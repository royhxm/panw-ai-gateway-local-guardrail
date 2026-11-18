import json
import pytest

from conftest import request_body


@pytest.mark.parametrize("field", ["messages", "choices"])
def test_malformed_message_items_are_rejected(stack, field):
    client, _, web, _, _ = stack
    body = {"request": {"json": {field: [None]}}}
    assert client.post("/webhook", json=body, headers=web).status_code == 422


def test_separate_authentication_and_cookie_login(stack):
    client, _, web, logs, _ = stack
    assert client.post("/webhook", json=request_body()).status_code == 401
    assert client.get("/api/logs", headers=web).status_code == 401
    token = logs["Authorization"].removeprefix("Bearer ")
    assert client.post("/api/logs/login", json={"token": token}).status_code == 200
    assert client.cookies.get("guardrail_logs")
    assert client.get("/api/logs").status_code == 200
    assert client.post("/api/logs/logout").status_code == 200
    assert client.get("/api/logs").status_code == 401
    assert client.post("/api/logs/login", json={"token": "无效密码"}).status_code == 401


def test_allowed_content_preserves_roles_and_duplicates(stack):
    client, _, web, logs, _ = stack
    body = request_body("Hello")
    body["request"]["json"]["messages"].append({"role": "user", "content": "Hello"})
    response = client.post("/webhook/portkey", json=body, headers=web)
    assert response.status_code == 200 and response.json()["verdict"] is True
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    assert (
        item["summary"] == "Hello"
        and item["message_count"] == 2
        and item["duplicate_count"] == 1
    )
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()["scan"][
        "payload"
    ]
    assert detail["guard_input"]["messages"] == [
        {"role": "user", "content": "Hello\nHello"}
    ]
    assert [m["role"] for m in detail["observation"]["messages"]] == ["user", "user"]
    for flag in [
        "client_original_confirmed",
        "llm_received_confirmed",
        "client_received_confirmed",
    ]:
        assert detail["observation"][flag] is False


def test_historical_assistant_pii_is_masked_and_attributed(stack):
    client, state, web, logs, _ = stack
    body = request_body("Continue, please")
    body["request"]["json"]["messages"] = [
        {"role": "assistant", "content": "Phone 13800138000"},
        {"role": "user", "content": "Continue, please"},
    ]
    assert (
        client.post("/webhook/panw", json=body, headers=web).json()["verdict"] is False
    )
    assert not any(path == "/moderate" for path, _ in state["calls"])
    listing = client.get("/api/logs", headers=logs).json()
    item = listing["items"][0]
    assert item["summary"] == "Continue, please"
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()
    assert "13800138000" not in json.dumps(detail)
    hit = detail["scan"]["payload"]["pii_sources"][0]
    assert hit["role"] == "assistant" and hit["is_latest_user"] is False


def test_capture_filters_credentials_and_metadata_pii(stack):
    client, _, web, logs, _ = stack
    body = request_body()
    body["metadata"].update(
        password="do-not-store-fixture-secret", _user="test@example.com"
    )
    body["request"]["headers"] = {"Authorization": "Bearer do-not-store-fixture-key"}
    assert client.post("/webhook", json=body, headers=web).json()["verdict"] is True
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()
    raw = json.dumps(detail)
    assert "do-not-store-fixture" not in raw and "test@example.com" not in raw
    assert "<EMAIL_ADDRESS>" in raw


def test_after_hook_and_trace_correlation(stack):
    client, _, web, logs, _ = stack
    before = request_body()
    assert client.post("/webhook", json=before, headers=web).json()["verdict"]
    after = {
        **before,
        "eventType": "afterRequestHook",
        "response": {
            "json": {
                "model": "example-response-model",
                "choices": [
                    {"message": {"role": "assistant", "content": "test@example.com"}}
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 4,
                    "total_tokens": 12,
                },
            },
            "statusCode": 200,
        },
    }
    assert client.post("/webhook", json=after, headers=web).json()["verdict"] is False
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()
    assert len(detail["related"]) == 2
    assert detail["scan"]["payload"]["usage"]["total_tokens"] == 12
    assert (
        detail["scan"]["payload"]["observation"]["response_model"]
        == "example-response-model"
    )
    assert "test@example.com" not in json.dumps(detail)


def test_dependency_failure_is_logged_and_closed(stack):
    client, state, web, logs, _ = stack
    state["fail"] = "/analyze"
    assert client.post("/webhook", json=request_body(), headers=web).status_code == 503
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    assert item["outcome"] == "error" and item["summary"] == "[未保存原文]"


def test_controversial_blocks(stack):
    client, state, web, _, _ = stack
    state["label"] = "Controversial"
    assert (
        client.post("/webhook", json=request_body(), headers=web).json()["verdict"]
        is False
    )


def test_empty_oversized_and_unsupported_inputs(stack):
    client, _, web, _, _ = stack
    assert client.post("/webhook", json={}, headers=web).status_code == 422
    assert (
        client.post("/webhook", json=request_body("a" * 12001), headers=web).status_code
        == 413
    )
    body = request_body()
    body["request"]["json"]["messages"][0]["content"] = [
        {"type": "image_url", "image_url": {"url": "https://example.com/test.png"}}
    ]
    assert client.post("/webhook", json=body, headers=web).status_code == 422


def test_log_filters_and_security_headers(stack):
    client, _, web, logs, _ = stack
    client.post("/webhook", json=request_body("13800138000"), headers=web)
    assert client.get("/api/logs?outcome=blocked", headers=logs).json()["total"] == 1
    assert client.get("/api/logs?q=CN_PHONE_NUMBER", headers=logs).json()["total"] == 1
    assert client.get("/api/logs?q=%25", headers=logs).json()["total"] == 0
    assert client.get("/api/logs?limit=999", headers=logs).status_code == 422
    assert client.get("/api/logs/999999", headers=logs).status_code == 404
    response = client.get("/logs")
    assert (
        response.status_code == 200 and response.headers["cache-control"] == "no-store"
    )
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
