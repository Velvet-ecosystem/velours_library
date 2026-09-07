import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from velours_library import filesystem_identity, vault, vault_cli
from velours_library.filesystem_identity import FilesystemIdentityError
from velours_library.vault import VaultManager
from filesystem_fixture import FilesystemFixture, UUID


@pytest.mark.parametrize("failure", ["missing-uuid", "wrong-device", "ambiguous-uuid", "mount-removed", "unverifiable"])
def test_production_initialize_refuses_before_any_write(tmp_path, failure):
    root = tmp_path / "vault"
    root.mkdir()
    with patch.object(vault, "DEFAULT_VAULT_ROOT", root), FilesystemFixture(filesystem_identity, root) as fixture:
        expected = UUID
        if failure == "missing-uuid":
            expected = None
        elif failure == "wrong-device":
            fixture.devices[0]["uuid"] = "wrong-filesystem"
        elif failure == "ambiguous-uuid":
            fixture.devices.append({"maj:min": "259:777", "uuid": UUID})
        elif failure == "mount-removed":
            fixture.mounts = ""
        elif failure == "unverifiable":
            fixture.devices = []
        with patch.dict(os.environ, {}, clear=True):
            manager = VaultManager(root, expected_filesystem_uuid=expected)
        with pytest.raises(FilesystemIdentityError):
            manager.initialize()
    assert list(root.iterdir()) == []


def test_missing_verified_root_is_not_recreated_on_host(tmp_path):
    root = tmp_path / "missing-vault"
    with pytest.raises(FilesystemIdentityError):
        VaultManager(root, expected_filesystem_uuid=UUID).initialize()
    assert not root.exists()


@pytest.mark.parametrize("kind", ["root", "subdirectory", "bind"])
def test_real_vault_operations_on_verified_filesystem_keep_public_paths(tmp_path, kind):
    root = tmp_path / "vault"
    root.mkdir()
    if kind == "subdirectory":
        root = root / "subdirectory"
        root.mkdir()
    with FilesystemFixture(filesystem_identity, root) as fixture:
        if kind == "bind":
            fixture.mount_id = 702
            fixture.mounts += "702 1 %s /subdirectory /fixture/bind rw - ext4 /dev/synthetic rw\n" % fixture.device
        manager = VaultManager(root, expected_filesystem_uuid=UUID)
        result = manager.initialize()
        assert result["catalog"] == str(root / "catalog/vault.sqlite3")
        assert result["health"]["root"] == str(root)
        media = root / "media/video/rolling/frame.bin"
        media.write_bytes(b"synthetic frame")
        record = manager.register_object(media, kind="video", source="acceptance-fixture")
        assert record["path"] == "media/video/rolling/frame.bin"
        assert manager.verify_object(record["object_id"])["verified"]
        assert manager.promote(record["object_id"], "PROTECTED")["retention"] == "PROTECTED"
        assert len(manager.list_objects()) == 1
        assert "/proc/self/fd" not in json.dumps(result)


def test_identity_loss_blocks_existing_manager_and_correct_return_recovers(tmp_path):
    with FilesystemFixture(filesystem_identity, tmp_path) as fixture:
        manager = VaultManager(tmp_path, expected_filesystem_uuid=UUID)
        manager.initialize()
        catalog = manager.catalog_path.read_bytes()
        correct = list(fixture.devices)
        fixture.devices = []
        for operation in (manager.health, manager.initialize, manager.list_objects):
            with pytest.raises(FilesystemIdentityError):
                operation()
        assert manager.catalog_path.read_bytes() == catalog
        fixture.devices = correct
        assert manager.initialize()["manifest"]["schema"] == "velvet.vault.v1"


def test_path_replacement_mid_operation_cannot_receive_vault_writes(tmp_path):
    root = tmp_path / "vault"
    original = tmp_path / "original-volume"
    root.mkdir()
    manager = VaultManager(root, expected_filesystem_uuid=UUID)
    initialize_catalog = manager._initialize_catalog

    def replace_path_before_catalog():
        root.rename(original)
        root.mkdir()
        initialize_catalog()

    with FilesystemFixture(filesystem_identity, root):
        with patch.object(manager, "_initialize_catalog", side_effect=replace_path_before_catalog):
            with pytest.raises(FilesystemIdentityError):
                manager.initialize()
        assert list(root.iterdir()) == []
        root.rmdir()
        original.rename(root)
        # Failed operation released its binding; fresh verification can recover.
        assert manager.initialize()["manifest"]["schema"] == "velvet.vault.v1"


def test_nested_foreign_filesystem_cannot_receive_catalog_writes(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    real_stat = Path.stat

    def foreign_catalog_stat(path, *args, **kwargs):
        metadata = real_stat(path, *args, **kwargs)
        if path.name == "catalog":
            values = list(metadata)
            values[2] = os.makedev(259, 777)
            return os.stat_result(values)
        return metadata

    with FilesystemFixture(filesystem_identity, tmp_path), patch.object(Path, "stat", foreign_catalog_stat):
        with pytest.raises(FilesystemIdentityError):
            VaultManager(tmp_path, expected_filesystem_uuid=UUID).initialize()
    assert list(catalog.iterdir()) == []


def test_cli_uses_explicit_uuid_and_reports_wrong_volume_without_writes(tmp_path, capsys):
    root = tmp_path / "vault"
    root.mkdir()
    args = ["--root", str(root), "--expected-filesystem-uuid", UUID, "init"]
    with FilesystemFixture(filesystem_identity, root) as fixture:
        fixture.devices[0]["uuid"] = "other"
        assert vault_cli.main(args) == 3
        refusal = json.loads(capsys.readouterr().err)
        assert refusal["schema"] == "velvet.vault.preflight.v1"
        assert refusal["state"] == "vault-unavailable"
        assert refusal["authority"] == "none"
        assert list(root.iterdir()) == []
        fixture.devices[0]["uuid"] = UUID
        assert vault_cli.main(args) == 0
        assert json.loads(capsys.readouterr().out)["manifest"]["authority"] == "none"


def test_production_subdirectory_requires_identity_and_environment_supplies_it(tmp_path):
    child = tmp_path / "library-subvault"
    child.mkdir()
    with patch.object(vault, "DEFAULT_VAULT_ROOT", tmp_path), patch.dict(os.environ, {}, clear=True):
        with pytest.raises(FilesystemIdentityError):
            VaultManager(child).initialize()
        with FilesystemFixture(filesystem_identity, child), patch.dict(os.environ, {"VELVET_VAULT_FILESYSTEM_UUID": UUID}):
            assert VaultManager(child).initialize()["health"]["root"] == str(child)


def test_intake_preflight_retains_existing_unprivileged_mount_guards():
    unit = (Path(__file__).parents[1] / "examples/systemd/velour-library-drop.service").read_text()
    for required in ("ConditionPathIsMountPoint=/srv/velvet", "User=velvet", "NoNewPrivileges=true",
                     "ReadWritePaths=/srv/velvet/library /srv/velvet/staging/library-drop",
                     "EnvironmentFile=-/etc/velvet/vault.env",
                     "ExecStartPre=/usr/local/bin/velour-vault --root /srv/velvet status"):
        assert required in unit
