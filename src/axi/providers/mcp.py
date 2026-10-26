"""MCP Provider：读取 axi.json，连接 MCP server，注册工具。"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack, suppress
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import (
    create_mcp_http_client,
    streamable_http_client,
)
from mcp.types import PaginatedRequestParams
from pydantic import Field, model_validator

from axi.config import MCPServerConfig as MCPServerBaseConfig, app_config
from axi.models import RunResult, ToolMeta, ToolSource

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    """MCP server 返回的工具级错误（is_error=true）。

    区别于连接层异常：工具级错误不应触发重连重试。
    """


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
        self._task: asyncio.Task[None] | None = None
        self.reconnect_lock = asyncio.Lock()

    async def connect(self) -> None:
        """由固定任务持有连接上下文；请求任务只使用 session。"""
        ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run_session(ready))
        try:
            await ready
        except BaseException:
            await self.close()
            raise

    async def _run_session(self, ready: asyncio.Future[None]) -> None:
        try:
            async with AsyncExitStack() as stack:
                if self.config.url:
                    http_client = await stack.enter_async_context(
                        create_mcp_http_client(headers=self.config.headers)
                    )
                    read_stream, write_stream = await stack.enter_async_context(
                        streamable_http_client(self.config.url, http_client=http_client)
                    )
                else:
                    server_params = StdioServerParameters(
                        command=self.config.command,
                        args=self.config.args,
                        env=self.config.env,
                    )
                    devnull = stack.enter_context(open(os.devnull, "w"))
                    read_stream, write_stream = await stack.enter_async_context(
                        stdio_client(server_params, errlog=devnull)
                    )
                session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await session.initialize()
                self.session = session
                ready.set_result(None)
                await asyncio.Event().wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e)
            elif not isinstance(e, asyncio.CancelledError):
                logger.exception(
                    "MCP session '%s' closed unexpectedly", self.config.server
                )
        finally:
            self.session = None

    async def list_tools(self) -> list[ToolMeta]:
        """获取该 server 的所有工具。"""
        if not self.session:
            raise RuntimeError("Not connected")

        tools = []
        cursor = None
        while True:
            response = await self.session.list_tools(
                params=PaginatedRequestParams(cursor=cursor)
                if cursor is not None
                else None
            )
            for t in response.tools:
                tools.append(
                    ToolMeta(
                        name=t.name,
                        server=self.config.server,
                        description=t.description or "",
                        input_schema=t.input_schema,
                        source=ToolSource.MCP,
                    )
                )
            cursor = response.next_cursor
            if cursor is None:
                break
        return tools

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """调用工具。server 返回 is_error 时抛 MCPToolError。"""
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

        if result.is_error:
            raise MCPToolError("\n".join(contents) or "Unknown tool error")

        if len(contents) == 1:
            # 尝试解析为 JSON
            try:
                return json.loads(contents[0])
            except (json.JSONDecodeError, ValueError):
                return contents[0]
        return contents

    async def close(self) -> None:
        """通知持有者退出，等待它在原任务中关闭全部上下文。"""
        task = self._task
        if task:
            if not task.cancelling():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if self._task is task:
                self._task = None


class MCPProvider:
    """MCP 工具提供者：管理所有 MCP server 连接。"""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._closing = False

    def load_config(self) -> list[MCPServerConfig]:
        """从全局配置中读取 mcpServers。"""
        return [
            MCPServerConfig(server=name, **cfg.model_dump())
            for name, cfg in app_config.mcp_servers.items()
        ]

    async def connect_all(self, configs: list[MCPServerConfig]) -> list[ToolMeta]:
        """连接所有 MCP server，返回所有工具元数据。"""
        self._closing = False
        all_tools: list[ToolMeta] = []

        for config in configs:
            conn = MCPConnection(config)
            try:
                await conn.connect()
                tools = await conn.list_tools()
                self._connections[config.server] = conn
                all_tools.extend(tools)
            except asyncio.CancelledError:
                # connect 已成功、list_tools 尚未返回时，连接还没交给 _connections。
                await conn.close()
                raise
            except Exception:
                await conn.close()
                # 连接失败不阻塞其他 server
                logger.exception("Failed to connect to MCP server '%s'", config.server)

        return all_tools

    async def call_tool(
        self, server: str, tool_name: str, params: dict[str, Any]
    ) -> RunResult:
        """路由到对应 MCP server 执行工具。失败时尝试重连一次。"""
        if self._closing:
            return RunResult.fail("MCP provider is shutting down.")
        conn = self._connections.get(server)
        if not conn:
            return RunResult.fail(
                f"MCP server not connected: {server}. "
                "It failed to start with the daemon; check daemon log for the cause."
            )

        async def _call() -> RunResult:
            """工具级错误（is_error）就地转 error 信封，不参与重连重试。"""
            try:
                return RunResult.success(await conn.call_tool(tool_name, params))
            except MCPToolError as e:
                return RunResult.fail(str(e))

        previous_session = conn.session
        try:
            return await _call()
        except Exception as e:
            if self._closing:
                return RunResult.fail("MCP provider is shutting down.")
            logger.warning(
                "Tool call '%s/%s' failed, attempting reconnect: %s",
                server,
                tool_name,
                e,
            )
            try:
                async with conn.reconnect_lock:
                    if self._closing:
                        return RunResult.fail("MCP provider is shutting down.")
                    if conn.session is None or conn.session is previous_session:
                        await conn.close()
                        await conn.connect()
                result = await _call()
                logger.info("Reconnect to '%s' succeeded", server)
                return result
            except Exception as retry_err:
                logger.exception("Reconnect to '%s' failed", server)
                return RunResult.fail(
                    f"Tool call failed and reconnect failed: {retry_err}"
                )

    async def close_all(self) -> None:
        """关闭所有连接。"""
        self._closing = True
        for conn in self._connections.values():
            async with conn.reconnect_lock:
                await conn.close()
        self._connections.clear()
