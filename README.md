# Cortxt Resilient Inference

A small, provider-neutral tool for hard request deadlines and policy-gated
fallback when an inference route is unavailable, rate limited, too slow, or
fails to return a usable result.

It is deliberately independent of any inference provider, agent runtime, or
provider SDK.

Status: experimental v0.2. The OpenAI-compatible adapter and hard timeout are
implemented and locally tested. Provider-specific reload APIs, streaming,
circuit breaking, and production traffic validation are not yet included.

## Features

- routes are tried in declared order and only when `policy_eligible` is exactly
  `true`;
- total attempts are bounded and HTTP attempts run in terminable child
  processes with a hard wall-clock deadline;
- permanent and transient failures remain explicit in the evidence envelope;
- non-idempotent work is never replayed after an effect may have occurred;
- an unsafe fallback is skipped rather than silently weakening policy;
- every terminal outcome contains the complete attempt history.

The CLI supports deterministic simulations and real OpenAI-compatible HTTP
routes. API keys are read only from named environment variables. Remote routes
must use HTTPS; HTTP is accepted only for localhost tests.

```text
Your app or agent
        |
        v
Cortxt Resilient Inference
        |-- primary OpenAI-compatible endpoint (for example InferX)
        `-- approved fallback endpoint
```

No special fallback prompt is required. The normal OpenAI-compatible
`messages` are sent to the first eligible route. If that attempt times out, is
rate limited, or the provider is unavailable, the same messages are sent to
the next eligible route within the declared attempt budget when replay is
safe. Non-idempotent work is blocked after an unknown-effect timeout.

## Quickstart

```text
python -m unittest discover -s tests -v
set PYTHONPATH=src
python -m cortxt_resilient_inference.cli examples/timeout-fallback.json
```

For a real route, omit `simulations`, add top-level OpenAI-compatible
`messages`, and give each route:

```json
{
  "base_url": "https://provider.example/v1",
  "model": "exact-model-id",
  "api_key_env": "PROVIDER_API_KEY"
}
```

Copy `examples/live-template.json`, replace the endpoint/model identifiers, and
set the named API-key environment variables before running it. Never put API
keys in the JSON file.

## Integrate it into your application

Version 0.2 can be used as a CLI subprocess or imported by a Python
application. It is not yet a drop-in OpenAI proxy: an existing OpenAI client
cannot switch only its `base_url` to this tool.

### CLI

Install the local package and create a request from the live template:

```text
python -m pip install -e .
copy examples\live-template.json request.json
```

Edit `request.json` so the primary route contains the provider's exact
OpenAI-compatible base URL and model ID. Add a second approved route for
fallback. Keep credentials outside the file:

```powershell
$env:INFERX_API_KEY = "replace-with-real-key"
$env:FALLBACK_API_KEY = "replace-with-real-key"
cortxt-resilient-run request.json
```

On macOS or Linux, set the same variables with `export`:

```sh
export INFERX_API_KEY="replace-with-real-key"
export FALLBACK_API_KEY="replace-with-real-key"
cortxt-resilient-run request.json
```

A successful run prints one JSON envelope containing `status`,
`selected_route_id`, the assistant `response`, and every attempted route. Store
or parse that envelope in the calling application instead of scraping logs.

### Python

The adapter uses spawned child processes to enforce request deadlines, so keep
the entry point behind the normal `__main__` guard:

```python
from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter
from cortxt_resilient_inference.runner import execute


def main():
    request = {
        "task_id": "request-123",
        "data_class": "L0",
        "idempotency": "read_only",
        "max_attempts_total": 2,
        "per_attempt_timeout_ms": 15_000,
        "routes": [
            {
                "route_id": "inferx-primary",
                "base_url": "https://your-inferx-endpoint.example/v1",
                "model": "exact-primary-model-id",
                "api_key_env": "INFERX_API_KEY",
                "policy_eligible": True,
            },
            {
                "route_id": "fallback",
                "base_url": "https://fallback-provider.example/v1",
                "model": "exact-fallback-model-id",
                "api_key_env": "FALLBACK_API_KEY",
                "policy_eligible": True,
            },
        ],
    }
    messages = [{"role": "user", "content": "Summarize this request."}]
    adapter = OpenAICompatibleAdapter(messages)
    adapters = {route["route_id"]: adapter for route in request["routes"]}
    result = execute(request, adapters)
    print(result)


if __name__ == "__main__":
    main()
```

The application remains responsible for deciding which routes satisfy its
privacy, residency, and provider policies. Set `policy_eligible` to literal
`true` only after making that decision.

### Context continuity during fallback

Fallback preserves only the context supplied by the application in the
request. The adapter sends the same `messages` to the next eligible route, so
system instructions, conversation history, retrieved documents, and tool
results continue only when they are included in those messages.

Provider-side session state does not move between routes. This includes hidden
conversation state, prompt caches, partially streamed responses, deployment
memory, and any other state stored only by the first provider. Applications
should therefore own and persist the canonical conversation history and make
each inference request self-contained.

Fallback models may also have different context-window or feature limits.
Version 0.2 does not summarize, truncate, or translate requests automatically.
Configure routes that can accept the request as sent, or apply an explicit
context-compaction policy in the calling application before execution.

## What automatic recovery means

This tool provides request-level recovery: it stops a stalled inference
attempt and tries the next approved endpoint. It does not restart, reload, or
provision the failed provider deployment itself. That requires a separate,
provider-specific management API and lifecycle contract.

The adapter sends `POST <base_url>/chat/completions`, maps 404/429/5xx into
stable failure classes, and terminates the worker process when the declared
deadline expires. Timeout is recorded as an unknown-effect stalled return; the
runner therefore blocks fallback for non-idempotent work.

Expected CLI exit codes:

- `0`: succeeded;
- `2`: failed or blocked by routing/policy;
- `3`: malformed request.

## Boundaries

This tool does not decide whether a provider satisfies a data class. Callers
must supply policy decisions. It does not contain provider credentials,
production adapters, customer data, pricing claims, or automatic tool replay.
It does not call a provider-specific deployment reload API. Recovery is
achieved through bounded failover; native reload can be added only where a
provider exposes and documents such an API.
