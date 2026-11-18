#!/usr/bin/env python3
"""Small, non-exhaustive real-service evaluation; reports errors and mismatches separately."""
import argparse, json, os, time, urllib.request, urllib.error, uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "examples/safety-cases.json",
    )
    args = parser.parse_args()
    token = os.environ.get("WEBHOOK_TOKEN")
    if not token:
        raise SystemExit(
            "Set WEBHOOK_TOKEN in the environment; do not put it in command arguments."
        )
    results = []
    for case in json.loads(args.cases.read_text(encoding="utf-8-sig")):
        packet = {
            "eventType": "beforeRequestHook",
            "request": {
                "json": {"messages": [{"role": "user", "content": case["text"]}]}
            },
            "metadata": {
                "feature": "safety_evaluation",
                "trace_id": "eval-" + str(uuid.uuid4()),
            },
        }
        req = urllib.request.Request(
            args.base_url.rstrip("/") + "/webhook",
            data=json.dumps(packet).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                value = json.load(r)
            actual = value.get("verdict")
            results.append(
                {
                    "id": case["id"],
                    "expected_allow": case["expected_allow"],
                    "actual_allow": actual,
                    "matched": actual == case["expected_allow"],
                    "label": value.get("data", {}).get("safety", {}).get("label"),
                    "latency_ms": round((time.monotonic() - start) * 1000),
                }
            )
        except (urllib.error.URLError, ValueError) as exc:
            results.append(
                {"id": case["id"], "error": type(exc).__name__, "matched": False}
            )
    print(
        json.dumps(
            {
                "cases": results,
                "matched": sum(r["matched"] for r in results),
                "total": len(results),
                "note": "Small diagnostic sample, not a security guarantee. Mismatches include false positives and misses.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
