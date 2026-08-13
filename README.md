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
