import copy
import pytest
from conftest import request_body


def empty_response(content_marker="missing"):
    message = {"role": "assistant"}
    if content_marker != "missing":
        message["content"] = content_marker
    return {
        "statusCode": 200,
        "text": "",
        "json": {
            "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "length", "message": message}],
            "usage": {
                "prompt_tokens": 199,
                "completion_tokens": 1,
                "total_tokens": 200,
            },
        },
    }


@pytest.mark.parametrize("content", ["missing", None, "", "  "])
def test_successful_empty_completion_is_skipped_not_safe(stack, content):
    client, state, web, logs, _ = stack
    body = request_body("ping")
    body.update(eventType="afterRequestHook", response=empty_response(content))
    r = client.post("/webhook/panw", headers=web, json=body)
    assert r.status_code == 200 and r.json()["verdict"] is True
    assert r.json()["data"]["scan_status"] == "skipped_no_text"
    assert r.json()["data"]["safety"] == {"label": "Skipped", "categories": "NoText"}
    assert not any(path == "/moderate" for path, _ in state["calls"])
    row = client.get("/api/logs", headers=logs).json()["items"][0]
    d = client.get("/api/logs/" + str(row["id"]), headers=logs).json()["scan"][
        "payload"
    ]
    assert d["guard_input"]["executed"] is False
    assert d["usage"]["completion_tokens"] == 1 and d["observation"]["snapshot"]


@pytest.mark.parametrize(
    "mutation",
    [
        "status_missing",
        "status_error",
        "no_choices",
        "tool",
        "multimodal",
        "refusal",
        "finish_filter",
        "provider_error",
        "no_object",
    ],
)
def test_invalid_or_unsupported_empty_responses_do_not_skip(stack, mutation):
    client, _, web, _, _ = stack
    response = empty_response()
    if mutation == "status_missing":
        response.pop("statusCode")
    if mutation == "status_error":
        response["statusCode"] = 500
    if mutation == "no_choices":
        response["json"]["choices"] = []
    if mutation == "no_object":
        response["json"].pop("object")
    if mutation == "provider_error":
        response["json"]["base_resp"] = {"status_code": 1001}
    if mutation == "tool":
        response["json"]["choices"][0]["message"]["tool_calls"] = [{"id": "test"}]
    if mutation == "multimodal":
        response["json"]["choices"][0]["message"]["content"] = [
            {"type": "image_url", "image_url": {"url": "test"}}
        ]
    if mutation == "refusal":
        response["json"]["choices"][0]["message"]["refusal"] = "Unscanned refusal"
    if mutation == "finish_filter":
        response["json"]["choices"][0]["finish_reason"] = "content_filter"
    body = request_body()
    body.update(eventType="afterRequestHook", response=response)
    assert client.post("/webhook", headers=web, json=body).status_code == 422


def test_nonempty_output_still_scanned_and_blocked(stack):
    client, _, web, _, _ = stack
    response = empty_response("test@example.com")
    body = request_body("ping")
    body.update(eventType="afterRequestHook", response=response)
    r = client.post("/webhook", headers=web, json=body)
    assert r.status_code == 200 and r.json()["verdict"] is False
    assert r.json()["data"]["pii"]
