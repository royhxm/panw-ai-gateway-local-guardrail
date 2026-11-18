#!/usr/bin/env python3
"""Download a pinned model revision, verifying its safetensors SHA-256."""
import argparse
import hashlib
from pathlib import Path
import time
import urllib.request

MODEL_ID = "Qwen/Qwen3Guard-Gen-0.6B"
REVISION = "fada3b2f655b89601929198343c94cd2f64d93cc"
WEIGHT_SHA256 = "4f3ce47ebd968cddb67de08d8764f8ede7c410a7d1fb9e08145a4c7a2f2e5c0f"
WEIGHT_BYTES = 1503300328
FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
    "model.safetensors",
]


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def download(url, target):
    partial = target.with_name(target.name + ".partial")
    for attempt in range(1, 6):
        start = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(
            url, headers={"Range": f"bytes={start}-"} if start else {}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                append = start > 0 and response.status == 206
                if append and not response.headers.get("Content-Range", "").startswith(
                    f"bytes {start}-"
                ):
                    raise RuntimeError("Server returned an unexpected resume range")
                with partial.open("ab" if append else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            return partial
        except Exception:
            if attempt == 5:
                raise
            print(f"Retrying {target.name} ({attempt}/5); partial file retained.")
            time.sleep(min(attempt * 2, 10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "model-cache",
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    directory = args.cache_dir / "model"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".revision"
    if marker.exists() and marker.read_text().strip() != REVISION:
        raise SystemExit(
            "A different model revision is present; use a separate cache directory."
        )
    for name in FILES:
        target = directory / name
        if target.exists():
            if name == "model.safetensors" and (
                target.stat().st_size != WEIGHT_BYTES or sha256(target) != WEIGHT_SHA256
            ):
                raise SystemExit(
                    "Existing weights failed verification; left untouched. Use a new cache directory."
                )
            if target.stat().st_size == 0:
                raise SystemExit(f"Existing {name} is empty; left untouched.")
            continue
        if args.verify_only:
            raise SystemExit(f"Missing {target}")
        print("Downloading", name)
        partial = download(
            f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}", target
        )
        if name == "model.safetensors" and (
            partial.stat().st_size != WEIGHT_BYTES or sha256(partial) != WEIGHT_SHA256
        ):
            raise SystemExit(
                "Downloaded weights failed SHA-256 verification; partial file retained."
            )
        partial.replace(target)
    if not args.verify_only:
        marker.write_text(REVISION + "\n", encoding="utf-8")
    print("Model files present; weight size and SHA-256 verified. Revision:", REVISION)
    print("For Linux Docker access, ensure model-cache is readable by UID 10001.")


if __name__ == "__main__":
    main()
