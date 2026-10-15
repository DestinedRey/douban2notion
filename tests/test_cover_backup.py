import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

try:
    from repair_covers import prepare, cipher, apply, unaffected
except ImportError:
    prepare = None


@unittest.skipIf(prepare is None, "cryptography is only required by the repair workflow")
class BackupTest(unittest.TestCase):
    def page(self):
        return {"id": "page1", "created_time": "2026-10-16", "archived": False,
                "properties": {"封面": {"type": "files", "files": [{"type": "external", "name": "Cover", "external": {"url": "https://img3.doubanio.com/cover.jpg"}}]},
                               "短评": {"type": "rich_text", "rich_text": [{"plain_text": "keep me"}]}},
                "icon": {"type": "emoji", "emoji": "🎬"}, "cover": None}

    def test_backup_is_authenticated_and_round_trips_all_fields(self):
        helper = Mock(movie_database_id="movies")
        page = self.page()
        helper.query_all.return_value = [page]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"NOTION_TOKEN": "test-only"}):
            prepare(helper, "movie", Path(tmp), 1)
            data = (Path(tmp) / "movie-before.enc").read_bytes()
            self.assertNotIn(b"keep me", data)
            restored = json.loads(cipher("movie").decrypt(data))
            self.assertEqual(restored["rows"], [page])
            self.assertEqual(restored["total"], 1)

    def test_invalid_backup_stops_before_upload_or_page_write(self):
        helper = Mock(movie_database_id="movies")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"NOTION_TOKEN": "test-only"}):
            (Path(tmp) / "movie-before.enc").write_bytes(b"invalid")
            with self.assertRaises(Exception):
                apply(helper, "movie", Path(tmp))
        helper.client.pages.update.assert_not_called()
        helper.client.file_uploads.create.assert_not_called()

    def test_noncover_verification_includes_reviews_and_ratings(self):
        before = self.page()
        after = json.loads(json.dumps(before))
        after["properties"]["短评"]["rich_text"] = []
        self.assertNotEqual(unaffected(before), unaffected(after))


if __name__ == "__main__":
    unittest.main()
