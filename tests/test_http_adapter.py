import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortxt_resilient_inference.http_adapter import OpenAICompatibleAdapter


class StubHandler(BaseHTTPRequestHandler):
    status = 200
    delay_seconds = 0.0
    redirect_url = None
    received_authorizations = None
    message_role = "assistant"

    def do_POST(self):
        if self.received_authorizations is not None:
            self.received_authorizations.append(self.headers.get("Authorization"))
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.redirect_url:
            try:
                self.send_response(302)
                self.send_header("Location", self.redirect_url)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        body = json.dumps({
            "choices": [{"message": {"role": self.message_role, "content": request["model"]}}]
        }).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format, *_args):
        pass


class StubServer:
    def __init__(self, status=200, delay=0.0, redirect_url=None, capture=False,
                 message_role="assistant"):
        attributes = {"status": status, "delay_seconds": delay, "redirect_url": redirect_url,
                      "received_authorizations": [] if capture else None,
                      "message_role": message_role}
        handler = type("ConfiguredHandler", (StubHandler,), attributes)
        self.handler = handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def route(base_url):
    return {"route_id": "test", "base_url": base_url, "model": "model-a",
            "api_key_env": "CORTXT_TEST_API_KEY", "policy_eligible": True}


class HttpAdapterTests(unittest.TestCase):
    def setUp(self):
        os.environ["CORTXT_TEST_API_KEY"] = "not-a-real-key"
        self.adapter = OpenAICompatibleAdapter([{"role": "user", "content": "hello"}])

    def tearDown(self):
        os.environ.pop("CORTXT_TEST_API_KEY", None)

    def test_success_returns_only_assistant_message(self):
        with StubServer() as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "succeeded")
        self.assertEqual(result["response"], {"role": "assistant", "content": "model-a"})

    def test_non_assistant_message_is_rejected(self):
        with StubServer(message_role="user") as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "invalid_response")
        self.assertEqual(result["effect_state"], "unknown")

    def test_404_is_invalid_model_id(self):
        with StubServer(status=404) as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "invalid_model_id")

    def test_429_is_rate_limited(self):
        with StubServer(status=429) as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "rate_limited")

    def test_500_is_provider_unavailable(self):
        with StubServer(status=500) as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "provider_unavailable")
        self.assertEqual(result["effect_state"], "unknown")

    def test_redirect_is_blocked_without_forwarding_credentials(self):
        target_server = StubServer(capture=True)
        with target_server as target_url:
            target = target_url + "/capture"
            with StubServer(redirect_url=target) as base_url:
                result = self.adapter(route(base_url), 3000)
            self.assertEqual(result["outcome"], "invalid_configuration")
            self.assertEqual(result["effect_state"], "unknown")
            self.assertEqual(target_server.handler.received_authorizations, [])

    def test_hanging_response_is_terminated_at_bounded_deadline(self):
        with StubServer(delay=2.0) as base_url:
            started = time.monotonic()
            result = self.adapter(route(base_url), 300)
            elapsed = time.monotonic() - started
        self.assertEqual(result["outcome"], "return_channel_stalled")
        self.assertEqual(result["effect_state"], "unknown")
        self.assertLess(elapsed, 1.5)

    def test_missing_credentials_fail_without_request(self):
        os.environ.pop("CORTXT_TEST_API_KEY")
        with StubServer() as base_url:
            result = self.adapter(route(base_url), 3000)
        self.assertEqual(result["outcome"], "missing_credentials")

    def test_insecure_remote_url_is_rejected(self):
        result = self.adapter(route("http://example.com/v1"), 3000)
        self.assertEqual(result["outcome"], "invalid_configuration")


if __name__ == "__main__":
    unittest.main()
