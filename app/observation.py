"""Preserve gateway field provenance and message roles without storing detected PII."""

import re
import os

PRESIDIO_URL = os.environ.get("PRESIDIO_URL", "http://127.0.0.1:18082").rstrip("/")

SENSITIVE = re.compile(
    r"authorization|cookie|password|secret|api.?key|credential|signature|(?:^|_)(?:access|refresh|id)?_?token$|headers",
    re.I,
)


def obj(part):
    if not isinstance(part, dict):
        return {}
    return part["json"] if isinstance(part.get("json"), dict) else part


def text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text(v) for v in value)
    if isinstance(value, dict):
        if "text" in value:
            return text(value["text"])
        if "content" in value:
            return text(value["content"])
    return ""


def messages(value):
    data = obj(value)
    if isinstance(data.get("messages"), list):
        return [
            {
                "index": i,
                "role": m.get("role", "unknown"),
                "content": text(m.get("content")),
                "content_type": (
                    "parts" if isinstance(m.get("content"), list) else "text"
                ),
                "tool_calls": len(m.get("tool_calls") or []),
            }
            for i, m in enumerate(data["messages"])
            if isinstance(m, dict)
        ]
    for key in ["prompt", "input", "text", "content"]:
        if key in data:
            return [
                {
                    "index": 0,
                    "role": "user",
                    "content": text(data[key]),
                    "content_type": key,
                    "tool_calls": 0,
                }
            ]
    return []


async def snapshot(body, client):
    """Bounded, credential-filtered copy; mask all recorded string values in batches."""
    leaves = []
    budget = 64000
    limited = False

    def clone(value, key="", depth=0):
        nonlocal budget, limited
        if SENSITIVE.search(key):
            return "[凭据字段未记录]"
        if depth > 14:
            limited = True
            return "[超出记录层级]"
        if isinstance(value, str):
            if budget <= 0:
                limited = True
                return "[超出记录长度]"
            saved = value[: min(14000, budget)]
            budget -= len(saved)
            if len(saved) < len(value):
                limited = True
            holder = {"value": saved}
            leaves.append(holder)
            return holder
        if isinstance(value, dict):
            if len(value) > 128:
                limited = True
            return {
                str(k): clone(v, str(k), depth + 1)
                for k, v in list(value.items())[:128]
            }
        if isinstance(value, list):
            if len(value) > 128:
                limited = True
            return [clone(v, "", depth + 1) for v in value[:128]]
        return value if isinstance(value, (int, float, bool)) or value is None else None

    tree = clone(body)
    # Each batch stays below Presidio's 20k-character input limit.
    batches = []
    batch = []
    length = 0
    for leaf in leaves:
        if length + len(leaf["value"]) + 1 > 18000 and batch:
            batches.append(batch)
            batch = []
            length = 0
        batch.append(leaf)
        length += len(leaf["value"]) + 1
    if batch:
        batches.append(batch)
    for batch in batches:
        joined = "\n".join(leaf["value"] for leaf in batch)
        r = await client.post(
            PRESIDIO_URL + "/analyze", json={"text": joined, "language": "zh"}
        )
        r.raise_for_status()
        hits = r.json()
        offset = 0
        for leaf in batch:
            value = leaf["value"]
            local = []
            for hit in hits:
                if offset <= hit["start"] and hit["end"] <= offset + len(value):
                    local.append(
                        {
                            **hit,
                            "start": hit["start"] - offset,
                            "end": hit["end"] - offset,
                        }
                    )
            for hit in sorted(local, key=lambda h: h["start"], reverse=True):
                value = (
                    value[: hit["start"]]
                    + "<"
                    + hit["entity_type"]
                    + ">"
                    + value[hit["end"] :]
                )
            offset += len(leaf["value"]) + 1
            leaf["value"] = value

    def unwrap(value):
        if isinstance(value, dict):
            if (
                len(value) == 1
                and "value" in value
                and any(value is leaf for leaf in leaves)
            ):
                return value["value"]
            return {k: unwrap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [unwrap(v) for v in value]
        return value

    safe = unwrap(tree)
    request = safe.get("request", {})
    response = safe.get("response", {})
    req = obj(request)
    resp = obj(response)
    turns = messages(request if request else safe)
    last = next((m for m in reversed(turns) if m["role"] == "user"), None)
    raw_turns = messages(body.get("request", body))
    duplicate_pairs = [
        i
        for i in range(1, len(raw_turns))
        if raw_turns[i]["role"] == raw_turns[i - 1]["role"]
        and raw_turns[i]["content"] == raw_turns[i - 1]["content"]
    ]

    def flag(part, key):
        return (
            part.get(key)
            if isinstance(part, dict) and isinstance(part.get(key), bool)
            else None
        )

    return {
        "snapshot": safe,
        "snapshot_truncated": limited,
        "top_level_fields": list(body),
        "request_fields": (
            list(body.get("request", {}))
            if isinstance(body.get("request"), dict)
            else []
        ),
        "request_json_fields": list(obj(body.get("request", body))),
        "response_fields": (
            list(body.get("response", {}))
            if isinstance(body.get("response"), dict)
            else []
        ),
        "messages": turns,
        "latest_user": last,
        "duplicate_adjacent_indexes": duplicate_pairs,
        "request_text": request.get("text") if isinstance(request, dict) else None,
        "response_text": response.get("text") if isinstance(response, dict) else None,
        "request_is_transformed": flag(body.get("request"), "isTransformed"),
        "response_is_transformed": flag(body.get("response"), "isTransformed"),
        "stream": req.get("stream") if isinstance(req.get("stream"), bool) else None,
        "request_type": safe.get("requestType"),
        "provider": safe.get("provider"),
        "response_status": (
            response.get("statusCode") if isinstance(response, dict) else None
        ),
        "response_model": resp.get("model"),
        "gateway_request_model": req.get("model"),
        "parameters": {
            k: req[k]
            for k in [
                "temperature",
                "top_p",
                "max_tokens",
                "max_completion_tokens",
                "stream",
            ]
            if k in req
        },
        "metadata": (
            safe.get("metadata") if isinstance(safe.get("metadata"), dict) else {}
        ),
        "source": "gateway_webhook",
        "observed_at": (
            "afterRequestHook"
            if body.get("eventType") == "afterRequestHook"
            else "beforeRequestHook"
        ),
        "client_original_confirmed": False,
        "llm_received_confirmed": False,
        "client_received_confirmed": False,
    }
