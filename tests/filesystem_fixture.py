"""Synthetic kernel/lsblk observations around real temporary descriptors.

No mount or block-device operations occur. The same fixtures exercise both
repository copies of the approved filesystem identity contract.
"""

import json
import os
from unittest.mock import patch


UUID = "11111111-2222-3333-4444-555555555555"


class FilesystemFixture:
    def __init__(self, module, path):
        self.module = module
        self.path = path
        device = path.stat().st_dev
        self.device = "%d:%d" % (os.major(device), os.minor(device))
        self.mount_id = 701
        self.mounts = "701 1 %s / /fixture/vault rw - ext4 /dev/synthetic rw\n" % self.device
        self.devices = [{"maj:min": self.device, "uuid": UUID}]
        self.patches = []

    def read_text(self, path):
        if path == "/proc/self/mountinfo":
            return self.mounts
        if path.startswith("/proc/self/fdinfo/"):
            return "mnt_id:\t%d\n" % self.mount_id
        raise AssertionError("unexpected read: " + path)

    def __enter__(self):
        self.patches = [
            patch.object(self.module, "_read_text", side_effect=self.read_text),
            patch.object(self.module, "_block_devices", side_effect=lambda: json.dumps({"blockdevices": self.devices})),
        ]
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *args):
        for item in reversed(self.patches):
            item.stop()
