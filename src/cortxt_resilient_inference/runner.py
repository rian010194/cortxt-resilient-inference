"""Provider-neutral fallback state machine with deterministic evidence."""

from dataclasses import asdict, dataclass
from typing import Callable, Mapping


RETRYABLE = {"rate_limited", "provider_unavailable", "provider_overloaded",
             "timeout_before_effect", "return_channel_stalled"}
PERMANENT = {"invalid_model_id", "policy_denied", "non_idempotent_effect_unknown",
             "missing_credentials", "invalid_configuration", "invalid_response"}
KNOWN_OUTCOMES = RETRYABLE | PERMANENT | {"succeeded"}


@dataclass(frozen=True)
class Attempt:
    attempt: int
    route_id: str
    outcome: str
    latency_ms: int
    cost_status: str


Adapter = Callable[[Mapping[str, object], int], Mapping[str, object]]


def _terminal(task_id: str, status: str, attempts: list[Attempt], reason: str,
              route_id: str | None = None,
              response: Mapping[str, object] | None = None) -> dict[str, object]:
    envelope = {
        "task_id": task_id,
        "status": status,
        "selected_route_id": route_id,
        "terminal_reason": reason,
        "attempts": [asdict(attempt) for attempt in attempts],
    }
    if response is not None:
        envelope["response"] = dict(response)
    return envelope


def execute(request: Mapping[str, object], adapters: Mapping[str, Adapter]) -> dict[str, object]:
    """Execute eligible routes in order within the declared safety bounds."""
    task_id = request["task_id"]
    routes = request["routes"]
    max_attempts = request["max_attempts_total"]
    timeout_ms = request["per_attempt_timeout_ms"]
    idempotency = request["idempotency"]
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id must be a non-empty string")
    if (
        not isinstance(routes, list)
        or not routes
        or not all(
            isinstance(route, Mapping)
            and isinstance(route.get("route_id"), str)
            and bool(route.get("route_id"))
            for route in routes
        )
    ):
        raise ValueError("routes must contain mappings with non-empty route_id values")
    if type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError("max_attempts_total must be a positive integer")
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise ValueError("per_attempt_timeout_ms must be a positive integer")
    if idempotency not in {"read_only", "idempotent", "non_idempotent"}:
        raise ValueError("unknown idempotency fails closed")
    attempts: list[Attempt] = []

    for route in routes:
        if len(attempts) >= max_attempts:
            break
        if route.get("policy_eligible") is not True:
            continue
        route_id = route["route_id"]
        adapter = adapters.get(route_id)
        if adapter is None:
            raw = {"outcome": "provider_unavailable", "latency_ms": 0, "cost_status": "unknown"}
        else:
            raw = adapter(route, timeout_ms)
        outcome = raw.get("outcome")
        if outcome not in KNOWN_OUTCOMES:
            outcome = "provider_unavailable"
        latency = raw.get("latency_ms")
        latency = latency if type(latency) is int and latency >= 0 else 0
        cost_status = raw.get("cost_status")
        cost_status = cost_status if cost_status in {"actual", "estimated", "unknown"} else "unknown"
        attempts.append(Attempt(len(attempts) + 1, route_id, outcome, latency, cost_status))

        if outcome == "succeeded":
            response = raw.get("response")
            if not isinstance(response, Mapping):
                attempts[-1] = Attempt(attempts[-1].attempt, route_id, "invalid_response",
                                       latency, cost_status)
                if idempotency == "non_idempotent":
                    return _terminal(task_id, "blocked", attempts,
                                     "non_idempotent_effect_unknown")
                continue
            return _terminal(task_id, "succeeded", attempts, "completed", route_id, response)
        effect_state = raw.get("effect_state", "before_effect")
        if idempotency == "non_idempotent" and effect_state != "before_effect":
            return _terminal(task_id, "blocked", attempts, "non_idempotent_effect_unknown")
        if outcome in PERMANENT:
            continue

    eligible = any(route.get("policy_eligible") is True for route in routes)
    reason = "attempt_budget_exhausted" if eligible and len(attempts) >= max_attempts else "no_eligible_fallback"
    return _terminal(task_id, "blocked", attempts, reason)
