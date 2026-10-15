import pytest

from webserver.models import MyNexusBookAnalysis, MyNexusChatSession
from webserver.services import mynexus_service
from webserver.services.mynexus_service import MyNexusClient, MyNexusError
from webserver.handlers.mynexus import routes


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "response reason"
        self.text = "response body"
        self.body = body or {"ok": True}

    def json(self):
        return self.body


def test_client_builds_mynexus_api_url_and_external_user_header(monkeypatch):
    client = MyNexusClient("http://localhost:3000/", "api-token")
    calls = {}

    assert client.url("/chat/sessions") == "http://localhost:3000/api/v1/chat/sessions"
    assert client.headers(17) == {
        "Authorization": "Bearer api-token",
        "X-MyBooks-User-ID": "17",
    }

    def fake_request(method, url, **kwargs):
        calls.update(method=method, url=url, kwargs=kwargs)
        return FakeResponse(body={"analysis_status": "completed"})

    monkeypatch.setattr(mynexus_service.requests, "request", fake_request)
    assert client.analysis_status(17) == {"analysis_status": "completed"}
    assert calls["url"] == "http://localhost:3000/api/v1/books/by-mybooks-id/17"
    assert calls["kwargs"]["headers"]["Authorization"] == "Bearer api-token"


def test_client_rejects_invalid_configuration():
    with pytest.raises(MyNexusError, match="URL"):
        MyNexusClient("file:///tmp/mynexus", "api-token")
    with pytest.raises(MyNexusError, match="token"):
        MyNexusClient("http://localhost:3000", "")


def test_analysis_and_session_mapping_use_expected_keys():
    assert list(MyNexusBookAnalysis.__table__.primary_key.columns.keys()) == ["book_id"]
    assert list(MyNexusChatSession.__table__.primary_key.columns.keys()) == ["reader_id", "book_id"]
    assert {route[0] for route in routes()} == {
        r"/api/admin/mynexus/test",
        r"/api/book/([0-9]+)/mynexus/analysis",
        r"/api/book/([0-9]+)/mynexus/availability",
        r"/api/book/([0-9]+)/mynexus/session",
        r"/api/book/([0-9]+)/mynexus/chat",
    }


def test_client_reports_remote_auth_failure(monkeypatch):
    client = MyNexusClient("http://localhost:3000", "bad-token")
    monkeypatch.setattr(mynexus_service.requests, "request", lambda *args, **kwargs: FakeResponse(401))

    with pytest.raises(MyNexusError) as exc_info:
        client.test_connection()

    assert exc_info.value.status_code == 401
    assert exc_info.value.message == "response body"
