import io
import json
import tempfile
import unittest
from pathlib import Path

from velours_library.acquisition import (
    AcquisitionError,
    AcquisitionManager,
    SourcePolicy,
    SourceRule,
)
from velours_library.catalog import Library


PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(self, body=b"manual text", *, url="https://docs.example.com/manuals/widget.txt", headers=None, status=200):
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = headers or {"Content-Type": "text/plain", "Content-Length": str(len(body))}
        self.status = status

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request.full_url, timeout))
        return self.response


class AcquisitionTests(unittest.TestCase):
    def make_policy(self, **rule_overrides):
        values = dict(
            rule_id="manufacturer-docs",
            origin="https://docs.example.com",
            path_prefix="/manuals",
            source_label="manufacturer",
            trust_class="primary",
            allowed_content_types=("text/*", "application/pdf"),
            allow_private_network=False,
            rights_note="manufacturer reference",
            tags=("approved-acquisition",),
            max_bytes=1024,
        )
        values.update(rule_overrides)
        return SourcePolicy([SourceRule(**values)], default_max_bytes=2048)

    def test_acquire_stages_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            body = b"line one\nline two\n"
            opener = FakeOpener(
                FakeResponse(
                    body,
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Content-Length": str(len(body)),
                        "ETag": '"abc123"',
                        "Last-Modified": "Sat, 22 Aug 2026 12:00:00 GMT",
                    },
                )
            )
            manager = AcquisitionManager(
                library,
                self.make_policy(),
                opener=opener,
                resolver=lambda host: [PUBLIC_IP],
            )

            candidate, record = manager.acquire(
                "https://docs.example.com/manuals/widget.txt#section",
                title="Widget Manual",
                tags=["workshop"],
                version_label="2.1",
                stale_after="2027-08-01",
            )

            self.assertEqual(candidate.state, "staged")
            self.assertEqual(candidate.source, "manufacturer")
            self.assertEqual(candidate.trust_class, "primary")
            self.assertEqual(candidate.source_uri, "https://docs.example.com/manuals/widget.txt")
            self.assertEqual(candidate.tags, ("approved-acquisition", "workshop"))
            self.assertEqual(record.candidate_id, candidate.candidate_id)
            self.assertEqual(record.authority, "none")
            self.assertEqual(record.bytes, len(body))
            self.assertEqual(record.content_type, "text/plain")
            self.assertEqual(record.etag, '"abc123"')
            self.assertEqual(record.sha256, candidate.sha256)
            self.assertEqual(len(library.list_candidates("staged")), 1)
            with self.assertRaises(KeyError):
                library.inspect(candidate.candidate_id)

            records = manager.list_records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["candidate_id"], candidate.candidate_id)
            self.assertEqual(records[0]["authority"], "none")

    def test_rejects_unapproved_origin_before_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = FakeOpener(FakeResponse())
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=opener,
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.acquire(
                    "https://evil.example/manuals/widget.txt",
                    title="Wrong Host",
                )
            self.assertEqual(opener.calls, [])

    def test_rejects_path_outside_approved_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=FakeOpener(FakeResponse()),
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.authorize("https://docs.example.com/private/widget.txt")

    def test_rejects_private_network_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=FakeOpener(FakeResponse()),
                resolver=lambda host: ["192.168.1.20"],
            )
            with self.assertRaises(AcquisitionError):
                manager.authorize("https://docs.example.com/manuals/widget.txt")

    def test_private_network_requires_explicit_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(allow_private_network=True),
                opener=FakeOpener(FakeResponse()),
                resolver=lambda host: ["192.168.1.20"],
            )
            rule = manager.authorize("https://docs.example.com/manuals/widget.txt")
            self.assertTrue(rule.allow_private_network)

    def test_rejects_disallowed_content_type(self):
        with tempfile.TemporaryDirectory() as directory:
            opener = FakeOpener(
                FakeResponse(
                    b"binary",
                    headers={"Content-Type": "application/octet-stream", "Content-Length": "6"},
                )
            )
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=opener,
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.acquire(
                    "https://docs.example.com/manuals/widget.bin",
                    title="Binary",
                )
            self.assertEqual(library_candidates(manager), [])

    def test_rejects_declared_oversize_before_streaming(self):
        with tempfile.TemporaryDirectory() as directory:
            response = FakeResponse(
                b"small body",
                headers={"Content-Type": "text/plain", "Content-Length": "4096"},
            )
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(max_bytes=32),
                opener=FakeOpener(response),
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.acquire(
                    "https://docs.example.com/manuals/widget.txt",
                    title="Too Large",
                )
            self.assertEqual(library_candidates(manager), [])

    def test_rejects_stream_that_exceeds_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            body = b"x" * 100
            response = FakeResponse(
                body,
                headers={"Content-Type": "text/plain"},
            )
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(max_bytes=32),
                opener=FakeOpener(response),
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.acquire(
                    "https://docs.example.com/manuals/widget.txt",
                    title="Growing Body",
                )
            self.assertEqual(library_candidates(manager), [])
            acquisition_dir = Path(directory) / "acquisition"
            self.assertEqual(list(acquisition_dir.iterdir()), [])

    def test_optional_checksum_pin(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            body = b"known bytes"
            opener = FakeOpener(FakeResponse(body))
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=opener,
                resolver=lambda host: [PUBLIC_IP],
            )
            candidate, _ = manager.acquire(
                "https://docs.example.com/manuals/widget.txt",
                title="Pinned",
                expected_sha256=hashlib.sha256(body).hexdigest(),
            )
            self.assertEqual(candidate.sha256, hashlib.sha256(body).hexdigest())

    def test_checksum_mismatch_does_not_create_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = AcquisitionManager(
                Library(directory),
                self.make_policy(),
                opener=FakeOpener(FakeResponse(b"actual")),
                resolver=lambda host: [PUBLIC_IP],
            )
            with self.assertRaises(AcquisitionError):
                manager.acquire(
                    "https://docs.example.com/manuals/widget.txt",
                    title="Pinned",
                    expected_sha256="0" * 64,
                )
            self.assertEqual(library_candidates(manager), [])

    def test_policy_loader_is_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "schema": "velours.library.acquisition-policy.v1",
                        "sources": [
                            {
                                "id": "docs",
                                "origin": "https://docs.example.com",
                                "source_label": "manufacturer",
                                "trust_class": "primary",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            policy = SourcePolicy.load(policy_path)
            self.assertEqual(policy.rules[0].rule_id, "docs")

            bad_path = Path(directory) / "bad.json"
            bad_path.write_text(
                json.dumps({"schema": "wrong", "sources": []}),
                encoding="utf-8",
            )
            with self.assertRaises(AcquisitionError):
                SourcePolicy.load(bad_path)


def library_candidates(manager):
    return manager.library.list_candidates("staged")


if __name__ == "__main__":
    unittest.main()
