import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from velours_library import filesystem_identity as identity
from filesystem_fixture import FilesystemFixture, UUID


class FilesystemIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "vault"
        self.root.mkdir()

    def test_expected_volume_is_verified_and_descriptor_closed(self):
        with FilesystemFixture(identity, self.root):
            with identity.verified_filesystem(self.root, UUID) as binding:
                fd = binding.fd
                self.assertEqual(binding.held_path.stat().st_ino, self.root.stat().st_ino)
                self.assertEqual(os.statvfs(str(binding.held_path)).f_blocks, os.statvfs(str(self.root)).f_blocks)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_path_missing_is_unavailable(self):
        with self.assertRaises(identity.FilesystemIdentityError):
            with identity.verified_filesystem(self.root / "missing", UUID):
                self.fail("missing path accepted")

    def test_legacy_missing_uuid_is_unavailable_without_inventory(self):
        with patch.object(identity, "_block_devices") as inventory:
            for uuid in (None, "", " ", "invalid/uuid", False):
                with self.subTest(uuid=uuid), self.assertRaises(identity.FilesystemIdentityError):
                    with identity.verified_filesystem(self.root, uuid):
                        self.fail("unconfigured identity accepted")
            inventory.assert_not_called()

    def test_mount_removed_but_directory_remains_is_unavailable(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.mounts = ""
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    self.fail("removed mount accepted")

    def test_wrong_device_is_unavailable_even_if_expected_uuid_exists_elsewhere(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.devices = [{"maj:min": "259:777", "uuid": UUID},
                               {"maj:min": fixture.device, "uuid": "other-filesystem"}]
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    self.fail("wrong device accepted")

    def test_duplicate_uuid_on_distinct_devices_is_ambiguous(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.devices.append({"maj:min": "259:777", "uuid": UUID})
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    self.fail("ambiguous UUID accepted")

    def test_aliases_for_the_same_device_are_not_duplicate_filesystems(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.devices.append(dict(fixture.devices[0]))
            with identity.verified_filesystem(self.root, UUID):
                pass

    def test_subdirectory_and_manifest_file_are_supported(self):
        child = self.root / "archive"
        child.mkdir()
        marker = child / ".velvet-vault.json"
        marker.write_text("presence marker only")
        with FilesystemFixture(identity, self.root), patch.object(os.path, "ismount", side_effect=AssertionError("ismount heuristic")):
            for path in (child, marker):
                with self.subTest(path=path), identity.verified_filesystem(path, UUID):
                    pass

    def test_bind_mount_uses_descriptor_mount_id_and_backing_device(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.mount_id = 702
            fixture.mounts += "702 1 %s /archive /fixture/bind\\040path rw - ext4 /dev/synthetic rw\n" % fixture.device
            with identity.verified_filesystem(self.root, UUID) as binding:
                self.assertEqual(binding.mount_id, 702)

    def test_overmount_cannot_be_hidden_by_matching_parent_mount(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.mount_id = 702
            fixture.mounts += "702 701 259:777 / /fixture/vault rw - ext4 /dev/wrong rw\n"
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    self.fail("wrong overmount accepted")

    def test_recovery_requires_fresh_uuid_observation(self):
        with FilesystemFixture(identity, self.root) as fixture:
            fixture.devices = []
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    pass
            fixture.devices = [{"maj:min": fixture.device, "uuid": UUID}]
            with identity.verified_filesystem(self.root, UUID):
                pass

    def test_path_replacement_during_operation_is_rejected(self):
        with FilesystemFixture(identity, self.root):
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID) as binding:
                    self.root.rename(self.root.with_name("old-vault"))
                    self.root.mkdir()
                    (binding.held_path / "held-reference.txt").write_text("fixture")
            self.assertFalse((self.root / "held-reference.txt").exists())

    def test_uuid_loss_during_operation_is_rejected(self):
        with FilesystemFixture(identity, self.root) as fixture:
            with self.assertRaises(identity.FilesystemIdentityError):
                with identity.verified_filesystem(self.root, UUID):
                    fixture.devices = []

    def test_symlink_target_is_rejected(self):
        link = self.root.with_name("link")
        link.symlink_to(self.root)
        with FilesystemFixture(identity, self.root), self.assertRaises(identity.FilesystemIdentityError):
            with identity.verified_filesystem(link, UUID):
                pass

    def test_unverifiable_system_data_fails_closed(self):
        with FilesystemFixture(identity, self.root):
            for failure in (PermissionError("fixture"), FileNotFoundError("lsblk"),
                            subprocess.TimeoutExpired("lsblk", 3), ValueError("bad JSON")):
                with self.subTest(failure=type(failure).__name__), patch.object(identity, "_block_devices", side_effect=failure):
                    with self.assertRaises(identity.FilesystemIdentityError):
                        with identity.verified_filesystem(self.root, UUID):
                            pass

    def test_malformed_or_conflicting_inventory_fails_closed(self):
        with FilesystemFixture(identity, self.root) as fixture:
            for document in ({}, {"blockdevices": None}, {"blockdevices": [{"uuid": UUID}]},
                             {"blockdevices": [{"maj:min": fixture.device, "uuid": UUID},
                                               {"maj:min": fixture.device, "uuid": "other"}]}):
                with self.subTest(document=document), patch.object(identity, "_block_devices", return_value=json.dumps(document)):
                    with self.assertRaises(identity.FilesystemIdentityError):
                        with identity.verified_filesystem(self.root, UUID):
                            pass

    def test_caller_error_is_not_misreported_as_identity_failure(self):
        with FilesystemFixture(identity, self.root):
            with self.assertRaisesRegex(ValueError, "caller-fixture"):
                with identity.verified_filesystem(self.root, UUID):
                    raise ValueError("caller-fixture")

    def test_inventory_command_is_read_only_bounded_and_explicit(self):
        with patch.object(identity.subprocess, "run") as run:
            run.return_value.stdout = '{"blockdevices": []}'
            self.assertEqual(identity._block_devices(), '{"blockdevices": []}')
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["lsblk", "--all", "--json", "--list", "--output", "MAJ:MIN,UUID"])
            self.assertEqual(kwargs["timeout"], 3.0)
            self.assertTrue(kwargs["check"])
            self.assertNotIn("shell", kwargs)
