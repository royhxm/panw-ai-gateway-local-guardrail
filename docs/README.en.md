# PANW AI Gateway Local Guardrail — English quick start

CPU-only Qwen3Guard-Gen-0.6B + Microsoft Presidio + an authenticated FastAPI
webhook, with a private scan-log UI. This is an independent community project.

## Requirements and installation

Use an x86_64 Linux host with Docker Engine, Docker Compose, approximately 8 GB
RAM and at least 15 GB free disk. The Compose stack uses Linux host networking;
only the webhook can be bound to a chosen private address. Model and PII services
remain on loopback. No firewall or gateway security policy is changed automatically.

```bash
git clone https://github.com/royhxm/panw-ai-gateway-local-guardrail.git
cd panw-ai-gateway-local-guardrail
git checkout v0.2.1
python3 scripts/setup.py
python3 scripts/download_model.py
sudo chown -R 10001:10001 logs-data model-cache
docker compose build
docker compose up -d --wait --wait-timeout 180
python3 scripts/smoke_test.py
```

`.env` contains two generated, independent secrets: `WEBHOOK_TOKEN` for calls and
`LOGS_TOKEN` for the log UI. Never commit this file. Default webhook binding is
`127.0.0.1:18080`; edit `WEBHOOK_BIND_HOST` to a private address for a remote gateway.

## Integration

Use `/webhook/portkey` or `/webhook/panw`. Send a Portkey-style context with
`eventType: beforeRequestHook` or `afterRequestHook` and `Authorization: Bearer
<WEBHOOK_TOKEN>`. The result contains a boolean `verdict` and a `data` object.

Only `Safe` passes. Detected PII, `Unsafe`, and `Controversial` block. Dependencies
failing produce HTTP 503. Configure the gateway synchronously with denial on
failure and `failOnError:true`. A 200 HTTP status can contain `verdict:false`.

Use a 95000 ms webhook timeout. PANW/SCM policy changes must be saved and deployed.
An SSRF rejection may require an administrator-approved exact-host entry in
`TRUSTED_CUSTOM_HOSTS`; do not disable SSRF controls. See the detailed
[gateway guide](gateway-integration.md).

## Logs and evidence

Open `/logs` and use `LOGS_TOKEN`. The UI is currently primarily in Chinese.
Logs preserve roles, message order, duplicates, engine timing and trace-linked
stages. Detected PII is masked in recorded copies and credential fields are omitted.
Unknown PII may still appear; this is not a general-purpose DLP guarantee.

Gateway webhook snapshots are **not** client-side raw HTTP captures, LLM delivery
receipts or confirmation of what the client ultimately received. The UI explicitly
marks missing evidence. History containing PII can block a new, innocuous turn;
the latest-turn summary does not represent the full scan scope.

## Important limitations

- Generative safety classification can yield false positives and false negatives,
  including indirect prompt injection misses. No universal jailbreak protection.
- Chinese PII recognizers cover contiguous mobile numbers, validated 18-character
  IDs and email addresses, not arbitrary names/addresses or every phone format.
- Streaming **input** checks work before generation. Completed-response checks
  cannot retract already delivered streaming tokens. Use non-streaming or gateway
  buffering when responses must be checked before display.
- Supported text is bounded to 12000 characters and a 4096-token model context;
  images/audio are rejected. One inference runs at a time with four admitted slots.

[Chinese full guide](../README.md) · [API](api.md) · [Operations](operations.md) ·
[Limitations](limitations.md) · [Changelog](../CHANGELOG.md)


## v0.2.1 output diagnostics

See [output control and trace correlation](output-control.md) for details. Aurora continues to call PANW AI Gateway first. This release adds no application proxy; streaming buffering and business payload redaction require gateway-side support and are not implemented by this verdict-only webhook.

