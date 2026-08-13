import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_example_succeeds(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run(
            [sys.executable, "-m", "cortxt_resilient_inference.cli", "examples/timeout-fallback.json"],
            cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["selected_route_id"], "fallback")
        self.assertEqual(len(payload["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()
