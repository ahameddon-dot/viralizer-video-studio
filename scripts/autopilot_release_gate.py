"""Run local, PostgreSQL, and optional authenticated staging release gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_MODULES = [
    "tests.test_autopilot_postgres_gate", "tests.test_autopilot_retention",
    "tests.test_autopilot_operations", "tests.test_autopilot_providers",
    "tests.test_autopilot_growth", "tests.test_autopilot_lifecycle",
    "tests.test_autopilot_ui", "tests.test_autopilot_intelligence",
    "tests.test_autopilot_foundation",
]


def run_tests() -> None:
    completed = subprocess.run([sys.executable, "-m", "unittest", *TEST_MODULES], cwd=ROOT)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def request_json(base_url: str, path: str) -> dict:
    headers = {"Accept": "application/json"}
    request = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return json.loads(response.read())


def staging_gate() -> None:
    base_url = os.getenv("AUTOPILOT_STAGING_BASE_URL", "").strip()
    if not base_url:
        print("STAGING GATE: SKIPPED — AUTOPILOT_STAGING_BASE_URL is not configured")
        return
    health = request_json(base_url, "/health")
    if not health:
        raise RuntimeError("Staging health response was empty")
    print("STAGING HEALTH GATE: PASSED")


if __name__ == "__main__":
    run_tests()
    if not os.getenv("AUTOPILOT_TEST_DATABASE_URL"):
        print("POSTGRES GATE: SKIPPED — AUTOPILOT_TEST_DATABASE_URL is not configured")
    else:
        print("POSTGRES GATE: PASSED")
    try:
        staging_gate()
    except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"STAGING GATE: FAILED — {exc}", file=sys.stderr)
        raise SystemExit(1)
