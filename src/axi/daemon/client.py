"""daemon 客户端：CLI 侧通过 Unix socket 与 daemon 通信。"""

import asyncio
import logging
import os
import subprocess
import sys
import time

from axi.daemon.protocol import (
    SOCKET_DIR,
    SOCKET_PATH,
    PID_PATH,
    DaemonRequest,
    DaemonResponse,
)

logger = logging.getLogger(__name__)

DAEMON_LOG_PATH = os.path.join(SOCKET_DIR, "daemon.log")

_DAEMON_START_POLL_RETRIES = 30
_DAEMON_START_POLL_INTERVAL = 0.1  # seconds
_DAEMON_REQUEST_TIMEOUT = 30  # seconds


def is_daemon_running() -> bool:
    """检查 daemon 是否在运行。"""
    if not os.path.exists(PID_PATH):
        return False

    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return os.path.exists(SOCKET_PATH)
    except (OSError, ValueError):
        return False


def ensure_daemon() -> bool:
    """确保 daemon 已启动。未运行时自动启动，返回是否就绪。"""
    if is_daemon_running():
        return True

    os.makedirs(SOCKET_DIR, exist_ok=True)

    with open(DAEMON_LOG_PATH, "a") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "axi.daemon.server"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    for _ in range(_DAEMON_START_POLL_RETRIES):
        time.sleep(_DAEMON_START_POLL_INTERVAL)
        if is_daemon_running():
            return True
    logger.error("Daemon failed to start. Check log: %s", DAEMON_LOG_PATH)
    return False


def send_request(req: DaemonRequest) -> DaemonResponse:
    """向 daemon 发送请求并获取响应。"""
    return asyncio.run(_send(req))


async def _send(req: DaemonRequest) -> DaemonResponse:
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    except OSError as e:
        return DaemonResponse.fail(
            f"Cannot connect to daemon: {e}. Try: axi daemon stop && axi daemon start"
        )

    try:
        writer.write(req.model_dump_json().encode() + b"\n")
        await writer.drain()

        line = await asyncio.wait_for(
            reader.readline(), timeout=_DAEMON_REQUEST_TIMEOUT
        )
        if not line:
            return DaemonResponse.fail("Daemon connection closed unexpectedly")

        return DaemonResponse.model_validate_json(line)
    except asyncio.TimeoutError:
        return DaemonResponse.fail(
            f"Daemon request timed out after {_DAEMON_REQUEST_TIMEOUT}s"
        )
    finally:
        writer.close()
        await writer.wait_closed()
