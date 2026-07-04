"""daemon 客户端：CLI 侧通过 Unix socket 与 daemon 通信。"""

import asyncio
import fcntl
import logging
import os
import subprocess
import sys
import time

from axi.config import CONFIG_PATH, app_config
from axi.daemon.protocol import (
    LOCK_PATH,
    LOG_PATH,
    SOCKET_DIR,
    SOCKET_PATH,
    PID_PATH,
    DaemonRequest,
    DaemonResponse,
)

logger = logging.getLogger(__name__)

_DAEMON_START_POLL_RETRIES = 30
_DAEMON_START_POLL_INTERVAL = 0.1  # seconds


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


def _spawn_and_wait() -> bool:
    """拉起 daemon 子进程并轮询直到就绪。调用方需持有启动锁。"""
    with open(LOG_PATH, "a") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "axi.daemon.server"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
            env={**os.environ, "AXI_CONFIG": str(CONFIG_PATH)},
        )

    for _ in range(_DAEMON_START_POLL_RETRIES):
        time.sleep(_DAEMON_START_POLL_INTERVAL)
        if is_daemon_running():
            return True
    logger.error("Daemon failed to start. Check log: %s", LOG_PATH)
    return False


def ensure_daemon() -> bool:
    """确保 daemon 已启动。未运行时自动启动，返回是否就绪。

    并行的多个 axi 进程可能同时发现 daemon 未运行。用文件锁串行化启动：
    只有拿到锁的进程 spawn，其余进程阻塞在锁上，拿到锁后复查发现已就绪即返回。
    否则会多进程各拉起一个 daemon、互相 unlink socket、覆盖 PID 文件。
    """
    if is_daemon_running():
        return True

    os.makedirs(SOCKET_DIR, exist_ok=True)

    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # 锁内复查：可能刚才另一个进程已经把 daemon 拉起来了
        if is_daemon_running():
            return True
        return _spawn_and_wait()


def send_request(req: DaemonRequest) -> DaemonResponse:
    """向 daemon 发送请求并获取响应。"""
    return asyncio.run(_send(req))


def daemon_request(req: DaemonRequest) -> DaemonResponse:
    """确保 daemon 已启动后发送请求。所有入口（CLI/PTC/MCP serve）统一走这里。"""
    if not ensure_daemon():
        return DaemonResponse.fail(f"Failed to start axi daemon. Check log: {LOG_PATH}")
    return send_request(req)


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

        timeout = app_config.daemon.request_timeout
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if not line:
            return DaemonResponse.fail("Daemon connection closed unexpectedly")

        return DaemonResponse.model_validate_json(line)
    except asyncio.TimeoutError:
        return DaemonResponse.fail(
            f"Daemon request timed out after {timeout}s. Raise it via "
            "AXI_REQUEST_TIMEOUT or axi.json daemon.requestTimeout."
        )
    finally:
        writer.close()
        await writer.wait_closed()
