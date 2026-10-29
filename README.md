# AI Field Developer / Solutions Engineer Assessment

A runnable Python 3.12 implementation of all four assessment tasks. The code is
organized as separate services under `src/assessment`, with shared types kept
small and explicit. Automated tests cover validation, authorization, streaming
chunk boundaries, concurrency, rate-limit eviction, fallback, and error hygiene.

## Quick start

```bash
uv sync --all-groups
uv run pytest
```

Each service also has an installed command:

```bash
uv run customer-mcp
uv run mock-mcp-server            # port 9001
uv run mcp-security-gateway       # port 9000
uv run streaming-guardrail        # port 9100
uv run model-router               # port 9200
```

## Task 1 — strict stdio MCP server

`customer-mcp` uses the official Python `mcp` SDK and its stdio transport. It
exposes:

- `get_customer_record(customer_id)` where the ID matches `CUST-[A-Z0-9]{5}`.
- `trigger_refund(customer_id, amount, reason)` where amount is finite and
  positive and the trimmed reason is at least 10 characters.

Pydantic models forbid extra fields and coercion. Logging is explicitly bound to
stderr; stdout is owned by the SDK transport and therefore contains JSON-RPC
messages only. An SDK handler wrapper maps invalid tool arguments to the
assessment-requested JSON-RPC `-32602` error before execution. Malformed request
shapes retain the SDK's normal protocol error handling.

## Task 2 — MCP security gateway

The HTTP endpoint is `POST /mcp`. Tokens are configured as a comma-separated
map and are intentionally opaque rather than insecure, unsigned JWTs:

```bash
MCP_TOKENS='admin-secret:admin,viewer-secret:viewer' \
MCP_DOWNSTREAM_URL='http://127.0.0.1:9001/mcp' \
uv run mcp-security-gateway
```

`tools/list` and allowed calls are forwarded byte-for-byte. A viewer calling an
`admin_*` tool receives JSON-RPC error `-32001` and no downstream request is
made. Missing/invalid authentication receives HTTP 401. A production deployment
would replace the small token adapter with verified OIDC/JWT claims.

Example:

```bash
curl -s http://127.0.0.1:9000/mcp \
  -H 'Authorization: Bearer viewer-secret' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
```

## Task 3 — streaming PII guardrail

`POST /v1/generate` forwards a JSON generation request to `LLM_PROVIDER_URL`.
The example provider contract is Server-Sent Events (SSE):

```text
data: {"delta":"some text"}

data: [DONE]
```

Email addresses, US SSNs, and 13–19 digit credit-card-like strings are replaced
with `[REDACTED]`. The redactor retains only an incomplete final token (bounded
to 256 characters), so patterns split across any provider event are detected
without buffering the full response. Completed tokens are emitted immediately;
this preserves streaming behavior while avoiding partial PII leakage. Regex
redaction is a baseline guardrail, not a substitute for a DLP engine or semantic
classifier in a high-assurance production deployment.

## Task 4 — rate limiter and fallback router

`POST /v1/completions` requires `X-API-Key`. The SQLite limiter uses a precise
60-second sliding window and defaults to 50,000 reserved tokens per tenant.
Every admission is a short `BEGIN IMMEDIATE` transaction, making the read/check/
insert operation atomic across concurrent coroutines and gateway processes.
Expired rows are evicted on access and the tenant/time index keeps queries
targeted.

Reserved tokens are `input_tokens + max_tokens`. A caller can supply tokenizer
output as `input_tokens`; otherwise the provider-neutral estimate is one token
per four prompt characters. Reserving the maximum output prevents post-response
overruns.

The primary provider has a 3,000 ms timeout. HTTP 429 or timeout triggers one
attempt against the secondary provider. Other primary errors fail closed. No raw
upstream body, exception, URL, or stack trace is returned to the client.

Configuration:

| Variable | Default |
| --- | --- |
| `RATE_LIMIT_DB` | `rate_limits.db` |
| `TOKEN_LIMIT_PER_MINUTE` | `50000` |
| `PRIMARY_MODEL_URL` | `http://127.0.0.1:9201/v1/completions` |
| `SECONDARY_MODEL_URL` | `http://127.0.0.1:9202/v1/completions` |

## Design notes

- Application factories accept injected HTTP clients, URLs, clocks, and database
  paths. Tests use real ASGI request handling and mock only external providers.
- HTTP status codes describe gateway transport outcomes; response bodies use
  stable JSON-RPC or gateway error contracts.
- Logs can contain operational context, while client errors remain sanitized.
- SQLite WAL mode allows readers during writes; atomic admission prevents the
  classic concurrent rate-limiter oversubscription race.

## Test map

```bash
uv run pytest -v
```

- Task 1: strict IDs, finite positive amounts, trimmed reason length, extra keys.
- Task 2: transparent forwarding, admin/viewer policy, malformed JSON-RPC,
  authentication, and proof of zero downstream I/O on denial.
- Task 3: every split point across PII strings, all pattern types, bounded carry,
  and an end-to-end SSE proxy test.
- Task 4: exact expiration, ten-way concurrent admission, primary 429, primary
  timeout, fallback success, sanitized upstream failure, and pre-provider rate
  rejection.
