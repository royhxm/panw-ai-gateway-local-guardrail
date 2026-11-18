import importlib.util
from pathlib import Path


def test_setup_generates_independent_tokens_and_preserves_existing_env(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "setup_script", root / "scripts/setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env.example").write_bytes((root / ".env.example").read_bytes())
    module.initialize(tmp_path)
    initial = (tmp_path / ".env").read_text()
    values = dict(
        line.split("=", 1)
        for line in initial.splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert len(values["WEBHOOK_TOKEN"]) >= 32 and len(values["LOGS_TOKEN"]) >= 32
    assert values["WEBHOOK_TOKEN"] != values["LOGS_TOKEN"]
    module.initialize(tmp_path)
    assert (tmp_path / ".env").read_text() == initial
    assert values["WEBHOOK_BIND_HOST"] == "127.0.0.1"
