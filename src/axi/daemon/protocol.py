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

    method: Literal["list_tools", "call_tool", "search", "describe", "shutdown"] = (
        Field(description="方法名")
    )
    tool_name: str | None = Field(default=None, description="工具完整名称")
    params: dict[str, Any] | None = Field(default=None, description="调用参数")
    query: str | None = Field(default=None, description="搜索关键词")
    regex: bool = Field(default=False, description="是否使用正则搜索")
    top_k: int = Field(default=10, description="搜索结果数量")


class DaemonResponse(ResultEnvelope):
    """daemon 响应。"""
