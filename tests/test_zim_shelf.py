from pathlib import Path

import pytest

from velours_library.zim_shelf import ZimShelf


def test_zim_shelf_inventory_keeps_large_reference_outside_canonical_archive(tmp_path: Path):
    shelf = ZimShelf(tmp_path / "library")
    shelf.prepare()
    zim = shelf.shelf_dir / "wikipedia_en_test.zim"; zim.write_bytes(b"zim-data")
    inventory = shelf.write_inventory(hash_files=True)
    assert inventory["archives"][0]["root_path"] == "external/zim/wikipedia_en_test.zim"
    assert inventory["archives"][0]["sha256_parts"]["external/zim/wikipedia_en_test.zim"]
    assert inventory["read_only_reference_shelf"] is True
    assert not (shelf.library_root / "archive" / "sha256").exists()


def test_split_zim_is_one_archive_with_multiple_parts(tmp_path: Path):
    shelf = ZimShelf(tmp_path / "library"); shelf.prepare()
    (shelf.shelf_dir / "wiki.zimaa").write_bytes(b"a")
    (shelf.shelf_dir / "wiki.zimab").write_bytes(b"bb")
    archives = shelf.scan()
    assert len(archives) == 1
    assert archives[0].parts == ["external/zim/wiki.zimaa", "external/zim/wiki.zimab"]
    assert archives[0].total_bytes == 3


def test_serve_command_defaults_to_loopback_and_blocks_external(monkeypatch, tmp_path: Path):
    shelf = ZimShelf(tmp_path / "library"); shelf.prepare()
    (shelf.shelf_dir / "wiki.zim").write_bytes(b"zim")
    monkeypatch.setattr("velours_library.zim_shelf.shutil.which", lambda name: "/usr/bin/kiwix-serve")
    command = shelf.serve_command()
    assert "--address=127.0.0.1" in command
    assert "--port=8080" in command
    assert "--blockexternal" in command
    assert command[-1].endswith("wiki.zim")


def test_non_loopback_binding_requires_explicit_permission(monkeypatch, tmp_path: Path):
    shelf = ZimShelf(tmp_path / "library"); shelf.prepare()
    (shelf.shelf_dir / "wiki.zim").write_bytes(b"zim")
    monkeypatch.setattr("velours_library.zim_shelf.shutil.which", lambda name: "/usr/bin/kiwix-serve")
    with pytest.raises(ValueError):
        shelf.serve_command(address="192.168.1.20")
    command = shelf.serve_command(address="192.168.1.20", allow_network=True)
    assert "--address=192.168.1.20" in command


def test_missing_kiwix_binary_fails_closed(monkeypatch, tmp_path: Path):
    shelf = ZimShelf(tmp_path / "library"); shelf.prepare()
    (shelf.shelf_dir / "wiki.zim").write_bytes(b"zim")
    monkeypatch.setattr("velours_library.zim_shelf.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError):
        shelf.serve_command()
