from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_real_api_subprocess_reaches_status_endpoint(isolated_runtime):
    project_root = Path(__file__).resolve().parents[2]
    package_parent = project_root.parents[1]
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(package_parent), env.get("PYTHONPATH", "")])
    )
    env["RXYCODE_DATA_DIR"] = str(isolated_runtime.data_dir)
    api_token = "system-test-api-token"
    launch_script = (
        "import uvicorn; "
        "from RxyCode.RxyCode1_1_0 import api_server; "
        f"api_server.configure_api_token({api_token!r}); "
        f"uvicorn.run(api_server.app, host='127.0.0.1', port={port}, log_level='warning')"
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            launch_script,
        ],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 15
    response = None
    try:
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise AssertionError(
                        f"API process exited with {process.returncode}: {output}"
                    )
                try:
                    response = client.get(
                        f"http://127.0.0.1:{port}/status",
                        headers={"Authorization": f"Bearer {api_token}"},
                        timeout=0.25,
                    )
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)

        assert response is not None and response.status_code == 200
        payload = response.json()
        assert {"mode", "input_tokens", "output_tokens"} <= payload.keys()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
