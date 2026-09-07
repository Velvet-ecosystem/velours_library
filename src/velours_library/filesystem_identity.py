# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Linux filesystem UUID binding for an explicitly selected path.

The identical bounded verifier is maintained in Runtime and velours_library.
No mounting, UUID enrollment, privilege escalation or storage fallback occurs.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class FilesystemIdentityError(OSError):
    """The selected path cannot be bound to the configured mounted filesystem."""


def _uuid(value: Optional[str]) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", value):
        raise FilesystemIdentityError("expected-filesystem-uuid-missing-or-invalid")
    return value.casefold()


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as stream:
        text = stream.read(2 * 1024 * 1024 + 1)
    if len(text) > 2 * 1024 * 1024:
        raise FilesystemIdentityError("filesystem-identity-data-exceeds-bound")
    return text


def _block_devices() -> str:
    # Explicit columns/list shape work with Founder's util-linux 2.34. Missing
    # udev/UUID information or inaccessible device metadata fails closed.
    result = subprocess.run(
        ["lsblk", "--all", "--json", "--list", "--output", "MAJ:MIN,UUID"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=3.0, check=True, encoding="utf-8",
    )
    if len(result.stdout) > 2 * 1024 * 1024:
        raise FilesystemIdentityError("filesystem-identity-data-exceeds-bound")
    return result.stdout


def _expected_device(expected_uuid: str) -> str:
    entries = json.loads(_block_devices())["blockdevices"]
    if not isinstance(entries, list) or len(entries) > 4096:
        raise FilesystemIdentityError("filesystem-device-inventory-invalid")
    identities = {}
    for entry in entries:
        if entry.get("children"):
            raise FilesystemIdentityError("filesystem-device-inventory-not-flat")
        device = entry["maj:min"]
        uuid = entry.get("uuid")
        if not isinstance(device, str) or not re.fullmatch(r"\d+:\d+", device):
            raise FilesystemIdentityError("filesystem-device-inventory-invalid")
        if uuid is not None and not isinstance(uuid, str):
            raise FilesystemIdentityError("filesystem-device-inventory-invalid")
        normalized = uuid.casefold() if uuid else None
        if device in identities and identities[device] != normalized:
            raise FilesystemIdentityError("filesystem-device-inventory-ambiguous")
        identities[device] = normalized
    matches = [device for device, uuid in identities.items() if uuid == expected_uuid]
    if len(matches) != 1:
        raise FilesystemIdentityError("expected-filesystem-uuid-absent-or-ambiguous")
    return matches[0]


def _mount_id(fd: int) -> int:
    values = [line.split()[1] for line in _read_text("/proc/self/fdinfo/%d" % fd).splitlines()
              if line.startswith("mnt_id:")]
    if len(values) != 1 or not values[0].isdigit():
        raise FilesystemIdentityError("filesystem-mount-id-unverifiable")
    return int(values[0])


def _mounted_device(mount_id: int) -> str:
    matches = []
    for line in _read_text("/proc/self/mountinfo").splitlines():
        fields = line.split()
        if len(fields) < 10 or "-" not in fields[6:]:
            raise FilesystemIdentityError("filesystem-mount-table-invalid")
        if fields[0] == str(mount_id):
            matches.append(fields[2])
    if len(matches) != 1:
        raise FilesystemIdentityError("filesystem-mount-absent-or-ambiguous")
    return matches[0]


def _open_path(path: Path) -> int:
    fd = os.open(str(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        mode = os.fstat(fd).st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise FilesystemIdentityError("filesystem-target-not-file-or-directory")
    except BaseException:
        os.close(fd)
        raise
    return fd


class VerifiedFilesystem:
    """A held filesystem reference, valid only inside its context manager."""

    def __init__(self, path: Path, expected_uuid: str, fd: int) -> None:
        self.path = path
        self.expected_uuid = expected_uuid
        self.fd = fd
        self.metadata = os.fstat(fd)
        self.mount_id = _mount_id(fd)

    @property
    def held_path(self) -> Path:
        return Path("/proc/self/fd/%d" % self.fd)

    def check_current(self) -> None:
        device = "%d:%d" % (os.major(self.metadata.st_dev), os.minor(self.metadata.st_dev))
        if _expected_device(self.expected_uuid) != device:
            raise FilesystemIdentityError("filesystem-identity-mismatch")
        self.check_path_current()

    def check_path_current(self) -> None:
        device = "%d:%d" % (os.major(self.metadata.st_dev), os.minor(self.metadata.st_dev))
        if _mounted_device(self.mount_id) != device:
            raise FilesystemIdentityError("filesystem-mount-changed")
        current = _open_path(self.path)
        try:
            metadata = os.fstat(current)
            if ((metadata.st_dev, metadata.st_ino) != (self.metadata.st_dev, self.metadata.st_ino)
                    or _mount_id(current) != self.mount_id):
                raise FilesystemIdentityError("filesystem-target-changed")
        finally:
            os.close(current)


@contextmanager
def verified_filesystem(path: Path, expected_filesystem_uuid: Optional[str]) -> Iterator[VerifiedFilesystem]:
    """Bind an existing file/directory, including subdirectories and bind mounts.

    The actual descriptor mount ID selects its mount record: no pathname-prefix
    or ismount heuristic can confuse a subdirectory, bind mount or overmount.
    Capacity and I/O may use held_path; recheck the configured path on exit.
    """
    fd = None
    try:
        try:
            expected_uuid = _uuid(expected_filesystem_uuid)
            fd = _open_path(path)
            binding = VerifiedFilesystem(path, expected_uuid, fd)
            binding.check_current()
        except FilesystemIdentityError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
                subprocess.SubprocessError) as exc:
            raise FilesystemIdentityError("filesystem-identity-unverifiable") from exc
        yield binding
        try:
            binding.check_current()
        except FilesystemIdentityError:
            raise
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
                subprocess.SubprocessError) as exc:
            raise FilesystemIdentityError("filesystem-identity-unverifiable") from exc
    finally:
        if fd is not None:
            os.close(fd)
