import os, secrets, json, re, time
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import audit
import observation

QWEN_URL = os.environ.get("QWEN_URL", "http://127.0.0.1:18081").rstrip("/")
PRESIDIO_URL = os.environ.get("PRESIDIO_URL", "http://127.0.0.1:18082").rstrip("/")
VERSION = "0.1.0"
app = FastAPI(
    title="PANW AI Gateway Local Guardrail",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
audit.install(app)
app.mount(
    "/logs/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="logs-static",
)
TOKEN = os.environ["WEBHOOK_TOKEN"]
if len(TOKEN) < 32 or TOKEN.startswith("REPLACE_"):
    raise RuntimeError("weak webhook token")


async def auth(request: Request):
    candidate = request.headers.get("authorization", "")
    if not secrets.compare_digest(candidate.encode(), ("Bearer " + TOKEN).encode()):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as client:
        try:
            for url in [QWEN_URL, PRESIDIO_URL]:
                r = await client.get(url + "/health")
                r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, "dependency unavailable")
    return {"status": "ok", "version": VERSION}


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_content(v) for v in value)
    if isinstance(value, dict):
        if value.get("type") in ["image_url", "input_image", "audio", "input_audio"]:
            raise HTTPException(422, "only text is supported")
        if "text" in value:
            return text_content(value["text"])
        if "content" in value:
            return text_content(value["content"])
    raise HTTPException(422, "unsupported content")


def extract(part):
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        raise HTTPException(422, "invalid payload")
    obj = part.get("json")
    if isinstance(obj, dict):
        return extract(obj)
    if isinstance(part.get("messages"), list):
        if any(not isinstance(message, dict) for message in part["messages"]):
            raise HTTPException(422, "messages must contain objects")
        return "\n".join(text_content(m.get("content", "")) for m in part["messages"])
    if isinstance(part.get("choices"), list):
        if any(not isinstance(choice, dict) for choice in part["choices"]):
            raise HTTPException(422, "choices must contain objects")
        return "\n".join(
            text_content(c.get("message", c.get("text", ""))) for c in part["choices"]
        )
    for key in ["text", "prompt", "input", "content"]:
        if key in part and part[key] is not None:
            return text_content(part[key])
    raise HTTPException(422, "no supported text found")


def safe_id(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,160}", value)
        else None
    )


def masked_text(text, entities):
    for entity in sorted(entities, key=lambda e: e["start"], reverse=True):
        text = (
            text[: entity["start"]]
            + "<"
            + entity["entity_type"]
            + ">"
            + text[entity["end"] :]
        )
    return text


@app.post("/webhook", dependencies=[Depends(auth)])
@app.post("/webhook/portkey", dependencies=[Depends(auth)])
@app.post("/webhook/panw", dependencies=[Depends(auth)])
async def webhook(request: Request):
    raw = await request.body()
    if len(raw) > 131072:
        raise HTTPException(413, "payload too large")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(422, "JSON object required")
    event = body.get("eventType", "beforeRequestHook")
    if event not in ["beforeRequestHook", "afterRequestHook"]:
        raise HTTPException(422, "unsupported eventType")
    after = event == "afterRequestHook"
    source = body.get("request", body)
    obj = source.get("json", source) if isinstance(source, dict) else {}
    model = obj.get("model") if isinstance(obj, dict) else None
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    trace = (
        request.headers.get("x-portkey-trace-id")
        or body.get("traceId")
        or metadata.get("trace_id")
    )
    request.state.audit.update(
        event_type=event,
        model=(
            model
            if isinstance(model, str)
            and re.fullmatch(r"[A-Za-z0-9@][A-Za-z0-9_./:-]{0,119}", model)
            else None
        ),
        trace_id=(
            trace
            if isinstance(trace, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", trace)
            else None
        ),
    )
    payload = {
        "version": 3,
        "check": "default.webhook",
        "guardrail_id": safe_id(
            body.get("guardrailId") or metadata.get("guardrail_id")
        ),
        "config_id": safe_id(
            request.headers.get("x-portkey-config-id") or metadata.get("config_id")
        ),
        "workspace_id": safe_id(
            request.headers.get("x-portkey-workspace-id")
            or metadata.get("workspace_id")
        ),
        "guard_model": "Qwen/Qwen3Guard-Gen-0.6B",
        "content": {},
        "timing": {},
        "usage": {},
        "policy": "PII / Unsafe / Controversial => deny; Safe => allow",
        "gateway_observed": False,
    }
    request.state.audit["payload"] = payload
    text = extract(body.get("response") if after else body.get("request", body))
    if not text.strip():
        raise HTTPException(422, "empty content")
    if len(text) > 12000:
        raise HTTPException(413, "text too long")
    messages = [{"role": "user", "content": text}]
    if after:
        prompt = (
            extract(body["request"])
            if body.get("request")
            else "Please respond to the user."
        )
        if len(prompt) > 12000:
            raise HTTPException(413, "prompt too long")
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": text},
        ]
        response = body.get("response", {})
        response_obj = (
            response.get("json", response) if isinstance(response, dict) else {}
        )
        usage = response_obj.get("usage", {}) if isinstance(response_obj, dict) else {}
        if isinstance(usage, dict):
            payload["usage"] = {
                key: value
                for key, value in usage.items()
                if key in ["prompt_tokens", "completion_tokens", "total_tokens"]
                and type(value) is int
                and 0 <= value <= 1000000000
            }
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            started = time.monotonic()
            try:
                p = await client.post(
                    PRESIDIO_URL + "/analyze", json={"text": text, "language": "zh"}
                )
                p.raise_for_status()
            finally:
                payload["timing"]["presidio_ms"] = round(
                    (time.monotonic() - started) * 1000, 2
                )
            entities = p.json()
            masked = masked_text(text, entities)
            request.state.audit.update(summary=masked[:1600], pii=entities)
            payload["content"]["response" if after else "prompt"] = masked
            if after and body.get("request"):
                # Context logging is separately inspected before storing; never persist raw context.
                started = time.monotonic()
                try:
                    context = await client.post(
                        PRESIDIO_URL + "/analyze",
                        json={"text": prompt, "language": "zh"},
                    )
                    context.raise_for_status()
                    payload["content"]["prompt"] = masked_text(prompt, context.json())
                finally:
                    payload["timing"]["context_masking_ms"] = round(
                        (time.monotonic() - started) * 1000, 2
                    )
            # PII blocks immediately, avoiding unnecessary model latency.
            safety = {"label": "Skipped", "categories": "PII"}
            if not entities:
                started = time.monotonic()
                try:
                    m = await client.post(
                        QWEN_URL + "/moderate", json={"messages": messages}
                    )
                    m.raise_for_status()
                    safety = m.json()
                    payload["timing"]["qwen_inference_ms"] = round(
                        safety.get("seconds", 0) * 1000, 2
                    )
                finally:
                    payload["timing"]["qwen_request_ms"] = round(
                        (time.monotonic() - started) * 1000, 2
                    )
        except (httpx.HTTPError, ValueError):
            request.state.audit.update(detail="Guardrail unavailable; fail closed")
            raise HTTPException(503, "guardrail unavailable; fail closed")
    allowed = not entities and safety["label"] == "Safe"
    payload["verdict"] = allowed
    payload["safety"] = safety
    payload["forward_decision"] = (
        ("allow_return" if allowed else "deny_return")
        if after
        else ("allow_forward" if allowed else "deny_forward")
    )
    payload["guard_input"] = {
        "source": "local_model_request",
        "executed": not bool(entities),
        "messages": (
            [
                {
                    "role": "user",
                    "content": payload["content"].get("prompt", "[未保存上下文]"),
                },
                {
                    "role": "assistant",
                    "content": payload["content"].get("response", ""),
                },
            ]
            if after
            else [{"role": "user", "content": payload["content"].get("prompt", "")}]
        ),
        "note": "实际模型请求的日志副本，检出的 PII 已遮盖；PII 命中时模型不执行。",
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as log_client:
            payload["observation"] = await observation.snapshot(body, log_client)
        latest = payload["observation"].get("latest_user")
        if not after and latest and latest.get("content"):
            request.state.audit["summary"] = latest["content"][:1600]
        payload["pii_sources"] = []
        if not after:
            offset = 0
            for turn in observation.messages(body.get("request", body)):
                for hit in entities:
                    if offset <= hit["start"] and hit["end"] <= offset + len(
                        turn["content"]
                    ):
                        payload["pii_sources"].append(
                            {
                                "entity_type": hit["entity_type"],
                                "message_index": turn["index"],
                                "role": turn["role"],
                                "is_latest_user": bool(
                                    latest and turn["index"] == latest["index"]
                                ),
                                "source": "request.json.messages",
                                "local_start": hit["start"] - offset,
                                "local_end": hit["end"] - offset,
                            }
                        )
                offset += len(turn["content"]) + 1
    except Exception:
        # Log enrichment never changes the guardrail decision, and never falls back to raw data.
        payload["observation"] = {
            "source": "gateway_webhook",
            "capture_error": "结构化日志采集失败；未保存原始数据",
        }
    finally:
        payload["timing"]["snapshot_masking_ms"] = round(
            (time.monotonic() - started) * 1000, 2
        )
    request.state.audit.update(
        outcome="allowed" if allowed else "blocked",
        safety_label=safety["label"],
        categories=safety.get("categories"),
    )
    return {
        "verdict": allowed,
        "data": {
            "action": "allow" if allowed else "deny",
            "pii": entities,
            "safety": safety,
            "eventType": event,
        },
    }
