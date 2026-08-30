from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from velours_library.catalog import Library
from velours_library.remote_client import RemoteLibraryClient, RemoteLibraryError
from velours_library.retrieval_service import PeerSecretStore, RetrievalAudit, build_handler
from http.server import ThreadingHTTPServer


class RemoteRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library_root = self.root / "library"
        self.library = Library(self.library_root)
        source = self.root / "manual.txt"
        source.write_text("Tiburon pulley alignment reference and belt routing notes.\n", encoding="utf-8")
        self.item = self.library.add(
            source,
            title="Workshop Reference",
            source="owner test fixture",
            trust_class="owner",
            source_uri="fixture://workshop-reference",
            tags=("vehicle", "manual"),
        )

        self.secret_dir = self.root / "peer-secrets"
        self.secret_dir.mkdir(mode=0o700)
        self.node_id = "mobile-founder-01"
        self.token = "0123456789abcdef0123456789abcdef"
        token_path = self.secret_dir / (self.node_id + ".token")
        token_path.write_text(self.token + "\n", encoding="utf-8")
        token_path.chmod(0o600)
        self.client_token = self.root / "client.token"
        self.client_token.write_text(self.token + "\n", encoding="utf-8")
        self.client_token.chmod(0o600)

        handler = build_handler(
            self.library,
            PeerSecretStore(self.secret_dir),
            RetrievalAudit(self.library_root / "audit" / "remote-retrieval.jsonl"),
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = self.server.server_address
        self.base_url = "http://%s:%d" % (host, port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def client(self) -> RemoteLibraryClient:
        return RemoteLibraryClient.from_token_file(
            self.base_url,
            node_id=self.node_id,
            token_file=self.client_token,
        )

    def test_health_discloses_only_safe_service_posture(self) -> None:
        health = self.client().health()
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["read_only"])
        self.assertTrue(health["reference_only"])
        self.assertEqual(health["authority"], "none")
        self.assertNotIn("library_root", health)

    def test_approved_mobile_node_can_search_home_library(self) -> None:
        result = self.client().search("pulley alignment", 5)
        self.assertEqual(result["node_id"], self.node_id)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["authority"], "none")
        self.assertTrue(result["results"])
        first = result["results"][0]
        self.assertEqual(first["item_id"], self.item.item_id)
        self.assertEqual(first["sha256"], self.item.sha256)
        self.assertEqual(first["trust_class"], "owner")
        self.assertNotIn("storage_path", first)
        self.assertNotIn("extracted_text_path", first)

    def test_approved_mobile_node_can_request_evidence_bundle(self) -> None:
        result = self.client().evidence("belt routing", 5)
        self.assertTrue(result["reference_only"])
        self.assertEqual(result["authority"], "none")
        evidence = result["evidence"]
        self.assertIsInstance(evidence, dict)
        self.assertTrue(evidence.get("results"))

    def test_wrong_token_is_rejected(self) -> None:
        client = RemoteLibraryClient(
            self.base_url,
            node_id=self.node_id,
            token="fedcba9876543210fedcba9876543210",
        )
        with self.assertRaises(RemoteLibraryError):
            client.search("pulley")

    def test_write_style_endpoint_does_not_exist(self) -> None:
        payload = json.dumps({"candidate_id": "anything"}).encode("utf-8")
        request = Request(
            self.base_url + "/v1/publish",
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.token,
                "X-Velvet-Node-ID": self.node_id,
                "Content-Type": "application/json",
            },
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 404)

    def test_audit_hashes_query_instead_of_recording_raw_text(self) -> None:
        query = "private task specific wording"
        self.client().search(query, 3)
        audit_path = self.library_root / "audit" / "remote-retrieval.jsonl"
        records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(records)
        last = records[-1]
        self.assertFalse(last["raw_query_recorded"])
        self.assertNotIn(query, json.dumps(last))
        self.assertEqual(last["node_id"], self.node_id)

    def test_peer_secret_files_must_not_be_group_or_world_readable(self) -> None:
        insecure = self.secret_dir / "insecure-node.token"
        insecure.write_text("a" * 32, encoding="utf-8")
        insecure.chmod(0o644)
        self.assertIsNone(PeerSecretStore(self.secret_dir).token_for("insecure-node"))


if __name__ == "__main__":
    unittest.main()
