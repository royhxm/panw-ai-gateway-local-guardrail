#!/usr/bin/env python3
"""Check release versions, source syntax, example JSON and accidental credential files."""
import ast
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "Invalid VERSION"
    tree = ast.parse((ROOT / "app/webhook.py").read_text(encoding="utf-8"))
    assigned = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert assigned.get("VERSION") == version, "Webhook VERSION differs"
    for name in ["compose.yaml", ".env.example"]:
        assert "local-guardrail:" + version in (ROOT / name).read_text(
            encoding="utf-8"
        ), (name + " image version differs")
    assert "## [" + version + "]" in (ROOT / "CHANGELOG.md").read_text(
        encoding="utf-8"
    ), "Missing changelog entry"
    assert (
        (ROOT / "README.md")
        .read_text(encoding="utf-8")
        .startswith("# PANW AI Gateway Local Guardrail")
    ), "Project title must identify PANW AI Gateway"
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    paths = (
        [ROOT / name for name in result.stdout.decode().split("\0") if name]
        if result.returncode == 0
        else []
    )
    if not paths:
        paths = [
            p
            for p in ROOT.rglob("*")
            if p.is_file()
            and not set(p.relative_to(ROOT).parts)
            & {
                ".git",
                ".venv",
                "__pycache__",
                ".pytest_cache",
                "logs-data",
                "model-cache",
                ".artifacts",
                "backups",
            }
            and p.name != ".env"
        ]
    for path in paths:
        relative = path.relative_to(ROOT)
        assert not set(relative.parts) & {
            "logs-data",
            "model-cache",
            "backups",
            "__pycache__",
        }, "Runtime data tracked: " + str(relative)
        assert path.name == ".env.example" or not path.name.startswith(
            ".env"
        ), "Credential configuration tracked: " + str(relative)
        assert path.suffix not in [
            ".pem",
            ".key",
            ".sqlite3",
            ".db",
            ".safetensors",
            ".pyc",
        ], "Private/binary runtime file tracked: " + str(relative)
        data = path.read_bytes()
        assert (b"-----BEGIN " + b"PRIVATE KEY-----") not in data, "Private key found"
        for pattern in [
            rb"gh[pousr]_[A-Za-z0-9]{30,}",
            rb"github_pat_[A-Za-z0-9_]{30,}",
        ]:
            assert not re.search(pattern, data), "Possible GitHub token found: " + str(
                relative
            )
        if path.suffix == ".py":
            ast.parse(data.decode("utf-8"), filename=str(relative))
        if path.suffix == ".json":
            json.loads(data)
    print(
        f"Release {version}: versions, source syntax, examples and {len(paths)} source files checked."
    )


if __name__ == "__main__":
    main()
