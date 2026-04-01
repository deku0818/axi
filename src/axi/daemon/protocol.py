"""daemon 通信协议：JSON 行格式的请求/响应。"""

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from axi.models import ResultEnvelope

# Unix socket 路径
SOCKET_DIR = os.path.expanduser("~/.axi")
SOCKET_PATH = os.path.join(SOCKET_DIR, "daemon.sock")
PID_PATH = os.path.join(SOCKET_DIR, "daemon.pid")


class DaemonRequest(BaseModel):
    """daemon 请求。"""

    method: Literal[
        "list_tools", "call_tool", "search", "grep", "describe", "shutdown", "status"
    ] = Field(description="方法名")
    tool_name: str | None = Field(default=None, description="工具完整名称")
    params: dict[str, Any] | None = Field(default=None, description="调用参数")
    query: str | None = Field(default=None, description="搜索关键词")
    top_k: int = Field(default=5, description="搜索结果数量")


class DaemonStatus(BaseModel):
    """daemon 状态信息。"""

    pid: int = Field(description="进程 ID")
    uptime_seconds: int = Field(description="运行时长（秒）")
    idle_seconds: int = Field(description="空闲时长（秒）")
    idle_timeout_seconds: int = Field(description="空闲超时阈值（秒）")
    idle_remaining_seconds: int = Field(description="距自动关闭剩余（秒）")
    server_tools: dict[str, int] = Field(
        default_factory=dict, description="各 server 工具数量"
    )


class DaemonResponse(ResultEnvelope):
    """daemon 响应。"""
