# Contributing

Please use synthetic examples, keep changes focused, and explain observable
before/after behavior. Never commit private deployment data or `.env` files.

## Development checks

Use Python 3.11 on Linux. In a virtual environment:

```bash
pip install -r requirements-test.txt -r requirements.txt
pytest
node --check app/static/app.js
python3 scripts/check_release.py
```

Model weights are unnecessary for unit tests. Real model inference is tested with
`scripts/smoke_test.py` against a running stack. Clearly distinguish mocks, synthetic
integration cases and real gateway observations in test results.

## Release procedure

1. Update VERSION, webhook VERSION, Compose default image, .env.example and documentation.
2. Add dated changes and known limitations to CHANGELOG.md.
3. Run tests and a full isolated Compose smoke test. Preserve private production data.
4. Run release checks; inspect `git diff --cached` and the file list for secrets.
5. Create an annotated `vX.Y.Z` tag and publish a GitHub Release with meaningful notes.

Do not attach `.env`, weights, runtime databases, real request captures or private
screenshots. Public release assets should be reproducible source/configuration only.

