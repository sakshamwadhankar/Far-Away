"""Cross-platform smoke test for the packaged Komvos backend binary.

Launches the PyInstaller-built executable exactly the way Electron does:
bound to 127.0.0.1, authenticated via the KOMVOS_SESSION_TOKEN environment
variable (fail-closed — no KOMVOS_DEV), with KOMVOS_ALLOW_MOCK_ENDPOINT=1
so the mock endpoint can execute a pipeline without real API keys.

Steps:
  1. Pick a free port.
  2. Spawn packaging/dist/komvos_backend(.exe) with --host 127.0.0.1 --port N.
  3. Poll /health until HTTP 200 (hard timeout).
  4. POST a 3-node pipeline whose model node uses the mock endpoint.
  5. Poll /runs/{run_id}/trace until the run reaches a terminal status;
     assert it is "completed".
  6. Terminate the process. Any failure exits non-zero.

Usage: python packaging/scripts/smoke_backend.py [path-to-binary]
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HEALTH_TIMEOUT_S = 60.0
RUN_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 0.5
TERMINAL_STATUSES = {"completed", "error", "stopped", "budget_exceeded", "halted"}

PIPELINE = {
    "schema_version": "2.0",
    "id": str(uuid.uuid4()),
    "name": "CI Smoke Test Pipeline",
    "version": "1.0.0",
    "nodes": [
        {
            "id": "in",
            "type": "input",
            "outputs": [{"name": "prompt", "type": "text"}],
        },
        {
            "id": "model_node",
            "type": "model",
            "endpoint_ref": "mock:smoke",
            "inputs": [{"name": "input", "type": "text"}],
            "outputs": [{"name": "output", "type": "text"}],
            "config": {"temperature": 0.7, "max_tokens": 20},
        },
        {
            "id": "out",
            "type": "output",
            "inputs": [{"name": "result", "type": "text"}],
        },
    ],
    "loops": [],
    "edges": [
        {"from": "in.prompt", "to": "model_node.input"},
        {"from": "model_node.output", "to": "out.result"},
    ],
    "endpoints": {
        "mock:smoke": {"kind": "mock", "model": "smoke-model"},
    },
}


def die(msg: str) -> None:
    print(f"SMOKE TEST FAILED: {msg}", flush=True)
    sys.exit(1)


def resolve_binary() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dist = os.path.join(root, "packaging", "dist")
    exe = os.path.join(dist, "komvos_backend.exe" if os.name == "nt" else "komvos_backend")
    if not os.path.isfile(exe):
        die(f"built backend binary not found at {exe}")
    return exe


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(
    url: str, token: str | None = None, body: dict | None = None, method: str = "GET"
) -> tuple[int, dict | str]:
    headers = {}
    data = None
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode()
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode()
        try:
            return exc.code, json.loads(payload)
        except json.JSONDecodeError:
            return exc.code, payload


def poll_health(port: int) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            status, _ = request(f"http://127.0.0.1:{port}/health")
            if status == 200:
                print(f"Backend healthy on 127.0.0.1:{port}", flush=True)
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(POLL_INTERVAL_S)
    die(f"/health did not return 200 within {HEALTH_TIMEOUT_S:.0f}s")


def run_pipeline(port: int, token: str) -> None:
    status, payload = request(
        f"http://127.0.0.1:{port}/pipelines/run",
        token=token,
        body={"pipeline": PIPELINE},
        method="POST",
    )
    if status != 202:
        die(f"POST /pipelines/run returned {status}: {payload}")
    run_id = payload.get("run_id")
    if not run_id:
        die(f"no run_id in response: {payload}")
    print(f"Started run {run_id}", flush=True)

    deadline = time.monotonic() + RUN_TIMEOUT_S
    while time.monotonic() < deadline:
        status, trace = request(
            f"http://127.0.0.1:{port}/runs/{run_id}/trace", token=token
        )
        if status == 200:
            run_status = (trace.get("run") or {}).get("status")
            if run_status in TERMINAL_STATUSES:
                if run_status != "completed":
                    die(f"run reached terminal status '{run_status}': {trace}")
                nodes_done = len(trace.get("nodes") or [])
                print(
                    f"Run completed ({nodes_done} node executions recorded)",
                    flush=True,
                )
                return
        elif status != 404:
            die(f"GET /runs/{run_id}/trace returned {status}: {trace}")
        time.sleep(POLL_INTERVAL_S)
    die(f"run did not reach a terminal state within {RUN_TIMEOUT_S:.0f}s")


def main() -> None:
    binary = resolve_binary()
    port = free_port()
    token = secrets.token_urlsafe(32)

    # Mirror the Electron packaged spawn path (apps/desktop/src/main.ts):
    # session token via env, mock gate opt-in, KOMVOS_DEV stripped so the
    # backend runs with production (fail-closed) auth semantics.
    env = os.environ.copy()
    env["KOMVOS_SESSION_TOKEN"] = token
    env["KOMVOS_ALLOW_MOCK_ENDPOINT"] = "1"
    env.pop("KOMVOS_DEV", None)

    print(f"Launching {binary} on 127.0.0.1:{port}", flush=True)
    proc = subprocess.Popen(
        [binary, "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        if proc.poll() is not None:
            die(f"{binary} exited immediately with code {proc.returncode}")
        poll_health(port)
        run_pipeline(port, token)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=15)
    print("Smoke test passed.", flush=True)


if __name__ == "__main__":
    main()
