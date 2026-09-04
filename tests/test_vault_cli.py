# SPDX-License-Identifier: GPL-3.0-only

import unittest
from unittest.mock import patch

from velours_library import vault_cli


class VaultCliPreflightTests(unittest.TestCase):
    @patch("velours_library.vault_cli.vault_main")
    @patch("velours_library.vault_cli.os.path.ismount", return_value=False)
    def test_production_root_refuses_when_not_mounted(self, ismount, vault_main):
        result = vault_cli.main(["--root", "/srv/velvet", "status"])

        self.assertEqual(result, 3)
        vault_main.assert_not_called()
        ismount.assert_called_once_with("/srv/velvet")

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.os.path.ismount", return_value=True)
    def test_production_root_delegates_when_mounted(self, ismount, vault_main):
        args = ["--root", "/srv/velvet", "status"]

        result = vault_cli.main(args)

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(args)
        ismount.assert_called_once_with("/srv/velvet")

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.os.path.ismount", return_value=False)
    def test_nonproduction_root_remains_available_for_tests(self, ismount, vault_main):
        args = ["--root", "/tmp/velvet-fixture", "status"]

        result = vault_cli.main(args)

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(args)
        ismount.assert_not_called()

    @patch("velours_library.vault_cli.vault_main", return_value=0)
    @patch("velours_library.vault_cli.os.path.ismount", return_value=False)
    def test_help_remains_available_without_vault(self, ismount, vault_main):
        result = vault_cli.main(["--help"])

        self.assertEqual(result, 0)
        vault_main.assert_called_once_with(["--help"])
        ismount.assert_not_called()


if __name__ == "__main__":
    unittest.main()
