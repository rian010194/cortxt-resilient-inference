"""OpenAI-compatible HTTP adapter with a hard process deadline."""

import json
import multiprocessing
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials never cross an unvalidated origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)


def _endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("base_url must use HTTPS (HTTP is allowed only for localhost tests)")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain credentials, query, or fragment")
    return base_url.rstrip("/") + "/chat/completions"


def _classify_http_status(status: int) -> str:
    if status == 404:
        return "invalid_model_id"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "invalid_configuration"
    return "provider_unavailable"


def _worker(base_url: str, model: str, messages: Sequence[Mapping[str, object]],
            api_key_env: str, response_connection) -> None:
    started = time.monotonic()
    result: dict[str, object]
    try:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            result = {"outcome": "missing_credentials"}
        else:
            body = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
            request = urllib.request.Request(
                _endpoint(base_url), data=body, method="POST",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(request) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                result = {"outcome": "invalid_response", "effect_state": "unknown"}
            else:
                payload = json.loads(raw.decode("utf-8"))
                message = payload["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError
                result = {"outcome": "succeeded", "response": message}
    except urllib.error.HTTPError as exc:
        result = {"outcome": _classify_http_status(exc.code), "effect_state": "unknown"}
    except (urllib.error.URLError, TimeoutError, OSError):
        result = {"outcome": "provider_unavailable", "effect_state": "unknown"}
    except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        result = {"outcome": "invalid_response", "effect_state": "unknown"}
    result["latency_ms"] = max(0, int((time.monotonic() - started) * 1000))
    result["cost_status"] = "unknown"
    try:
        response_connection.send(result)
    finally:
        response_connection.close()


def _stop_process(process) -> None:
    """Stop a worker without leaving an inference request running in the background."""
    if process.is_alive():
        process.terminate()
        process.join(0.1)
    if process.is_alive():
        process.kill()
        process.join(0.1)


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    """Invoke one OpenAI-compatible route inside a terminable child process."""

    messages: Sequence[Mapping[str, object]]

    def __call__(self, route: Mapping[str, object], timeout_ms: int) -> Mapping[str, object]:
        if type(timeout_ms) is not int or timeout_ms <= 0:
            return {"outcome": "invalid_configuration", "latency_ms": 0, "cost_status": "unknown"}
        try:
            base_url = route["base_url"]
            model = route["model"]
            api_key_env = route["api_key_env"]
            if not all(isinstance(value, str) and value for value in (base_url, model, api_key_env)):
                raise ValueError
            _endpoint(base_url)
            if not isinstance(self.messages, (list, tuple)) or not self.messages:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            return {"outcome": "invalid_configuration", "latency_ms": 0, "cost_status": "unknown"}

        context = multiprocessing.get_context("spawn")
        response_connection, worker_connection = context.Pipe(duplex=False)
        process = context.Process(
            target=_worker,
            args=(base_url, model, self.messages, api_key_env, worker_connection),
        )
        started = time.monotonic()
        try:
            process.start()
        except (OSError, RuntimeError):
            response_connection.close()
            worker_connection.close()
            return {"outcome": "provider_unavailable", "effect_state": "before_effect",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "cost_status": "unknown"}
        worker_connection.close()
        remaining = max(0.0, timeout_ms / 1000 - (time.monotonic() - started))
        if not response_connection.poll(remaining):
            _stop_process(process)
            response_connection.close()
            return {
                "outcome": "return_channel_stalled",
                "effect_state": "unknown",
                "latency_ms": max(timeout_ms, int((time.monotonic() - started) * 1000)),
                "cost_status": "unknown",
            }
        try:
            result = response_connection.recv()
        except (EOFError, OSError):
            result = {"outcome": "provider_unavailable", "effect_state": "unknown",
                      "latency_ms": int((time.monotonic() - started) * 1000), "cost_status": "unknown"}
        finally:
            response_connection.close()
            _stop_process(process)
        return result
