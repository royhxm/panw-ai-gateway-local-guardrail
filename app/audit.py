import asyncio
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

DB = os.environ.get("AUDIT_DB", "./logs-data/scans.sqlite3")
LOGS_TOKEN = os.environ["LOGS_TOKEN"]
if len(LOGS_TOKEN) < 32 or LOGS_TOKEN.startswith("REPLACE_"):
    raise RuntimeError(
        "LOGS_TOKEN must be an independent random value of at least 32 characters"
    )
logger = logging.getLogger("guardrail.audit")


def connect():
    conn = sqlite3.connect(DB, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            outcome TEXT NOT NULL, http_status INTEGER NOT NULL,
            latency_ms INTEGER NOT NULL, event_type TEXT, model TEXT,
            trace_id TEXT, summary TEXT, safety_label TEXT,
            categories TEXT, pii TEXT NOT NULL, detail TEXT)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS scans_time ON scans(timestamp)")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(scans)")}
        if "payload" not in columns:
            conn.execute(
                "ALTER TABLE scans ADD COLUMN payload TEXT NOT NULL DEFAULT '{}'"
            )
        conn.execute("CREATE INDEX IF NOT EXISTS scans_trace ON scans(trace_id)")


def save(row):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    with connect() as conn:
        conn.execute(
            """INSERT INTO scans(timestamp,outcome,http_status,latency_ms,
            event_type,model,trace_id,summary,safety_label,categories,pii,detail,payload)
            VALUES(:timestamp,:outcome,:http_status,:latency_ms,:event_type,:model,
            :trace_id,:summary,:safety_label,:categories,:pii,:detail,:payload)""",
            row,
        )
        conn.execute("DELETE FROM scans WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM scans WHERE id <= (SELECT MAX(id)-10000 FROM scans)")


def read_logs(limit, outcome, query, offset):
    where, args = ["timestamp >= ?"], [
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    ]
    if outcome != "all":
        where.append("outcome = ?")
        args.append(outcome)
    if query:
        where.append(
            "(summary LIKE ? ESCAPE '\\' OR trace_id LIKE ? ESCAPE '\\' OR model LIKE ? ESCAPE '\\' OR categories LIKE ? ESCAPE '\\' OR json_extract(payload,'$.identity.application_trace_id') LIKE ? ESCAPE '\\' OR json_extract(payload,'$.observation.metadata.trace_id') LIKE ? ESCAPE '\\')"
        )
        term = (
            "%"
            + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        args.extend([term] * 6)
    clause = " WHERE " + " AND ".join(where)
    with connect() as conn:
        counts = {
            r["outcome"]: r["n"]
            for r in conn.execute(
                "SELECT outcome,COUNT(*) n FROM scans" + clause + " GROUP BY outcome",
                args,
            )
        }
        pii_requests = conn.execute(
            "SELECT COUNT(*) FROM scans" + clause + " AND pii <> '[]'", args
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT id,timestamp,outcome,http_status,latency_ms,event_type,model,trace_id,summary,safety_label,categories,pii,detail,
            json_array_length(payload,'$.observation.messages') AS message_count,
            json_array_length(payload,'$.observation.duplicate_adjacent_indexes') AS duplicate_count,
            json_extract(payload,'$.observation.stream') AS stream,
            json_extract(payload,'$.observation.request_type') AS request_type,
            COALESCE(json_extract(payload,'$.observation.metadata.feature'),json_extract(payload,'$.observation.snapshot.metadata.feature')) AS feature,
            json_extract(payload,'$.identity.gateway_trace_id') AS gateway_trace_id,
            COALESCE(json_extract(payload,'$.identity.application_trace_id'),json_extract(payload,'$.observation.metadata.trace_id')) AS application_trace_id,
            json_extract(payload,'$.version') AS log_version
            FROM scans"""
            + clause
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["pii"] = json.loads(item["pii"])
        items.append(item)
    return {
        "items": items,
        "total": sum(counts.values()),
        "counts": counts,
        "pii_requests": pii_requests,
        "limit": limit,
        "offset": offset,
        "retention_days": 30,
        "max_records": 10000,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def read_detail(scan_id):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scans WHERE id=? AND timestamp>=?", (scan_id, cutoff)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "scan not found")
        related = []
        if row["trace_id"]:
            related = conn.execute(
                "SELECT * FROM scans WHERE trace_id=? AND timestamp>=? ORDER BY id DESC LIMIT 20",
                (row["trace_id"], cutoff),
            ).fetchall()

    def decode(value):
        item = dict(value)
        item["pii"] = json.loads(item["pii"])
        item["payload"] = json.loads(item["payload"])
        return item

    scan = decode(row)
    records = [decode(value) for value in related]
    opposite = (
        "afterRequestHook"
        if scan["event_type"] == "beforeRequestHook"
        else "beforeRequestHook"
    )
    candidates = [r for r in records if r["event_type"] == opposite]
    ambiguous = any(
        sum(r["event_type"] == stage for r in records) > 1
        for stage in ("beforeRequestHook", "afterRequestHook")
    )
    return {
        "scan": scan,
        "related": records,
        "correlation": {
            "key": "trace_id" if row["trace_id"] else None,
            "candidate_count": len(candidates),
            "ambiguous": ambiguous,
            "paired_scan_id": (
                candidates[0]["id"] if len(candidates) == 1 and not ambiguous else None
            ),
            "note": "仅按相同 Trace 关联，不按会话或时间猜测；多候选时不自动选择。",
        },
    }


def signature(expiry):
    return hmac.new(
        LOGS_TOKEN.encode(), ("logs:" + expiry).encode(), hashlib.sha256
    ).hexdigest()


async def logs_auth(request: Request):
    authorization = request.headers.get("authorization", "")
    if secrets.compare_digest(
        authorization.encode(), ("Bearer " + LOGS_TOKEN).encode()
    ):
        return
    cookie = request.cookies.get("guardrail_logs", "")
    try:
        expiry, sig = cookie.split(".", 1)
        if int(expiry) > time.time() and secrets.compare_digest(sig, signature(expiry)):
            return
    except (ValueError, TypeError):
        pass
    raise HTTPException(401, "logs authentication required")


def install(app):
    initialize()

    @app.middleware("http")
    async def audit_webhooks(request: Request, call_next):
        if request.url.path not in ["/webhook", "/webhook/portkey", "/webhook/panw"]:
            response = await call_next(request)
            if request.url.path.startswith(("/logs", "/api/logs")):
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                )
            return response
        started = time.monotonic()
        request.state.audit = {}
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            data = request.state.audit
            elapsed = round((time.monotonic() - started) * 1000)
            payload = data.get("payload", {})
            payload.setdefault("timing", {})["webhook_total_ms"] = elapsed
            row = {
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "outcome": data.get(
                    "outcome", "rejected" if status in [401, 413, 422] else "error"
                ),
                "http_status": status,
                "latency_ms": elapsed,
                "event_type": data.get("event_type"),
                "model": data.get("model"),
                "trace_id": data.get("trace_id"),
                "summary": data.get("summary", "[未保存原文]"),
                "safety_label": data.get("safety_label"),
                "categories": data.get("categories"),
                "pii": json.dumps(data.get("pii", [])),
                "detail": data.get("detail"),
                "payload": json.dumps(payload, ensure_ascii=False),
            }
            try:
                await asyncio.to_thread(save, row)
            except Exception:
                logger.exception("Audit persistence failed")

    @app.get("/logs")
    async def logs_page():
        return FileResponse(Path(__file__).parent / "static/index.html")

    @app.post("/api/logs/login")
    async def login(request: Request):
        if len(await request.body()) > 1024:
            raise HTTPException(413, "login payload too large")
        try:
            body = await request.json()
            token = body.get("token", "")
        except (ValueError, AttributeError):
            raise HTTPException(401, "invalid token")
        if not isinstance(token, str) or not secrets.compare_digest(
            token.encode(), LOGS_TOKEN.encode()
        ):
            raise HTTPException(401, "invalid token")
        expiry = str(int(time.time() + 8 * 3600))
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            "guardrail_logs",
            expiry + "." + signature(expiry),
            httponly=True,
            samesite="strict",
            max_age=8 * 3600,
            path="/api/logs",
        )
        return response

    @app.post("/api/logs/logout")
    async def logout():
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("guardrail_logs", path="/api/logs")
        return response

    @app.get("/api/logs", dependencies=[Depends(logs_auth)])
    async def logs(
        limit: int = 100, outcome: str = "all", q: str = "", offset: int = 0
    ):
        if (
            limit not in [25, 50, 100, 250, 500]
            or outcome not in ["all", "allowed", "blocked", "error", "rejected"]
            or not 0 <= offset <= 10000
            or len(q) > 200
        ):
            raise HTTPException(422, "invalid filter")
        return await asyncio.to_thread(read_logs, limit, outcome, q.strip(), offset)

    @app.get("/api/metrics", dependencies=[Depends(logs_auth)])
    async def runtime_metrics():
        return await asyncio.to_thread(metrics)

    @app.get("/api/logs/{scan_id}", dependencies=[Depends(logs_auth)])
    async def log_detail(scan_id: int):
        return await asyncio.to_thread(read_detail, scan_id)


def metrics():
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT outcome,http_status,latency_ms,payload FROM scans WHERE timestamp>=?",
            (cutoff,),
        ).fetchall()
    latency = sorted(r["latency_ms"] for r in rows)
    return {
        "window_hours": 24,
        "scans": len(rows),
        "blocked": sum(r["outcome"] == "blocked" for r in rows),
        "errors": sum(r["http_status"] >= 400 for r in rows),
        "latency_p50_ms": latency[(len(latency) - 1) // 2] if latency else None,
        "latency_p95_ms": (
            latency[min(len(latency) - 1, int(len(latency) * 0.95))]
            if latency
            else None
        ),
        "note": "统计 Webhook 阶段；一次调用通常包含输入和输出两次检查。",
    }
