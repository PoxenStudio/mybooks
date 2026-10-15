import json
import os
from urllib.parse import urlparse

import requests

from webserver.loader import get_settings

CONF = get_settings()


class MyNexusError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class MyNexusClient:
    def __init__(self, base_url=None, token=None):
        base_url = base_url if base_url is not None else CONF.get("MYNEXUS_URL")
        token = token if token is not None else CONF.get("MYNEXUS_TOKEN")
        self.base_url = base_url.strip().rstrip("/") if isinstance(base_url, str) else ""
        self.token = token.strip() if isinstance(token, str) else ""
        parsed = urlparse(self.base_url)
        if not self.base_url or parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise MyNexusError(503, "MyNexus URL is not configured")
        if not self.token:
            raise MyNexusError(503, "MyNexus API token is not configured")

    def url(self, path):
        api_root = self.base_url if self.base_url.endswith("/api/v1") else self.base_url + "/api/v1"
        return api_root + path

    def headers(self, reader_id=None):
        headers = {"Authorization": "Bearer " + self.token}
        if reader_id is not None:
            headers["X-MyBooks-User-ID"] = str(reader_id)
        return headers

    def request_json(self, method, path, reader_id=None, **kwargs):
        try:
            response = requests.request(
                method,
                self.url(path),
                headers=self.headers(reader_id),
                timeout=(10, 60),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MyNexusError(502, "MyNexus request failed: %s" % exc) from exc
        if not response.ok:
            raise MyNexusError(response.status_code, response.text[:2000] or response.reason)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MyNexusError(502, "MyNexus returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MyNexusError(502, "MyNexus returned an invalid JSON object")
        return payload

    def upload_book(self, book_id, file_path):
        filename = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as book_file:
                response = requests.post(
                    self.url("/books/import"),
                    headers=self.headers(),
                    data={"mybooks_id": str(book_id), "source_origin": "MyBooks"},
                    files={"file": (filename, book_file, "application/octet-stream")},
                    timeout=(10, 300),
                )
        except requests.RequestException as exc:
            raise MyNexusError(502, "MyNexus upload failed: %s" % exc) from exc
        if not response.ok:
            raise MyNexusError(response.status_code, response.text[:2000] or response.reason)
        try:
            payload = response.json()
        except ValueError as exc:
            raise MyNexusError(502, "MyNexus returned invalid upload response") from exc
        if not isinstance(payload, dict):
            raise MyNexusError(502, "MyNexus returned an invalid upload response")
        return payload

    def analysis_status(self, book_id):
        return self.request_json("GET", "/books/by-mybooks-id/%s" % book_id)

    def test_connection(self):
        return self.request_json("GET", "/system/health")

    def session_detail(self, session_id, reader_id):
        return self.request_json("GET", "/chat/sessions/%s" % session_id, reader_id=reader_id)

    def chat_url(self):
        return self.url("/chat/completions")

    def chat_headers(self, reader_id):
        headers = self.headers(reader_id)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "text/event-stream"
        return headers


def safe_json(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
