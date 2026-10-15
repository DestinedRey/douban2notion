import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import httpx
from notion_client import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from covers import CoverStore, download_cover, external_douban_url, image_type


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100 + b"\xff\xd9"
URL = "https://img3.doubanio.com/view/subject/l/public/example.jpg"


class CoverTest(unittest.TestCase):
    def test_html_200_and_cdn_error_cannot_be_uploaded(self):
        for data in (b"<script>challenge</script>" * 10, b"cdn error 001\n"):
            with self.assertRaises(ValueError):
                image_type(data)

    def test_download_checks_status_and_image_bytes(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [JPEG]
        session = Mock()
        session.get.return_value = response
        self.assertEqual(download_cover(URL, session), (JPEG, "image/jpeg", ".jpg"))
        response.raise_for_status.assert_called_once()
        self.assertEqual(session.get.call_args.kwargs["timeout"], (10, 30))

    def test_rejects_non_douban_sources(self):
        for url in ("http://img3.doubanio.com/a.jpg", "https://doubanio.com.evil.invalid/a.jpg", "file:///etc/passwd"):
            self.assertIsNone(external_douban_url({"type": "external", "external": {"url": url}}))

    def test_sdk_upload_reuses_id_for_cover_and_icon(self):
        sent = []
        replies = [{"id": "upload-id"}, {"id": "upload-id", "status": "uploaded"}]
        def respond(request):
            sent.append(request)
            return httpx.Response(200, json=replies.pop(0))
        client = Client(auth="test-only", client=httpx.Client(transport=httpx.MockTransport(respond)))
        store = CoverStore(client)
        with patch("covers.download_cover", return_value=(JPEG, "image/jpeg", ".jpg")), patch("covers.time.sleep"):
            prop, icon = store.new_cover(URL)
            store.upload(URL)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0].url.path, "/v1/file_uploads")
        self.assertEqual(sent[1].url.path, "/v1/file_uploads/upload-id/send")
        self.assertIn("multipart/form-data", sent[1].headers["Content-Type"])
        self.assertIn(JPEG, sent[1].content)
        self.assertEqual(prop["files"][0]["file_upload"], icon["file_upload"])
        client.close()

    def test_migration_preserves_other_attachments_and_fields(self):
        external = {"type": "external", "external": {"url": URL}}
        other = {"type": "external", "name": "User image", "external": {"url": "https://example.com/keep.jpg"}}
        page = {"properties": {"封面": {"files": [{**external, "name": "Cover"}, other]}, "评分": {"select": {"name": "5"}}},
                "icon": external, "cover": None}
        store = CoverStore(Mock())
        store.upload = Mock(return_value={"type": "file_upload", "file_upload": {"id": "image"}})
        payload = store.repair_payload(page)
        self.assertEqual(set(payload), {"properties", "icon"})
        self.assertEqual(set(payload["properties"]), {"封面"})
        self.assertEqual(payload["properties"]["封面"]["files"][1], other)
        self.assertEqual(page["properties"]["封面"]["files"][0]["type"], "external")

    def test_native_images_are_skipped(self):
        store = CoverStore(Mock())
        self.assertEqual(store.repair_payload({"properties": {"封面": {"files": [{"type": "file", "file": {"url": "https://notion.so/file"}}]}}, "icon": {"type": "emoji", "emoji": "🎬"}}), {})


if __name__ == "__main__":
    unittest.main()
