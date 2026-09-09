# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

from velours_library import vault_cli
from velours_library.filesystem_identity import FilesystemIdentityError


class VaultCliPreflightTests(unittest.TestCase):
    @patch("velours_library.vault_cli.vault_main")
    @patch("velours_library.vault_cli.verified_filesystem", side_effect=FilesystemIdentityError("fixture-unavailable"))
    def test_production_root_refuses_when_not_mounted(self, verify, vault_main):
        result = vault_cli.main(["--root", "/srv/velvet", "status"])

        self.assertEqual(result, 3)
        vault_main.assert_not_called()
        verify.assert_called_once()

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.verified_filesystem")
    def test_production_root_delegates_when_identity_verified(self, verify, vault_main):
        args = ["--root", "/srv/velvet", "status"]

        result = vault_cli.main(args)

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(args)
        verify.assert_called_once()

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.verified_filesystem")
    def test_nonproduction_root_remains_available_for_tests(self, verify, vault_main):
        args = ["--root", "/tmp/velvet-fixture", "status"]

        result = vault_cli.main(args)

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(args)
        verify.assert_not_called()

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.verified_filesystem")
    def test_help_remains_available_without_vault(self, verify, vault_main):
        result = vault_cli.main(["--help"])

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(["--help"])
        verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
