import importlib
import json
from pathlib import Path
import re
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


@pytest.fixture
def stack(tmp_path, monkeypatch):
    webhook_token = "test-webhook-token-" * 3
    logs_token = "test-logs-token-" * 3
    monkeypatch.setenv("WEBHOOK_TOKEN", webhook_token)
    monkeypatch.setenv("LOGS_TOKEN", logs_token)
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "scans.sqlite3"))
    monkeypatch.setenv("QWEN_URL", "http://qwen.test:18081")
    monkeypatch.setenv("PRESIDIO_URL", "http://pii.test:18082")
    for name in ["webhook", "audit", "observation"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("webhook")
    state = {"label": "Safe", "fail": None, "calls": []}
    real_client = httpx.AsyncClient

    def downstream(request):
        body = json.loads(request.content) if request.content else {}
        state["calls"].append((request.url.path, body))
        if request.url.path == state["fail"]:
            return httpx.Response(503, json={"detail": "test dependency failure"})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/moderate":
            return httpx.Response(
                200,
                json={
                    "label": state["label"],
                    "categories": "None" if state["label"] == "Safe" else "Jailbreak",
                    "seconds": 0.01,
                },
            )
        if request.url.path == "/analyze":
            hits = []
            for kind, pattern in [
                ("CN_PHONE_NUMBER", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
                ("EMAIL_ADDRESS", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
            ]:
                for match in re.finditer(pattern, body["text"]):
                    hits.append(
                        {
                            "entity_type": kind,
                            "start": match.start(),
                            "end": match.end(),
                            "score": 0.85,
                        }
                    )
            return httpx.Response(200, json=hits)
        raise AssertionError("Unexpected downstream URL: " + str(request.url))

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(downstream), **kwargs
        ),
    )
    with TestClient(module.app) as client:
        yield client, state, {"Authorization": "Bearer " + webhook_token}, {
            "Authorization": "Bearer " + logs_token
        }, module


def request_body(text="Hello", trace="test-trace"):
    return {
        "eventType": "beforeRequestHook",
        "provider": "example-provider",
        "requestType": "chatComplete",
        "metadata": {"trace_id": trace, "feature": "test"},
        "request": {
            "json": {
                "model": "example-model",
                "stream": True,
                "messages": [{"role": "user", "content": text}],
            },
            "text": text,
            "isTransformed": False,
        },
        "response": {"json": {}, "text": "", "statusCode": None},
    }
