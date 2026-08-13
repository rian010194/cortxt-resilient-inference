# Cortxt Resilient Inference

A small, provider-neutral tool for bounded retries and policy-gated
fallback when an inference route is unavailable, rate limited, too slow, or
fails to return a usable result.

It is deliberately independent of any inference provider, agent runtime, or
provider SDK.

## Features

- routes are tried in declared order and only when `policy_eligible` is exactly
  `true`;
- total attempts and per-attempt deadlines are bounded;
- permanent and transient failures remain explicit in the evidence envelope;
- non-idempotent work is never replayed after an effect may have occurred;
- an unsafe fallback is skipped rather than silently weakening policy;
- every terminal outcome contains the complete attempt history.

The bundled CLI uses deterministic simulated routes. It makes no network or
model calls and accepts no credentials.

## Quickstart

```text
python -m unittest discover -s tests -v
set PYTHONPATH=src
python -m cortxt_resilient_inference.cli examples/timeout-fallback.json
```

Expected CLI exit codes:

- `0`: succeeded;
- `2`: failed or blocked by routing/policy;
- `3`: malformed request.

## Boundaries

This tool does not decide whether a provider satisfies a data class. Callers
must supply policy decisions. It does not contain provider credentials,
production adapters, customer data, pricing claims, or automatic tool replay.
