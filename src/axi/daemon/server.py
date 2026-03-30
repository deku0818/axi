"""axi daemon 服务端：维持 MCP 连接，通过 Unix socket 接受请求。"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from axi.daemon.protocol import (
    SOCKET_DIR,
    SOCKET_PATH,
    PID_PATH,
    DaemonRequest,
    DaemonResponse,
)
from axi.models import ToolSource
from axi.providers.mcp import MCPProvider
from axi.registry import Registry, ToolResolveError

logger = logging.getLogger(__name__)


class DaemonServer:
    """axi daemon 主体。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.registry = Registry()
        self.mcp_provider = MCPProvider()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """启动 daemon：连接 MCP server，监听 Unix socket。"""
        # 加载并连接 MCP servers
        configs = self.mcp_provider.load_config(self.config_path)
        if configs:
            tools = await self.mcp_provider.connect_all(configs)
            for tool_meta in tools:
                self.registry.register(tool_meta)
            logger.info(
                "Loaded %d tools from %d MCP server(s)", len(tools), len(configs)
            )

        # 确保 socket 目录存在
        os.makedirs(SOCKET_DIR, exist_ok=True)

        # 清理旧 socket
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        # 写 PID 文件
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))

        # 启动 Unix socket server
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=SOCKET_PATH
        )

        logger.info("Daemon listening on %s", SOCKET_PATH)

        # 注册信号处理
        loop = asyncio.get_event_loop()

        def _request_stop() -> None:
            asyncio.create_task(self.stop())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _request_stop)

        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """停止 daemon。"""
        logger.info("Shutting down daemon...")
        await self.mcp_provider.close_all()

        if self._server:
            self._server.close()

        # 清理文件
        for path in (SOCKET_PATH, PID_PATH):
            if os.path.exists(path):
                os.unlink(path)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """处理单个客户端连接。"""
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    req = DaemonRequest.model_validate_json(line)
                    resp = await self._dispatch(req)
                except Exception as e:
                    resp = DaemonResponse.fail(f"{type(e).__name__}: {e}")

                writer.write(resp.model_dump_json().encode() + b"\n")
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            logger.debug("Client connection dropped")
        finally:
            writer.close()

    async def _dispatch(self, req: DaemonRequest) -> DaemonResponse:
        """路由请求到对应处理方法。"""
        handler = self._HANDLERS.get(req.method)
        if handler is None:
            return DaemonResponse.fail(f"Unknown method: {req.method}")
        return await handler(self, req)

    async def _handle_list_tools(self, req: DaemonRequest) -> DaemonResponse:
        tools = self.registry.list_all()
        return DaemonResponse.success([t.model_dump(exclude_none=True) for t in tools])

    async def _handle_search(self, req: DaemonRequest) -> DaemonResponse:
        results = self.registry.search(
            req.query or "", regex=req.regex, top_k=req.top_k
        )
        return DaemonResponse.success(
            [r.model_dump(exclude_none=True) for r in results]
        )

    async def _handle_describe(self, req: DaemonRequest) -> DaemonResponse:
        if not req.tool_name:
            return DaemonResponse.fail("tool_name required")
        try:
            meta = self.registry.resolve(req.tool_name)
        except ToolResolveError as e:
            return DaemonResponse.fail(str(e))
        return DaemonResponse.success(meta.model_dump(exclude_none=True))

    async def _handle_call_tool(self, req: DaemonRequest) -> DaemonResponse:
        if not req.tool_name:
            return DaemonResponse.fail("tool_name required")
        try:
            meta = self.registry.resolve(req.tool_name)
        except ToolResolveError as e:
            return DaemonResponse.fail(str(e))

        if meta.source != ToolSource.MCP:
            return DaemonResponse.fail(
                "Native tools should be executed locally, not via daemon"
            )
        if not meta.server:
            return DaemonResponse.fail("MCP tool missing server")

        result = await self.mcp_provider.call_tool(
            meta.server, meta.name, req.params or {}
        )
        if result.status == "success":
            return DaemonResponse.success(result.data)
        return DaemonResponse.fail(result.error or "Unknown error")

    async def _handle_shutdown(self, req: DaemonRequest) -> DaemonResponse:
        asyncio.create_task(self.stop())
        return DaemonResponse.success("Daemon shutting down")

    _HANDLERS = {
        "list_tools": _handle_list_tools,
        "search": _handle_search,
        "describe": _handle_describe,
        "call_tool": _handle_call_tool,
        "shutdown": _handle_shutdown,
    }


def run_daemon(config_path: str = "axi.json") -> None:
    """启动 daemon 进程。"""
    axi_logger = logging.getLogger("axi")
    axi_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    axi_logger.addHandler(handler)
    server = DaemonServer(Path(config_path))
    asyncio.run(server.start())


if __name__ == "__main__":
    config = sys.argv[1] if len(sys.argv) > 1 else "axi.json"
    run_daemon(config)
