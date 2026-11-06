"""Контракт OpenAI-compatible adapter через loopback HTTP, без внешней сети."""
import json
import sys
import threading
import urllib.error
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_planner  # noqa: E402

pytestmark = [pytest.mark.contract, pytest.mark.ai]


class FakeDoc:
    doc_id = "doc-http"
    document_instance_id = "instance-http"
    revision = 4
    parts = [{
        "part_id": "part-1",
        "template": "plate_with_holes",
        "params": {"length": 80, "width": 40, "height": 6, "hole_diameter": 4},
    }]


class ProviderServer:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append({"path": self.path, "headers": dict(self.headers)})
                status, payload = owner.responses.popleft()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(length)
                owner.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "json": json.loads(body),
                })
                status, payload = owner.responses.popleft()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"


def _configure(monkeypatch, server, api_key="marker-secret"):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "openai",
        "base_url": server.base_url,
        "model": "test-model",
        "api_key": api_key,
    })


def _envelope(content):
    return {"choices": [{"message": {"content": content}}]}


def _valid_plan():
    return {
        "schema_version": 1,
        "document_id": FakeDoc.doc_id,
        "document_instance_id": FakeDoc.document_instance_id,
        "base_revision": FakeDoc.revision,
        "units": "mm",
        "assumptions": [],
        "questions": [],
        "operations": [{
            "command_id": "parameter.set",
            "target_id": "part-1",
            "parameters": {"name": "length", "value": 100},
        }],
        "summary": "Изменить длину",
    }


@pytest.mark.parametrize("models,expected", [
    ([], False),
    ([{"id": "other"}], False),
    ([{"id": f"other-{index}"} for index in range(20)] + [{"id": "test-model"}], True),
    ([None, {}, {"id": 123}, {"id": ""}], False),
])
def test_connection_checks_actual_complete_model_list(monkeypatch, models, expected):
    with ProviderServer([(200, {"data": models})]) as server:
        _configure(monkeypatch, server)
        result = ai_planner.test_connection()
        assert result["ok"] is True
        assert result["model_found"] is expected
        if expected:
            assert result["models"][20] == "test-model"
        else:
            assert "отсутствует" in result["message"]
        assert server.requests[0]["path"] == "/v1/models"


@pytest.mark.parametrize("payload", [None, [], {}, {"data": {}}, {"data": "test-model"}])
def test_connection_rejects_malformed_model_list(monkeypatch, payload):
    with ProviderServer([(200, payload)]) as server:
        _configure(monkeypatch, server)
        with pytest.raises(ValueError, match="список /models"):
            ai_planner.test_connection()


def test_transport_routes_to_selected_provider_without_secret_in_body(monkeypatch):
    with ProviderServer([(200, _envelope("ok"))]) as server:
        _configure(monkeypatch, server)
        assert ai_planner.http_chat([{"role": "user", "content": "test"}], False) == "ok"

    request = server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["json"]["model"] == "test-model"
    assert request["json"]["temperature"] == 0
    assert "reasoning_effort" not in request["json"]
    assert request["headers"]["Authorization"] == "Bearer marker-secret"
    assert "marker-secret" not in json.dumps(request["json"])


@pytest.mark.parametrize("payload", [{}, {"choices": []}, _envelope("")])
def test_transport_rejects_invalid_or_empty_envelope(monkeypatch, payload):
    with ProviderServer([(200, payload)]) as server:
        _configure(monkeypatch, server, api_key="")
        with pytest.raises(ValueError):
            ai_planner.http_chat([{"role": "user", "content": "test"}], False)


def test_transport_surfaces_http_failure(monkeypatch):
    with ProviderServer([(503, {"error": {"message": "unavailable"}})]) as server:
        _configure(monkeypatch, server, api_key="")
        with pytest.raises(Exception) as error:
            ai_planner.http_chat([{"role": "user", "content": "test"}], False)
    assert getattr(error.value, "code", None) == 503


def test_schema_repair_runs_once_then_previews_valid_plan(monkeypatch):
    invalid = {**_valid_plan(), "units": "inch"}
    valid = _valid_plan()
    responses = [
        (200, _envelope(json.dumps(invalid))),
        (200, _envelope(json.dumps(valid))),
    ]
    preview_calls = []
    with ProviderServer(responses) as server:
        _configure(monkeypatch, server, api_key="")
        result = ai_planner.ai_plan(
            "сделай длину 100",
            FakeDoc(),
            lambda operations, revision, digest: preview_calls.append(
                (operations, revision, digest)) or {"mode": "preview"},
        )

    assert len(server.requests) == 2
    assert len(preview_calls) == 1
    assert result["plan"]["units"] == "mm"
    assert result["plan_hash"] == preview_calls[0][2]


def test_schema_repair_stops_after_second_invalid_response(monkeypatch):
    invalid = {**_valid_plan(), "schema_version": 999}
    responses = [
        (200, _envelope(json.dumps(invalid))),
        (200, _envelope(json.dumps(invalid))),
    ]
    with ProviderServer(responses) as server:
        _configure(monkeypatch, server, api_key="")
        with pytest.raises(RuntimeError, match="plan_invalid"):
            ai_planner.ai_plan(
                "сделай длину 100",
                FakeDoc(),
                lambda *_args: pytest.fail("preview не должен запускаться"),
            )
    assert len(server.requests) == 2


def test_provider_timeout_never_starts_preview(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "openai",
        "base_url": "http://127.0.0.1:9/v1",
        "model": "test-model",
        "api_key": "",
    })
    preview_calls = []

    def timeout(*_args, **_kwargs):
        raise urllib.error.URLError(TimeoutError("controlled timeout"))

    monkeypatch.setattr(ai_planner.urllib.request, "urlopen", timeout)
    with pytest.raises(urllib.error.URLError, match="controlled timeout"):
        ai_planner.ai_plan(
            "сделай длину 100", FakeDoc(),
            lambda *_args: preview_calls.append(True),
        )
    assert preview_calls == []


def test_truncated_provider_body_never_starts_preview(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "openai",
        "base_url": "http://127.0.0.1:9/v1",
        "model": "test-model",
        "api_key": "",
    })
    preview_calls = []

    class TruncatedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"choices": [{"message": '

    monkeypatch.setattr(
        ai_planner.urllib.request, "urlopen", lambda *_args, **_kwargs: TruncatedResponse())
    with pytest.raises(json.JSONDecodeError):
        ai_planner.ai_plan(
            "сделай длину 100", FakeDoc(),
            lambda *_args: preview_calls.append(True),
        )
    assert preview_calls == []


def test_oversized_provider_body_is_rejected_before_preview(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "openai",
        "base_url": "http://127.0.0.1:9/v1",
        "model": "test-model",
        "api_key": "",
    })
    preview_calls = []

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            return b"x" * limit

    monkeypatch.setattr(
        ai_planner.urllib.request, "urlopen", lambda *_args, **_kwargs: OversizedResponse())
    with pytest.raises(ValueError, match="превышает допустимый размер"):
        ai_planner.ai_plan(
            "сделай длину 100", FakeDoc(),
            lambda *_args: preview_calls.append(True),
        )
    assert preview_calls == []
