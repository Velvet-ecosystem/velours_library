import io
import json
import unittest
from unittest.mock import patch

from velours_library import federated_search_cli


class _FakeWeb:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query):
        return [
            {
                "result_id": "w1",
                "title": "Web result",
                "source": "example.org",
                "url": "https://example.org/result",
                "summary": "still available",
            }
        ]


class FederatedSearchCliTests(unittest.TestCase):
    def test_library_permission_failure_does_not_suppress_web_results(self):
        output = io.StringIO()
        with patch.object(
            federated_search_cli,
            "Library",
            side_effect=PermissionError(13, "Permission denied", "/srv/velvet/library"),
        ), patch.object(
            federated_search_cli,
            "SearxngSearchProvider",
            _FakeWeb,
        ), patch("sys.stdout", output):
            code = federated_search_cli.main(
                [
                    "automotive",
                    "--root",
                    "/srv/velvet/library",
                    "--web-endpoint",
                    "https://search.example/search",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["sources"]["library"]["status"], "unavailable")
        self.assertIn("Permission denied", payload["sources"]["library"]["message"])
        self.assertEqual(payload["sources"]["web"]["status"], "ok")
        self.assertTrue(any(row["provider"] == "web" for row in payload["results"]))
        self.assertEqual(payload["authority"], "none")
        self.assertTrue(payload["external_reference"])


if __name__ == "__main__":
    unittest.main()
