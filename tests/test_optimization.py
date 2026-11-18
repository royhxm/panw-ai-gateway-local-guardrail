import json
from conftest import request_body


def test_dual_trace_ids_and_ambiguous_pairing(stack):
    client, _, web, logs, _ = stack
    body = request_body()
    body["metadata"]["trace_id"] = "app-trace-fixture"
    headers = {**web, "x-portkey-trace-id": "gateway-trace-fixture"}
    for _ in range(2):
        assert client.post("/webhook", headers=headers, json=body).status_code == 200
    after = {
        **body,
        "eventType": "afterRequestHook",
        "response": {"json": {}, "text": "Safe answer"},
    }
    assert client.post("/webhook", headers=headers, json=after).status_code == 200
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()
    assert (
        detail["scan"]["payload"]["identity"]["application_trace_id"]
        == "app-trace-fixture"
    )
    assert detail["scan"]["trace_id"] == "gateway-trace-fixture"
    assert (
        detail["correlation"]["ambiguous"]
        and detail["correlation"]["paired_scan_id"] is None
    )


def test_empty_output_error_is_captured_and_masked(stack):
    client, _, web, logs, _ = stack
    body = request_body("Email test@example.com")
    body.update(eventType="afterRequestHook", response={"json": {}, "text": ""})
    assert client.post("/webhook", headers=web, json=body).status_code == 422
    item = client.get("/api/logs", headers=logs).json()["items"][0]
    detail = client.get("/api/logs/" + str(item["id"]), headers=logs).json()
    assert detail["scan"]["detail"]
    assert detail["scan"]["payload"]["gateway_observed"] is True
    assert "test@example.com" not in json.dumps(detail)
    assert detail["scan"]["payload"]["observation"]["snapshot"]


def test_metrics_auth(stack):
    client, _, _, logs, _ = stack
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers=logs).json()["window_hours"] == 24


def test_application_trace_is_searchable(stack):
    client, _, web, logs, _ = stack
    body = request_body()
    body["metadata"]["trace_id"] = "unique-application-search"
    assert (
        client.post(
            "/webhook",
            headers={**web, "x-portkey-trace-id": "different-gateway-id"},
            json=body,
        ).status_code
        == 200
    )
    assert (
        client.get("/api/logs?q=unique-application-search", headers=logs).json()[
            "total"
        ]
        == 1
    )


def test_upstream_error_is_not_classified_as_safe(stack):
    client, state, web, logs, _ = stack
    body = request_body()
    body.update(
        eventType="afterRequestHook",
        response={"statusCode": 500, "json": {}, "text": "provider error"},
    )
    assert client.post("/webhook", headers=web, json=body).status_code == 422
    assert not any(path == "/moderate" for path, _ in state["calls"])
    row = client.get("/api/logs", headers=logs).json()["items"][0]
    assert row["detail"] == "upstream response was not successful"


def test_retried_input_does_not_guess_output_pair(stack):
    client, _, web, logs, _ = stack
    body = request_body()
    for _ in range(2):
        client.post("/webhook", headers=web, json=body)
    client.post(
        "/webhook",
        headers=web,
        json={
            **body,
            "eventType": "afterRequestHook",
            "response": {"text": "Safe answer"},
        },
    )
    rows = client.get("/api/logs", headers=logs).json()["items"]
    before = next(row for row in rows if row["event_type"] == "beforeRequestHook")
    detail = client.get("/api/logs/" + str(before["id"]), headers=logs).json()
    assert (
        detail["correlation"]["ambiguous"]
        and detail["correlation"]["paired_scan_id"] is None
    )
