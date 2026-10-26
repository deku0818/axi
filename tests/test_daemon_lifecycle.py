"""真实子进程回归：残留 socket、初始化取消和 MCP 进程回收。"""

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest


MCP_SERVER = """
import json, os, sys, time
from pathlib import Path

root, name, block_on = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
(root / f'{name}.worker.pid').write_text(str(os.getpid()))
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    if method == block_on:
        (root / 'blocked').touch()
        while not (root / 'release').exists():
            time.sleep(0.02)
    if 'id' not in request:
        continue
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'],
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': name, 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': []}
    else:
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""


def _wait_for(check: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 15
    while not check():
        if time.monotonic() >= deadline:
            pytest.fail("Timed out waiting for daemon/MCP process state")
        time.sleep(0.02)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@contextmanager
def _daemon(
    block_on: str, *, stale_socket: bool = False
) -> Iterator[tuple[subprocess.Popen[bytes], dict[str, str], Path, Path]]:
    # macOS 的 Unix socket 路径长度有限，不能使用 pytest 的长临时目录。
    with tempfile.TemporaryDirectory(prefix="axi-test-", dir="/tmp") as directory:
        root = Path(directory)
        worker = root / "mcp.py"
        worker.write_text(MCP_SERVER)
        config = root / "axi.json"
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        name: {
                            "command": sys.executable,
                            "args": [str(worker), str(root), name, stage],
                        }
                        for name, stage in (
                            ("ready-a", ""),
                            ("ready-b", ""),
                            ("slow", block_on),
                        )
                    }
                }
            )
        )
        env = {
            "HOME": str(root),
            "AXI_CONFIG": str(config),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        key = hashlib.sha256(str(config.resolve()).encode()).hexdigest()[:12]
        runtime = root / ".axi" / "daemons"
        runtime.mkdir(parents=True)
        sock_path = runtime / f"{key}.sock"
        if stale_socket:
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(sock_path))
            (runtime / f"{key}.pid").write_text("4000000")
        with open(root / "daemon.log", "w") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "axi.daemon.server"],
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                yield proc, env, root, sock_path
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                for pid_file in root.glob("*.worker.pid"):
                    pid = int(pid_file.read_text())
                    with suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)


def _cli(env: dict[str, str], command: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", "from axi.cli import app; app()", "daemon", command],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout


def _stop_and_check_cleanup(
    proc: subprocess.Popen[bytes], env: dict[str, str], root: Path, sock_path: Path
) -> None:
    pids = [int(path.read_text()) for path in root.glob("*.worker.pid")]
    assert len(pids) == 3
    assert _cli(env, "stop").strip() == "Daemon stopped."
    assert proc.wait(timeout=15) == 0
    _wait_for(lambda: not any(_alive(pid) for pid in pids))
    assert not sock_path.exists()
    assert not list(sock_path.parent.glob("*.pid"))
    assert "Error closing MCP connection" not in (root / "daemon.log").read_text()


def test_stale_socket_does_not_make_initializing_daemon_ready() -> None:
    with _daemon("initialize", stale_socket=True) as (proc, env, root, sock_path):
        _wait_for(lambda: (root / "blocked").exists())
        assert json.loads(_cli(env, "status")) == {
            "status": "starting",
            "pid": proc.pid,
        }
        assert not sock_path.exists()
        (root / "release").touch()
        _wait_for(sock_path.exists)
        assert json.loads(_cli(env, "status"))["status"] == "running"
        _stop_and_check_cleanup(proc, env, root, sock_path)


@pytest.mark.parametrize("block_on", ["initialize", "tools/list"])
def test_stop_during_startup_reaps_all_mcp_processes(block_on: str) -> None:
    with _daemon(block_on) as (proc, env, root, sock_path):
        _wait_for(lambda: (root / "blocked").exists())
        assert json.loads(_cli(env, "status"))["status"] == "starting"
        _stop_and_check_cleanup(proc, env, root, sock_path)
