import json
import shutil
import sys
import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))

import server


class PlanningSchemeAccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = WEB_ROOT / "tests" / "tmp_planning_scheme_access"
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        self.tmp_dir.mkdir(parents=True)
        self.original_store = server.PLANNING_STORE
        server.PLANNING_STORE = server.planning_store.PlanningStore(root=self.tmp_dir)
        self.alice = {"id": 1, "username": "alice", "role": "user"}
        self.bob = {"id": 2, "username": "bob", "role": "user"}
        self.admin = {"id": 3, "username": "admin", "role": "admin"}

    def tearDown(self):
        server.PLANNING_STORE = self.original_store
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def json_body(self, body: bytes) -> dict:
        return json.loads(body.decode("utf-8"))

    def test_planning_api_filters_schemes_by_owner(self):
        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes",
            "POST",
            json.dumps({"name": "Alice方案"}, ensure_ascii=False).encode("utf-8"),
            current_user=self.alice,
        )
        self.assertEqual(status, 200)
        self.assertEqual(server.PLANNING_STORE.scheme_owner_username("Alice方案"), "alice")
        server.PLANNING_STORE.create_scheme("Bob方案", owner_username="bob")
        server.PLANNING_STORE.write_scheme("历史方案", server.planning_store.default_payload("历史方案"))

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes",
            "GET",
            b"",
            current_user=self.alice,
        )
        alice_names = [item["name"] for item in self.json_body(body)["schemes"]]
        self.assertEqual(status, 200)
        self.assertEqual(alice_names, ["Alice方案"])

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes",
            "GET",
            b"",
            current_user=self.admin,
        )
        admin_names = [item["name"] for item in self.json_body(body)["schemes"]]
        self.assertEqual(status, 200)
        self.assertEqual(admin_names, ["Alice方案", "Bob方案", "历史方案"])

    def test_non_admin_cannot_read_or_overwrite_other_users_scheme(self):
        server.PLANNING_STORE.create_scheme("Alice方案", owner_username="alice")
        server.PLANNING_STORE.create_scheme("Bob方案", owner_username="bob")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes/Alice方案",
            "GET",
            b"",
            current_user=self.bob,
        )
        denied_read = self.json_body(body)
        self.assertEqual(status, 404)
        self.assertEqual(denied_read["error"], "not_found")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes/copy",
            "POST",
            json.dumps(
                {"source": "Bob方案", "target": "Alice方案", "overwrite": True},
                ensure_ascii=False,
            ).encode("utf-8"),
            current_user=self.bob,
        )
        denied_overwrite = self.json_body(body)
        self.assertEqual(status, 404)
        self.assertEqual(denied_overwrite["error"], "not_found")
        self.assertEqual(server.PLANNING_STORE.scheme_owner_username("Alice方案"), "alice")

        status, headers, body = server.handle_planning_api_path(
            "/api/planning/schemes/Alice方案",
            "GET",
            b"",
            current_user=self.admin,
        )
        loaded = self.json_body(body)
        self.assertEqual(status, 200)
        self.assertEqual(loaded["scheme"], "Alice方案")


if __name__ == "__main__":
    unittest.main()
