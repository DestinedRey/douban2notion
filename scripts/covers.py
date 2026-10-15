"""Store Douban covers in Notion instead of relying on hotlinked thumbnails."""

import hashlib
import time
from io import BytesIO
from urllib.parse import urlparse

import requests
from notion_client.errors import APIResponseError


IMAGE_HEADERS = {
    "User-Agent": "api-client/1 com.douban.frodo/7.0.0(204) Android/29 product/M2012K11AC vendor/Xiaomi model/M2012K11AC brand/Redmi rom/android network/wifi platform/mobile",
    "Referer": "https://www.douban.com/",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def image_type(data):
    """Reject HTML challenges and CDN errors even if the status/MIME says image."""
    if len(data) < 64:
        raise ValueError("Image response is empty or too small")
    if data.startswith(b"\xff\xd8\xff") and data.rstrip().endswith(b"\xff\xd9"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in data[-16:]:
        return "image/png", ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("Source returned non-image content")


def external_douban_url(file):
    if not file or file.get("type") != "external":
        return None
    url = file.get("external", {}).get("url", "")
    parsed = urlparse(url)
    if parsed.scheme == "https" and (parsed.hostname or "").endswith(".doubanio.com"):
        return url
    return None


def download_cover(url, session=None):
    if not external_douban_url({"type": "external", "external": {"url": url}}):
        raise ValueError("Cover is not an HTTPS Douban image")
    session = session or requests.Session()
    for attempt in range(3):
        try:
            with session.get(url, headers=IMAGE_HEADERS, timeout=(10, 30), stream=True) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise ValueError("Cover exceeds 5 MiB")
                data = bytes(content)
                mime, extension = image_type(data)
                return data, mime, extension
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


class CoverStore:
    def __init__(self, client):
        self.client = client
        self.session = requests.Session()
        self.cache = {}
        self.last_request = 0.0

    def call(self, method, **kwargs):
        for attempt in range(4):
            time.sleep(max(0, 0.36 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                return method(**kwargs)
            except APIResponseError as exc:
                if attempt == 3 or exc.status not in (429, 500, 502, 503, 504):
                    raise
                time.sleep(float(exc.headers.get("retry-after", 2 ** attempt)))

    def upload(self, url):
        if url in self.cache:
            return self.cache[url]
        data, mime, extension = download_cover(url, self.session)
        digest = hashlib.sha256(data).hexdigest()
        filename = "douban-" + digest[:24] + extension
        upload = self.call(self.client.file_uploads.create, filename=filename, content_type=mime)
        sent = self.call(self.client.file_uploads.send, file_upload_id=upload["id"],
                         file=(filename, BytesIO(data), mime))
        if sent.get("status") != "uploaded":
            raise RuntimeError("Notion did not confirm the image upload")
        result = {"type": "file_upload", "file_upload": {"id": upload["id"]}}
        self.cache[url] = result
        return result

    def new_cover(self, url):
        image = self.upload(url)
        return {"files": [{**image, "name": "Cover"}]}, image

    def repair_payload(self, page):
        original = page.get("properties", {}).get("封面", {}).get("files", [])
        files = []
        changed = False
        for file in original:
            url = external_douban_url(file)
            if url:
                files.append({**self.upload(url), "name": file.get("name", "Cover")})
                changed = True
            else:
                # Preserve other attachments rather than replacing the entire list.
                files.append({k: v for k, v in file.items() if k in ("name", "type", "external", "file")})
        payload = {}
        if changed:
            payload["properties"] = {"封面": {"files": files}}
        for field in ("icon", "cover"):
            url = external_douban_url(page.get(field))
            if url:
                payload[field] = self.upload(url)
        return payload
