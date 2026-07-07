"""请求级变量：native 工具的统一变量读取入口。

stdio / CLI 形态下变量来自进程环境变量；HTTP MCP 形态下 server 是共享进程，
每个客户端的变量通过 ``Axi-*`` header 随请求传入，按请求隔离。
"""

import os
from collections.abc import Mapping
from contextvars import ContextVar

_request_env: ContextVar[dict[str, str]] = ContextVar("axi_request_env", default={})

_ENV_HEADER_PREFIX = "axi-"


def set_request_env(headers: Mapping[str, str] | None) -> None:
    """从 ``Axi-*`` header 提取当前请求的变量：``Axi-Foo-Bar`` → ``FOO_BAR``。

    由 mcp_serve 在每次 native 工具调用前调用；``None``（stdio 无请求）置空。
    ASGI 规范保证 header 名已小写。
    """
    _request_env.set(
        {
            name.removeprefix(_ENV_HEADER_PREFIX).replace("-", "_").upper(): value
            for name, value in headers.items()
            if name.startswith(_ENV_HEADER_PREFIX)
        }
        if headers
        else {}
    )


def env(name: str, default: str | None = None) -> str | None:
    """读取变量：请求级（HTTP header）优先，其次进程环境变量。"""
    value = _request_env.get().get(name)
    return value if value is not None else os.environ.get(name, default)
