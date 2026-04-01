"""MCP Provider：读取 axi.json，连接 MCP server，注册工具。"""

import asyncio
import importlib.util
import json
import logging
import os
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import Field, model_validator

from axi.config import (
    MCPServerConfig as MCPServerBaseConfig,
    NativeToolEntry,
    app_config,
)
from axi.models import RunResult, ToolMeta, ToolSource

logger = logging.getLogger(__name__)


class MCPServerConfig(MCPServerBaseConfig):
    """运行时 MCP server 配置，增加 server 名称和 transport 校验。"""

    server: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_transport(self) -> Self:
        if not self.command and not self.url:
            raise ValueError(
                f"MCP server '{self.server}' must have either 'command' or 'url'"
            )
        return self


class MCPConnection:
    """与单个 MCP server 的连接。"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        """建立连接并初始化 session。"""
        self._exit_stack = AsyncExitStack()

        if self.config.url:
            read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
                streamable_http_client(self.config.url)
            )
        else:
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env,
            )
            devnull = self._exit_stack.enter_context(open(os.devnull, "w"))
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params, errlog=devnull)
            )
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()

    async def list_tools(self) -> list[ToolMeta]:
        """获取该 server 的所有工具。"""
        if not self.session:
            raise RuntimeError("Not connected")

        response = await self.session.list_tools()
        tools = []
        for t in response.tools:
            tools.append(
                ToolMeta(
                    name=t.name,
                    server=self.config.server,
                    description=t.description or "",
                    input_schema=t.inputSchema
                    if isinstance(t.inputSchema, dict)
                    else {},
                    source=ToolSource.MCP,
                )
            )
        return tools

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """调用工具。"""
        if not self.session:
            raise RuntimeError("Not connected")

        result = await self.session.call_tool(tool_name, params)
        # 提取 content 中的文本
        contents = []
        for block in result.content:
            if hasattr(block, "text"):
                contents.append(block.text)
            else:
                contents.append(str(block))

        if len(contents) == 1:
            # 尝试解析为 JSON
            try:
                return json.loads(contents[0])
            except (json.JSONDecodeError, ValueError):
                return contents[0]
        return contents

    async def close(self) -> None:
        """关闭连接。"""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self.session = None


class MCPProvider:
    """MCP 工具提供者：管理所有 MCP server 连接。"""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}

    def load_config(self) -> list[MCPServerConfig]:
        """从全局配置中读取 mcpServers。"""
        return [
            MCPServerConfig(server=name, **cfg.model_dump())
            for name, cfg in app_config.mcp_servers.items()
        ]

    async def connect_all(self, configs: list[MCPServerConfig]) -> list[ToolMeta]:
        """连接所有 MCP server，返回所有工具元数据。"""
        all_tools: list[ToolMeta] = []

        for config in configs:
            conn = MCPConnection(config)
            try:
                await conn.connect()
                tools = await conn.list_tools()
                self._connections[config.server] = conn
                all_tools.extend(tools)
            except Exception:
                # 连接失败不阻塞其他 server
                logger.exception("Failed to connect to MCP server '%s'", config.server)

        return all_tools

    async def call_tool(
        self, server: str, tool_name: str, params: dict[str, Any]
    ) -> RunResult:
        """路由到对应 MCP server 执行工具。失败时尝试重连一次。"""
        conn = self._connections.get(server)
        if not conn:
            return RunResult.fail(f"MCP server not connected: {server}")

        try:
            result = await conn.call_tool(tool_name, params)
            return RunResult.success(result)
        except Exception as e:
            logger.warning(
                "Tool call '%s/%s' failed, attempting reconnect: %s",
                server,
                tool_name,
                e,
            )
            try:
                await conn.close()
                await conn.connect()
                result = await conn.call_tool(tool_name, params)
                logger.info("Reconnect to '%s' succeeded", server)
                return RunResult.success(result)
            except Exception as retry_err:
                logger.exception("Reconnect to '%s' failed", server)
                return RunResult.fail(
                    f"Tool call failed and reconnect failed: {retry_err}"
                )

    async def close_all(self) -> None:
        """关闭所有连接。"""
        for name, conn in self._connections.items():
            try:
                await conn.close()
            except Exception as e:
                logger.warning("Error closing MCP connection '%s': %s", name, e)
        self._connections.clear()


_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """获取或创建一个持久的事件循环（在后台线程运行）。"""
    global _loop, _thread
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(_loop)
                _loop.run_forever()

            _thread = threading.Thread(target=_run, daemon=True)
            _thread.start()
    return _loop


def run_async(coro: Any) -> Any:
    """在持久事件循环上运行协程。"""

    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def _import_from_file(file_path: str) -> None:
    """通过文件路径 import 模块，触发 @tool 注册。"""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def _resolve_server_name(entry: NativeToolEntry) -> str:
    """推导 native tool 的 server 名称。"""
    if entry.name is not None:
        return entry.name
    if entry.module.endswith(".py"):
        return Path(entry.module).stem
    return entry.module.rsplit(".", 1)[-1]


def load_native_tool_modules() -> None:
    """从全局配置的 nativeTools 列表中加载模块，触发 @tool 注册。"""
    entries = app_config.native_tools
    if not entries:
        return

    from axi.cli import get_registry

    registry = get_registry()

    for entry in entries:
        try:
            server_name = _resolve_server_name(entry)

            # 记录导入前已有的工具
            before = set(registry.list_names())

            if entry.module.endswith(".py"):
                _import_from_file(entry.module)
            else:
                importlib.import_module(entry.module)

            # 为新增的工具设置 server
            new_names = [k for k in registry.list_names() if k not in before]
            for name in new_names:
                registry.set_server(name, server_name)

        except Exception:
            logger.exception("Failed to load native tool '%s'", entry)


def load_mcp_tools_sync() -> tuple[MCPProvider, list[ToolMeta]]:
    """同步包装：加载配置并连接所有 MCP server。"""
    provider = MCPProvider()
    configs = provider.load_config()
    if not configs:
        return provider, []

    tools = run_async(provider.connect_all(configs))
    return provider, tools
