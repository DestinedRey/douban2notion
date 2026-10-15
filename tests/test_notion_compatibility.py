"""Exercise the SDK used by the sync without contacting Notion."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx
from notion_client import Client
from github_heatmap.loader.notion_loader import NotionLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from notion_helper import NotionHelper


class NotionCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.responses = []

        def respond(request):
            self.requests.append(request)
            return httpx.Response(200, json=self.responses.pop(0))

        self.client = Client(
            auth="test-only",
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        self.helper = NotionHelper.__new__(NotionHelper)
        self.helper.client = self.client
        self.helper._NotionHelper__cache = {}
        self.sleep = patch("retrying.time.sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.client.close()

    def test_sync_reads_all_database_pages(self):
        self.responses = [
            {"results": [{"id": "first"}], "has_more": True, "next_cursor": "next"},
            {"results": [{"id": "second"}], "has_more": False, "next_cursor": None},
        ]
        rows = self.helper.query_all("test-database")
        self.assertEqual([row["id"] for row in rows], ["first", "second"])
        self.assertEqual(len(self.requests), 2)
        for request in self.requests:
            self.assertEqual(request.url.path, "/v1/databases/test-database/query")
            self.assertEqual(request.headers["Notion-Version"], "2022-06-28")
        self.assertEqual(json.loads(self.requests[1].content)["start_cursor"], "next")

    def test_actor_type_is_read_from_current_database(self):
        self.responses = [{"properties": {"演员": {"type": "rich_text"}}}]
        self.assertEqual(self.helper.get_property_type("test-movies", "演员"), "rich_text")
        self.assertEqual(self.requests[0].method, "GET")
        self.assertEqual(self.requests[0].url.path, "/v1/databases/test-movies")

    def test_existing_relation_is_reused_without_creating_a_page(self):
        self.responses = [{"results": [{"id": "existing-relation"}]}]
        relation = self.helper.get_relation_id("2026", "test-years", None)
        self.assertEqual(relation, "existing-relation")
        self.assertEqual(self.helper.get_relation_id("2026", "test-years", None), relation)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(
            json.loads(self.requests[0].content)["filter"],
            {"property": "标题", "title": {"equals": "2026"}},
        )

    def test_heatmap_accepts_the_workflows_database_id(self):
        loader = NotionLoader(
            2026, 2026, "notion", notion_token="test-only",
            database_id="test-days", date_prop_name="日期", value_prop_name="看过",
        )
        with patch("github_heatmap.loader.notion_loader.requests.post") as post:
            post.return_value.ok = True
            post.return_value.json.return_value = {
                "results": [], "has_more": False, "next_cursor": None,
            }
            self.assertEqual(loader.get_api_data(), [])
            self.assertEqual(
                post.call_args.args[0],
                "https://api.notion.com/v1/databases/test-days/query",
            )
            self.assertEqual(post.call_args.kwargs["headers"]["Notion-Version"], "2021-08-16")


if __name__ == "__main__":
    unittest.main()
