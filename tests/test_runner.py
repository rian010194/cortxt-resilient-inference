import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortxt_resilient_inference.runner import execute


def request(idempotency="read_only", eligible=(True, True), max_attempts=2):
    return {
        "task_id": "test-task", "data_class": "L0", "idempotency": idempotency,
        "max_attempts_total": max_attempts, "per_attempt_timeout_ms": 100,
        "routes": [
            {"route_id": "primary", "provider": "a", "model": "a", "policy_eligible": eligible[0]},
            {"route_id": "fallback", "provider": "b", "model": "b", "policy_eligible": eligible[1]},
        ],
    }


def adapter(outcome, **extra):
    return lambda _route, _timeout: {"outcome": outcome, "latency_ms": 10,
                                     "cost_status": "estimated", **extra}


class RunnerTests(unittest.TestCase):
    def test_timeout_falls_back_and_preserves_evidence(self):
        result = execute(request(), {"primary": adapter("timeout_before_effect"),
                                     "fallback": adapter("succeeded")})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["selected_route_id"], "fallback")
        self.assertEqual([a["outcome"] for a in result["attempts"]],
                         ["timeout_before_effect", "succeeded"])

    def test_policy_ineligible_fallback_is_never_called(self):
        called = []
        def unsafe(_route, _timeout):
            called.append(True)
            return {"outcome": "succeeded"}
        result = execute(request(eligible=(True, False)),
                         {"primary": adapter("provider_unavailable"), "fallback": unsafe})
        self.assertEqual(result["terminal_reason"], "no_eligible_fallback")
        self.assertEqual(called, [])

    def test_attempt_budget_is_hard_limit(self):
        result = execute(request(max_attempts=1), {"primary": adapter("rate_limited"),
                                                   "fallback": adapter("succeeded")})
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["terminal_reason"], "attempt_budget_exhausted")

    def test_non_idempotent_unknown_effect_blocks_replay(self):
        result = execute(request(idempotency="non_idempotent"), {
            "primary": adapter("return_channel_stalled", effect_state="unknown"),
            "fallback": adapter("succeeded"),
        })
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["terminal_reason"], "non_idempotent_effect_unknown")
        self.assertEqual(len(result["attempts"]), 1)

    def test_unknown_outcome_fails_closed(self):
        result = execute(request(max_attempts=1), {"primary": adapter("mystery")})
        self.assertEqual(result["attempts"][0]["outcome"], "provider_unavailable")
        self.assertEqual(result["status"], "blocked")

    def test_request_is_not_mutated(self):
        original = request()
        before = copy.deepcopy(original)
        execute(original, {"primary": adapter("succeeded")})
        self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
