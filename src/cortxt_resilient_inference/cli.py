"""Offline CLI using deterministic simulated route outcomes."""

import json
import sys
from pathlib import Path

from .http_adapter import OpenAICompatibleAdapter
from .runner import execute


def _simulated_adapter(spec):
    def invoke(_route, _timeout_ms):
        return dict(spec)
    return invoke


def run(path: str) -> int:
    try:
        request = json.loads(Path(path).read_text(encoding="utf-8"))
        simulations = request.pop("simulations", None)
        messages = request.pop("messages", None)
        if simulations is not None:
            if not isinstance(simulations, dict):
                raise ValueError
            adapters = {route_id: _simulated_adapter(spec) for route_id, spec in simulations.items()}
        else:
            if not isinstance(messages, list) or not messages:
                raise ValueError
            adapter = OpenAICompatibleAdapter(messages)
            adapters = {route["route_id"]: adapter for route in request["routes"]}
        result = execute(request, adapters)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        print('{"error":"invalid_request"}')
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "succeeded" else 2


def main() -> int:
    if len(sys.argv) != 2:
        print('{"error":"usage"}')
        return 3
    return run(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
