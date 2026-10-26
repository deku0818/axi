"""axi — Agent eXecution Interface."""

import logging
from typing import Any, Callable

from axi import runtime
from axi.context import env
from axi.providers.native import ensure_native_tool_modules, register_tool

__all__ = ["tool", "env"]

# 包级 logger：各子模块通过 logging.getLogger(__name__) 自动继承
_logger = logging.getLogger("axi")
_logger.addHandler(logging.NullHandler())


def tool(
    tool_name: str | None = None,
    description: str | None = None,
    output_example: Any | None = None,
    *,
    name: str | None = None,
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
    if (
        tool_name is not None
        and name is None
        and description is None
        and output_example is None
    ):
        return _make_caller(tool_name)

    # 当作为装饰器时
    def decorator(func: Callable) -> Callable:
        meta = register_tool(
            func,
            name=name or tool_name,
            description=description,
            output_example=output_example,
        )
        runtime.registry.register(meta)
        return func

    return decorator


def _make_caller(tool_name: str) -> Callable:
    """在首次调用时发现原生工具，未找到时再交给 daemon。"""

    def caller(**kwargs: Any) -> Any:
        ensure_native_tool_modules()
        result = runtime.executor.run(tool_name, kwargs)
        if result.status == "error":
            raise RuntimeError(result.error)
        return result.data

    return caller
