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

# 等待 daemon 就绪的上限。daemon 要先连上所有 MCP server 才创建 socket，
# 官方 MCP 由 uvx 拉起、首次还要下载依赖，冷启动远超旧的 3 秒窗口。
_DAEMON_START_TIMEOUT = 60.0  # seconds
_DAEMON_START_POLL_INTERVAL = 0.1  # seconds

# 等待 daemon 退出（关 MCP 连接、删 PID / socket）的上限
DAEMON_STOP_TIMEOUT = 5.0  # seconds

# StreamReader 缓冲区上限。默认 64KB 放不下完整工具列表（list/search 的响应是单行
# JSON，工具多时轻松超过 64KB），会抛 asyncio.LimitOverrunError。调大到 8MB。
_STREAM_LIMIT = 8 * 1024 * 1024


def read_live_pid() -> int | None:
    """PID 文件里的进程仍存活时返回 pid，否则 None。"""
    try:
        with open(PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def is_daemon_running() -> bool:
    """daemon 已就绪（进程存活且 socket 已创建）时返回 True。"""
    return read_live_pid() is not None and os.path.exists(SOCKET_PATH)


def wait_for_exit(timeout: float = DAEMON_STOP_TIMEOUT) -> bool:
    """等待 daemon 进程退出，超时返回 False。

    shutdown 响应先于资源清理返回（关 MCP 连接、删 PID / socket），
    调用方在报告停止成功前先等 PID 消失，否则紧接着的 start 会撞上
    仍在收尾的进程，误判为 already running。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_live_pid() is None:
            return True
        time.sleep(_DAEMON_START_POLL_INTERVAL)
    return False


def _spawn_and_wait() -> bool:
    """拉起 daemon 子进程并轮询直到就绪。调用方需持有启动锁。"""
    with open(LOG_PATH, "a") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "axi.daemon.server"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
            env={**os.environ, "AXI_CONFIG": str(CONFIG_PATH)},
        )

    deadline = time.monotonic() + _DAEMON_START_TIMEOUT
    while time.monotonic() < deadline:
        if is_daemon_running():
            return True
        # 子进程已退出：socket 不会再出现，别把超时时间白等完
        if proc.poll() is not None:
            logger.error(
                "Daemon exited with code %s during startup. Check log: %s",
                proc.returncode,
                LOG_PATH,
            )
            return False
        time.sleep(_DAEMON_START_POLL_INTERVAL)
    logger.error(
        "Daemon did not become ready within %.0fs. Check log: %s",
        _DAEMON_START_TIMEOUT,
        LOG_PATH,
    )
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
        reader, writer = await asyncio.open_unix_connection(
            SOCKET_PATH, limit=_STREAM_LIMIT
        )
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
