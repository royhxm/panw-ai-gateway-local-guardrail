import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("presidio_analyzer")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
pii = importlib.import_module("pii")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("手机号13800138000", "CN_PHONE_NUMBER"),
        ("电话+86 13800138000", "CN_PHONE_NUMBER"),
        ("身份证11010519491231002X", "CN_ID_CARD"),
        ("邮箱test.person@example.com", "EMAIL_ADDRESS"),
    ],
)
def test_actual_presidio_recognizers(text, expected):
    assert any(hit["entity_type"] == expected for hit in pii.analyze({"text": text}))


def test_invalid_id_checksum_does_not_match():
    assert not any(
        hit["entity_type"] == "CN_ID_CARD"
        for hit in pii.analyze({"text": "身份证110105194912310020"})
    )
