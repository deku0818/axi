"""axi — Agent eXecution Interface."""

import logging
from typing import Any, Callable

from axi.cli import get_executor, get_registry
from axi.providers.native import register_tool

__all__ = ["tool"]

# 包级 logger：各子模块通过 logging.getLogger(__name__) 自动继承
_logger = logging.getLogger("axi")
_logger.addHandler(logging.NullHandler())


def tool(
    name: str | None = None,
    description: str | None = None,
    output_example: Any | None = None,
) -> Callable:
    """装饰器：注册一个 Python 函数为 axi 工具。

    用法：
        @tool(name="query_orders", description="按区域查询订单")
        def query_orders(region: str, limit: int = 10) -> dict:
            ...

    也可以作为函数调用获取 PTC 可调用对象：
        query = tool("query_orders")
        result = query(region="cn")
    """
    # 当作为 PTC 调用时：tool("tool_name") 返回可调用对象
    if name is not None and description is None and output_example is None:
        # 先查本地原生工具
        registry = get_registry()
        meta = registry.get(name)
        if meta is not None:
            executor = get_executor()

            def _native_caller(**kwargs: Any) -> Any:
                result = executor.run(name, kwargs)  # type: ignore[arg-type]
                if result.status == "error":
                    raise RuntimeError(result.error)
                return result.data

            return _native_caller

        # 再查 daemon（MCP 工具）
        return _make_daemon_caller(name)

    # 当作为装饰器时
    def decorator(func: Callable) -> Callable:
        meta = register_tool(
            func,
            name=name,
            description=description,
            output_example=output_example,
        )
        get_registry().register(meta)
        return func

    return decorator


def _make_daemon_caller(tool_name: str) -> Callable:
    """创建通过 daemon 调用 MCP 工具的 PTC 函数。"""
    from axi.daemon.client import ensure_daemon, send_request
    from axi.daemon.protocol import DaemonRequest

    def _daemon_caller(**kwargs: Any) -> Any:
        if not ensure_daemon():
            raise RuntimeError("Daemon is not running. Start it with: axi daemon start")

        resp = send_request(
            DaemonRequest(method="call_tool", tool_name=tool_name, params=kwargs)
        )
        if resp.status == "error":
            raise RuntimeError(resp.error)
        return resp.data

    return _daemon_caller
