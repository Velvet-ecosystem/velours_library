# SPDX-License-Identifier: GPL-3.0-only

import os

import pytest

from velours_library.vault import (
    RetentionClass,
    VaultManager,
    VaultPolicy,
)


def test_initialize_creates_shared_layout_and_catalog(tmp_path):
    manager = VaultManager(tmp_path / "vault")
    result = manager.initialize()

    assert (tmp_path / "vault" / "library").is_dir()
    assert (tmp_path / "vault" / "media" / "video" / "rolling").is_dir()
    assert (tmp_path / "vault" / "receipts" / "emergency").is_dir()
    assert (tmp_path / "vault" / "catalog" / "vault.sqlite3").is_file()
    assert result["manifest"]["schema"] == "velvet.vault.v1"
    assert result["manifest"]["authority"] == "none"


def test_register_verify_and_promote_object(tmp_path):
    root = tmp_path / "vault"
    manager = VaultManager(root)
    manager.initialize()
    media = root / "media" / "video" / "rolling" / "front.bin"
    media.write_bytes(b"front camera fixture")

    record = manager.register_object(
        media,
        kind="video",
        source="camera.front",
        retention=RetentionClass.ROLLING,
        related_event="evt-1",
        tags=("front", "fixture"),
    )

    listed = manager.list_objects(retention=RetentionClass.ROLLING)
    assert listed[0]["object_id"] == record["object_id"]
    assert listed[0]["path"] == "media/video/rolling/front.bin"
    assert manager.verify_object(record["object_id"])["verified"] is True

    promoted = manager.promote(record["object_id"], RetentionClass.PROTECTED)
    assert promoted["retention"] == "PROTECTED"
    assert manager.list_objects(retention=RetentionClass.PROTECTED)[0]["object_id"] == record["object_id"]


def test_retention_cannot_be_downgraded(tmp_path):
    root = tmp_path / "vault"
    manager = VaultManager(root)
    manager.initialize()
    media = root / "media" / "video" / "retained" / "incident.bin"
    media.write_bytes(b"incident")

    record = manager.register_object(
        media,
        kind="video",
        source="camera.front",
        retention=RetentionClass.PROTECTED,
    )

    with pytest.raises(ValueError, match="only be promoted"):
        manager.promote(record["object_id"], RetentionClass.ROLLING)


def test_object_must_remain_inside_vault_root(tmp_path):
    root = tmp_path / "vault"
    manager = VaultManager(root)
    manager.initialize()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")

    with pytest.raises(ValueError, match="inside vault root"):
        manager.register_object(outside, kind="video", source="fixture")


def test_symlink_object_is_rejected(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")

    root = tmp_path / "vault"
    manager = VaultManager(root)
    manager.initialize()
    target = root / "media" / "video" / "rolling" / "target.bin"
    target.write_bytes(b"target")
    link = root / "media" / "video" / "rolling" / "link.bin"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        manager.register_object(link, kind="video", source="fixture")


def test_policy_only_allows_automatic_purge_for_cache_and_rolling():
    policy = VaultPolicy()
    assert policy.may_auto_purge(RetentionClass.CACHE)
    assert policy.may_auto_purge(RetentionClass.ROLLING)
    assert not policy.may_auto_purge(RetentionClass.STANDARD)
    assert not policy.may_auto_purge(RetentionClass.PROTECTED)
    assert not policy.may_auto_purge(RetentionClass.PERMANENT)


class _Stat:
    f_frsize = 1
    f_bsize = 1
    f_blocks = 100
    f_bavail = 12


def test_health_enters_cleanup_due_before_hard_reserve(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    manager = VaultManager(root, statvfs_provider=lambda _: _Stat())

    health = manager.health()

    assert health.state == "cleanup_due"
    assert health.cleanup_recommended is True
    assert health.reserve_guard_active is False
