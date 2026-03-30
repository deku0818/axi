"""MCP Provider：读取 axi.json，连接 MCP server，注册工具。"""

import asyncio
import importlib.util
import json
import logging
import os
import threading
import traceback
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field, model_validator

from axi.models import RunResult, ToolMeta, ToolSource

logger = logging.getLogger(__name__)

# 配置文件默认路径
DEFAULT_CONFIG_PATH = Path("axi.json")


def load_axi_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """读取并解析 axi.json，返回原始 dict。找不到文件则返回空 dict。"""
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Malformed config file %s: %s", config_path, e)
            return {}


class MCPServerConfig(BaseModel):
    """单个 MCP server 的配置。"""

    server: str = Field(min_length=1)
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    url: str | None = None

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

    def load_config(
        self, config_path: Path = DEFAULT_CONFIG_PATH
    ) -> list[MCPServerConfig]:
        """读取 axi.json 中的 mcpServers 配置。"""
        raw = load_axi_config(config_path)
        mcp_servers = raw.get("mcpServers", {})

        configs = []
        for server_name, server_dict in mcp_servers.items():
            configs.append(
                MCPServerConfig.model_validate({"server": server_name, **server_dict})
            )
        return configs

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
            except Exception as e:
                # 连接失败不阻塞其他 server
                logger.error(
                    "Failed to connect to MCP server '%s': %s\n%s",
                    config.server,
                    e,
                    traceback.format_exc(),
                )

        return all_tools

    async def call_tool(
        self, server: str, tool_name: str, params: dict[str, Any]
    ) -> RunResult:
        """路由到对应 MCP server 执行工具。"""
        conn = self._connections.get(server)
        if not conn:
            return RunResult.fail(f"MCP server not connected: {server}")

        try:
            result = await conn.call_tool(tool_name, params)
            return RunResult.success(result)
        except Exception as e:
            logger.debug("MCP tool call error:\n%s", traceback.format_exc())
            return RunResult.fail(f"{type(e).__name__}: {e}")

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


def _parse_native_entry(entry: dict) -> tuple[str, str]:
    """解析 nativeTools 条目，返回 (module_or_path, server_name)。

    格式：{"module": "...", "name": "..."}
    - module: 模块路径或 .py 文件路径（必填）
    - name: server 名称（可选，默认从 module 推导）
    """
    module = entry["module"]
    name = entry.get("name")

    if name is None:
        if module.endswith(".py"):
            name = Path(module).stem
        else:
            name = module.rsplit(".", 1)[-1]

    return module, name


def load_native_tool_modules(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """从 axi.json 的 nativeTools 列表中加载模块，触发 @tool 注册。"""
    raw = load_axi_config(config_path)
    entries = raw.get("nativeTools", [])
    if not entries:
        return

    from axi.cli import get_registry

    registry = get_registry()

    for entry in entries:
        try:
            module, server_name = _parse_native_entry(entry)

            # 记录导入前已有的工具
            before = set(registry.list_names())

            if module.endswith(".py"):
                _import_from_file(module)
            else:
                importlib.import_module(module)

            # 为新增的工具设置 server
            new_names = [k for k in registry.list_names() if k not in before]
            for name in new_names:
                registry.set_server(name, server_name)

        except Exception as e:
            logger.error(
                "Failed to load native tool '%s': %s\n%s",
                entry,
                e,
                traceback.format_exc(),
            )


def load_mcp_tools_sync(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> tuple[MCPProvider, list[ToolMeta]]:
    """同步包装：加载配置并连接所有 MCP server。"""
    provider = MCPProvider()
    configs = provider.load_config(config_path)
    if not configs:
        return provider, []

    tools = run_async(provider.connect_all(configs))
    return provider, tools
