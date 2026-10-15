"""Store Douban covers in Notion instead of relying on hotlinked thumbnails."""

import hashlib
import re
import time
from io import BytesIO
from urllib.parse import urlparse

import requests
from notion_client.errors import APIResponseError
from douban_api import DOUBAN_API_HOST, DOUBAN_API_KEY, headers as API_HEADERS


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


def current_cover_urls(subject_url, session):
    """Resolve replacements only from the exact record's Douban subject."""
    parsed = urlparse(subject_url or "")
    match = re.fullmatch(r"/subject/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname not in ("movie.douban.com", "book.douban.com") or not match:
        raise ValueError("Cannot verify the Douban subject for a replacement cover")
    kind = parsed.hostname.split(".")[0]
    subject_id = match.group(1)
    for attempt in range(3):
        try:
            response = session.get(f"https://{DOUBAN_API_HOST}/api/v2/{kind}/{subject_id}",
                                   headers=API_HEADERS, params={"apiKey": DOUBAN_API_KEY}, timeout=(10, 30))
            response.raise_for_status()
            subject = response.json()
            if str(subject.get("id")) != subject_id:
                raise ValueError("Replacement metadata belongs to a different Douban subject")
            pictures = subject.get("pic") or {}
            urls = []
            for size in ("large", "normal"):
                url = pictures.get(size)
                if url and url not in urls and external_douban_url({"type": "external", "external": {"url": url}}):
                    urls.append(url)
            if not urls:
                raise ValueError("Douban subject has no valid current cover")
            return urls
        except requests.RequestException:
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

    def upload(self, url, subject_url=None):
        if url in self.cache:
            return self.cache[url]
        source = url
        try:
            data, mime, extension = download_cover(url, self.session)
        except (requests.RequestException, ValueError):
            if not subject_url:
                raise
            for replacement in current_cover_urls(subject_url, self.session):
                if replacement == url:
                    continue
                if replacement in self.cache:
                    self.cache[url] = self.cache[replacement]
                    return self.cache[url]
                try:
                    data, mime, extension = download_cover(replacement, self.session)
                    source = replacement
                    break
                except (requests.RequestException, ValueError):
                    continue
            else:
                raise ValueError("Original and current Douban covers are unavailable")
        digest = hashlib.sha256(data).hexdigest()
        filename = "douban-" + digest[:24] + extension
        upload = self.call(self.client.file_uploads.create, filename=filename, content_type=mime)
        sent = self.call(self.client.file_uploads.send, file_upload_id=upload["id"],
                         file=(filename, BytesIO(data), mime))
        if sent.get("status") != "uploaded":
            raise RuntimeError("Notion did not confirm the image upload")
        result = {"type": "file_upload", "file_upload": {"id": upload["id"]}}
        self.cache[url] = result
        self.cache[source] = result
        return result

    def new_cover(self, url, subject_url=None):
        image = self.upload(url, subject_url)
        return {"files": [{**image, "name": "Cover"}]}, image

    def repair_payload(self, page):
        subject_url = page.get("properties", {}).get("豆瓣链接", {}).get("url")
        original = page.get("properties", {}).get("封面", {}).get("files", [])
        files = []
        changed = False
        for file in original:
            url = external_douban_url(file)
            if url:
                files.append({**self.upload(url, subject_url), "name": file.get("name", "Cover")})
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
                payload[field] = self.upload(url, subject_url)
        return payload
