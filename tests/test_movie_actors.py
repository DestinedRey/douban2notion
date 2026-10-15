"""Verify movie writes after converting an oversized actor field to text."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import douban
import utils


class MovieActorsTest(unittest.TestCase):
    def run_insert(self, property_type, names):
        helper = Mock(movie_database_id="movies")
        helper.get_property_type.return_value = property_type
        helper.query_all.return_value = []
        entry = {
            "create_time": "2026-10-16T09:00:00+08:00", "status": "mark",
            "subject": {
                "title": "Test movie", "url": "https://movie.douban.com/subject/1/",
                "type": "movie", "pic": {"large": "https://example.com/cover.jpg"},
                "actors": [{"name": name} for name in names],
            },
        }
        with patch.object(douban, "notion_helper", helper, create=True), \
             patch.object(douban, "douban_name", "test-user", create=True), \
             patch.object(douban.CoverStore, "new_cover", return_value=({"files": []}, None)), \
             patch.object(douban, "fetch_subjects", side_effect=[[entry], [], []]):
            douban.insert_movie()
        return helper

    def test_text_actor_names_reach_create_without_truncation(self):
        names = [f"演员{i}" + "长" * 20 for i in range(100)]
        helper = self.run_insert("rich_text", names)
        properties = helper.create_page.call_args.kwargs["properties"]
        self.assertNotIn("multi_select", properties["演员"])
        chunks = properties["演员"]["rich_text"]
        self.assertEqual("".join(c["text"]["content"] for c in chunks), ",".join(names))
        self.assertTrue(all(len(c["text"]["content"]) <= 1024 for c in chunks))
        self.assertEqual(properties["状态"], {"status": {"name": "想看"}})
        helper.get_property_type.assert_called_once_with("movies", "演员")
        helper.update_page.assert_not_called()

    def test_legacy_multi_select_and_slash_names_still_work(self):
        helper = self.run_insert("multi_select", ["演员甲/Actor A", "演员乙"])
        actors = helper.create_page.call_args.kwargs["properties"]["演员"]
        self.assertEqual(actors, {"multi_select": [
            {"name": "演员甲"}, {"name": "Actor A"}, {"name": "演员乙"},
        ]})

    def test_missing_actors_do_not_clear_or_create_values(self):
        helper = self.run_insert("rich_text", [])
        self.assertNotIn("演员", helper.create_page.call_args.kwargs["properties"])

    def test_unsupported_actor_type_stops_before_writes(self):
        helper = Mock(movie_database_id="movies")
        helper.get_property_type.return_value = "relation"
        with patch.object(douban, "notion_helper", helper, create=True):
            with self.assertRaises(ValueError):
                douban.insert_movie()
        helper.query_all.assert_not_called()
        helper.create_page.assert_not_called()

    def test_excessive_text_is_rejected_instead_of_losing_names(self):
        with self.assertRaises(ValueError):
            utils.get_actor_property(["a" * (1024 * 100 + 1)], "rich_text")


if __name__ == "__main__":
    unittest.main()
