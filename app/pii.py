import re, datetime
import spacy
from fastapi import FastAPI, HTTPException
from presidio_analyzer import (
    AnalyzerEngine,
    RecognizerRegistry,
    PatternRecognizer,
    Pattern,
)
from presidio_analyzer.nlp_engine import SpacyNlpEngine


class BlankEngine(SpacyNlpEngine):
    def load(self):
        self.nlp = {"zh": spacy.blank("zh"), "en": spacy.blank("en")}


class ChineseID(PatternRecognizer):
    def validate_result(self, text):
        try:
            datetime.datetime.strptime(text[6:14], "%Y%m%d")
            weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
            return (
                "10X98765432"[sum(int(a) * b for a, b in zip(text[:17], weights)) % 11]
                == text[-1].upper()
            )
        except ValueError:
            return False


registry = RecognizerRegistry(supported_languages=["zh", "en"])
for language in ["zh", "en"]:
    for entity, pattern in [
        ("CN_PHONE_NUMBER", r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)"),
        (
            "EMAIL_ADDRESS",
            r"(?<![A-Za-z0-9_.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9_.-])",
        ),
    ]:
        registry.add_recognizer(
            PatternRecognizer(
                supported_entity=entity,
                supported_language=language,
                patterns=[Pattern(entity, pattern, 0.85)],
            )
        )
    registry.add_recognizer(
        ChineseID(
            supported_entity="CN_ID_CARD",
            supported_language=language,
            patterns=[Pattern("cn_id", r"(?<!\d)[1-9]\d{16}[0-9Xx](?!\d)", 0.5)],
        )
    )
engine = AnalyzerEngine(
    registry=registry, nlp_engine=BlankEngine(), supported_languages=["zh", "en"]
)
app = FastAPI()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": "Microsoft Presidio",
        "entities": ["CN_PHONE_NUMBER", "CN_ID_CARD", "EMAIL_ADDRESS"],
    }


@app.post("/analyze")
def analyze(body: dict):
    text = body.get("text", "")
    if not isinstance(text, str) or len(text) > 20000:
        raise HTTPException(422, "invalid text")
    results = engine.analyze(
        text=text, language=body.get("language", "zh"), score_threshold=0.5
    )
    return [
        {"entity_type": r.entity_type, "start": r.start, "end": r.end, "score": r.score}
        for r in results
    ]
