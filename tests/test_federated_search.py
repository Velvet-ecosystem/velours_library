import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from velours_library.catalog import Library
from velours_library.federated_search import (
    FederatedSearchEngine,
    KiwixSearchProvider,
)


class _FakeWeb:
    def search(self, query):
        return [
            {
                "result_id": "w1",
                "title": "Web %s" % query,
                "source": "example.org",
                "url": "https://example.org/ref",
                "summary": "web summary",
            }
        ]


class _BrokenProvider:
    def search(self, query, *args):
        raise RuntimeError("provider offline")


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _Response:
    def __init__(self, payload):
        self.payload = payload.encode("utf-8")
        self.headers = _Headers({"Content-Type": "application/xml", "Content-Length": str(len(self.payload))})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amount=-1):
        return self.payload if amount < 0 else self.payload[:amount]


class _KiwixOpener:
    def open(self, request, timeout=None):
        if "/catalog/v2/entries" in request.full_url:
            return _Response(
                """<?xml version='1.0'?>
                <feed xmlns='http://www.w3.org/2005/Atom'>
                  <entry>
                    <title>Wikipedia English</title>
                    <link href='/content/wikipedia_en_all_maxi_2026-01/' />
                  </entry>
                </feed>"""
            )
        if "/search?" in request.full_url:
            return _Response(
                """<?xml version='1.0'?>
                <results>
                  <result>
                    <title>Automotive Grade Linux</title>
                    <link href='/content/wikipedia_en_all_maxi_2026-01/A/Automotive_Grade_Linux' />
                    <snippet>Automotive Grade Linux is an open source project.</snippet>
                  </result>
                </results>"""
            )
        raise AssertionError(request.full_url)


class FederatedSearchTests(unittest.TestCase):
    def _library(self, root):
        source = Path(root) / "agl.txt"
        source.write_text(
            "Automotive Grade Linux is an open source automotive software platform.",
            encoding="utf-8",
        )
        library = Library(Path(root) / "library")
        library.add(
            source,
            title="AGL notes",
            source="owner notes",
            trust_class="owner",
        )
        return library

    def test_federates_library_zim_and_web_without_granting_authority(self):
        with TemporaryDirectory() as temporary:
            library = self._library(temporary)
            kiwix = KiwixSearchProvider("http://127.0.0.1:8080", opener=_KiwixOpener())
            payload = FederatedSearchEngine(
                library,
                kiwix_provider=kiwix,
                web_provider=_FakeWeb(),
            ).search("Automotive Grade Linux", 5)

            self.assertEqual(payload["schema"], "velour.federated_search.v1")
            self.assertEqual(payload["authority"], "none")
            self.assertTrue(payload["external_reference"])
            self.assertEqual(payload["sources"]["library"]["status"], "ok")
            self.assertEqual(payload["sources"]["zim"]["status"], "ok")
            self.assertEqual(payload["sources"]["web"]["status"], "ok")
            providers = {row["provider"] for row in payload["results"]}
            self.assertEqual(providers, {"library", "zim", "web"})
            for row in payload["results"]:
                self.assertEqual(row["authority"], "none")
                self.assertTrue(row["external_reference"])

    def test_optional_provider_failure_does_not_hide_local_results(self):
        with TemporaryDirectory() as temporary:
            library = self._library(temporary)
            payload = FederatedSearchEngine(
                library,
                kiwix_provider=_BrokenProvider(),
                web_provider=_BrokenProvider(),
            ).search("automotive", 5)
            self.assertGreater(payload["sources"]["library"]["count"], 0)
            self.assertEqual(payload["sources"]["zim"]["status"], "unavailable")
            self.assertEqual(payload["sources"]["web"]["status"], "unavailable")
            self.assertTrue(any(row["provider"] == "library" for row in payload["results"]))

    def test_disabled_sources_are_explicit(self):
        with TemporaryDirectory() as temporary:
            library = self._library(temporary)
            payload = FederatedSearchEngine(library).search("automotive", 5)
            self.assertEqual(payload["sources"]["zim"], {"status": "disabled", "count": 0})
            self.assertEqual(payload["sources"]["web"], {"status": "disabled", "count": 0})

    def test_kiwix_is_loopback_only(self):
        with self.assertRaises(ValueError):
            KiwixSearchProvider("http://192.168.1.10:8080")
        with self.assertRaises(ValueError):
            KiwixSearchProvider("https://example.org")
        self.assertEqual(
            KiwixSearchProvider("http://localhost:8080").endpoint,
            "http://localhost:8080",
        )

    def test_kiwix_search_uses_public_catalog_and_search_routes(self):
        provider = KiwixSearchProvider("http://127.0.0.1:8080", opener=_KiwixOpener())
        rows = provider.search("Automotive Grade Linux", 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "zim")
        self.assertEqual(rows[0]["source"], "Kiwix/wikipedia_en_all_maxi_2026-01")
        self.assertTrue(str(rows[0]["uri"]).startswith("http://127.0.0.1:8080/content/"))

    def test_query_and_limit_are_bounded(self):
        with TemporaryDirectory() as temporary:
            library = self._library(temporary)
            engine = FederatedSearchEngine(library)
            with self.assertRaises(Exception):
                engine.search("", 5)
            with self.assertRaises(Exception):
                engine.search("x", 26)


if __name__ == "__main__":
    unittest.main()
