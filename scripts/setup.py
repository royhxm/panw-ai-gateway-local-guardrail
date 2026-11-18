#!/usr/bin/env python3
"""Create private local settings. Never overwrite an existing .env or change a firewall."""
import argparse
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def initialize(root=ROOT):
    template = (root / ".env.example").read_text(encoding="utf-8")
    target = root / ".env"
    if target.exists():
        print(".env already exists; credentials preserved.")
    else:
        content = template.replace(
            "REPLACE_WITH_A_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS",
            secrets.token_urlsafe(48),
        )
        content = content.replace(
            "REPLACE_WITH_A_DIFFERENT_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS",
            secrets.token_urlsafe(48),
        )
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
        print("Created .env with two independent random tokens (not printed).")
    for name in ["logs-data", "model-cache"]:
        (root / name).mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        if os.geteuid() == 0:
            for name in ["logs-data", "model-cache"]:
                os.chown(root / name, 10001, 10001)
            print("Data directories assigned to container UID 10001.")
        elif (root / "logs-data").stat().st_uid != 10001:
            print(
                "Before starting Docker, run: sudo chown -R 10001:10001 logs-data model-cache"
            )
    else:
        print(
            "Deployment uses Linux host networking; run this setup on your Linux host."
        )


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    initialize()
