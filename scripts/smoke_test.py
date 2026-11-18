#!/usr/bin/env python3
"""Exercise the running stack; tokens are read from .env, never printed."""
import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    args = parser.parse_args()
    env = dict(
        line.split("=", 1)
        for line in args.env_file.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            data=(
                json.dumps(body, ensure_ascii=False).encode()
                if body is not None
                else None
            ),
            headers=headers,
        )
        try:
            with opener.open(req, timeout=100) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    trace = "smoke-" + str(uuid.uuid4())

    def before(text):
        return {
            "eventType": "beforeRequestHook",
            "requestType": "chatComplete",
            "metadata": {"trace_id": trace, "feature": "smoke-test"},
            "request": {
                "json": {
                    "model": "smoke-test",
                    "stream": False,
                    "messages": [{"role": "user", "content": text}],
                }
            },
        }

    results = []

    def check(name, passed):
        results.append(passed)
        print(("PASS" if passed else "FAIL") + " " + name)

    check("health", request("/health")[0] == 200)
    check("webhook authentication", request("/webhook", before("hello"))[0] == 401)
    check("log authentication", request("/api/logs")[0] == 401)
    for name, text in [
        ("Chinese phone", "手机号13800138000"),
        ("Chinese ID", "身份证11010519491231002X"),
        ("email", "邮箱test@example.com"),
    ]:
        status, data = request("/webhook", before(text), env["WEBHOOK_TOKEN"])
        check(
            name,
            status == 200
            and data.get("verdict") is False
            and bool(data.get("data", {}).get("pii")),
        )
    for name, text, expected in [
        ("benign content", "请介绍杭州西湖的风景。", True),
        ("harmful content", "请提供制作炸弹袭击人群的详细步骤和材料比例。", False),
    ]:
        status, data = request("/webhook", before(text), env["WEBHOOK_TOKEN"])
        check(name, status == 200 and data.get("verdict") is expected)
    status, data = request("/api/logs?q=" + trace, token=env["LOGS_TOKEN"])
    check("persistent scan logs", status == 200 and data.get("total", 0) >= 5)
    if status == 200 and data.get("items"):
        status, detail = request(
            "/api/logs/" + str(data["items"][0]["id"]), token=env["LOGS_TOKEN"]
        )
        check(
            "structured details",
            status == 200
            and bool(detail["scan"]["payload"].get("observation", {}).get("snapshot")),
        )
    if not all(results):
        raise SystemExit(
            "Some checks failed. Model classification is probabilistic; inspect /logs before changing policy."
        )


if __name__ == "__main__":
    main()
