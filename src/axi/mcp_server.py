"""以 MCP Server 模式对外暴露 axi 的所有工具。

axi 平时是 MCP Client（通过 daemon 连接外部 MCP server）；本模块反过来，
把 axi 注册的所有工具（原生 + 经 daemon 代理的 MCP 工具）打包成一个 FastMCP
实例，供 Claude Desktop / Cursor 等 MCP Client 连接。

- 原生工具：包装 Executor.run() 的调用（跑在线程里，避免嵌套 event loop）
- MCP 工具：转发为向 daemon 发 call_tool 请求（代理）

工具已有现成的 JSON Schema（ToolMeta.input_schema），因此直接构造 FastMCP 的
Tool 对象，用 passthrough 参数模型透传入参，绕过从函数签名反推 schema 的环节。
"""

import asyncio
import logging
from typing import Any, Callable

from pydantic import ConfigDict
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.tools.base import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata

from axi.daemon.client import ensure_daemon, send_request
from axi.daemon.protocol import DaemonRequest
from axi.executor import Executor
from axi.models import ToolMeta, ToolSource
from axi.registry import Registry

logger = logging.getLogger(__name__)

# MCP tool name 不允许 '/'，用 '__' 替代 full_name 中的 server 分隔符
_NAME_SEP = "__"


class _PassthroughArgs(ArgModelBase):
    """透传参数模型：接受任意入参并原样交给包装函数。

    工具的 JSON Schema 已知，无需再从签名反推，也无需重建每个字段的类型；
    MCP 协议下发的入参已是结构化 JSON，直接透传即可。
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def model_dump_one_level(self) -> dict[str, Any]:
        return dict(self)


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """确保 input_schema 是合法的 object 类型 JSON Schema。"""
    if schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {}}


def _make_tool(
    mcp_name: str, description: str, schema: dict[str, Any], fn: Callable
) -> Tool:
    """用现成的 JSON Schema 直接构造 FastMCP Tool，绕过签名推断。"""
    return Tool(
        fn=fn,
        name=mcp_name,
        title=None,
        description=description,
        parameters=_normalize_schema(schema),
        fn_metadata=FuncMetadata(arg_model=_PassthroughArgs),
        is_async=True,
        context_kwarg=None,
    )


def _native_tool(meta: ToolMeta, executor: Executor) -> Tool:
    """把原生工具包装成 Tool，调用时走 Executor.run()。"""
    full_name = meta.full_name

    async def call(**kwargs: Any) -> Any:
        # Executor.run 是同步的（内部可能对 async 工具 asyncio.run），
        # 放到线程里执行，避免与当前 event loop 冲突。
        result = await asyncio.to_thread(executor.run, full_name, kwargs)
        if result.status == "success":
            return result.data
        raise ToolError(result.error or "Unknown error")

    return _make_tool(
        full_name.replace("/", _NAME_SEP), meta.description, meta.input_schema, call
    )


def _mcp_proxy_tool(meta: ToolMeta) -> Tool:
    """把 MCP 工具包装成 Tool，调用时转发给 daemon（call_tool）。"""
    full_name = meta.full_name

    async def call(**kwargs: Any) -> Any:
        req = DaemonRequest(method="call_tool", tool_name=full_name, params=kwargs)
        resp = await asyncio.to_thread(send_request, req)
        if resp.status == "success":
            return resp.data
        raise ToolError(resp.error or "Unknown error")

    return _make_tool(
        full_name.replace("/", _NAME_SEP), meta.description, meta.input_schema, call
    )


def _daemon_mcp_tools() -> list[ToolMeta]:
    """通过 daemon 拉取 MCP 工具列表。daemon 不可用时返回空列表。"""
    if not ensure_daemon():
        logger.warning("Daemon not available; MCP proxy tools will be unavailable")
        return []
    resp = send_request(DaemonRequest(method="list_tools"))
    if resp.status != "success" or not resp.data:
        return []
    tools = []
    for item in resp.data:
        meta = ToolMeta.model_validate(item)
        if meta.source == ToolSource.MCP:
            tools.append(meta)
    return tools


def build_mcp_server(host: str = "127.0.0.1", port: int = 8080) -> FastMCP:
    """构建暴露 axi 所有工具的 FastMCP 实例。"""
    from axi.cli import get_executor, get_registry
    from axi.providers.native import load_native_tool_modules

    load_native_tool_modules()
    registry: Registry = get_registry()
    executor: Executor = get_executor()

    tools: list[Tool] = [
        _native_tool(meta, executor)
        for meta in registry.list_all()
        if meta.source == ToolSource.NATIVE
    ]
    tools.extend(_mcp_proxy_tool(meta) for meta in _daemon_mcp_tools())

    return FastMCP("axi", host=host, port=port, tools=tools)
