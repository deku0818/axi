"""将 axi 工具导出为 MCP server（stdio / streamable HTTP）。

两种暴露形态（互斥）：
- flat（平铺）：registry 中每个工具注册为独立 MCP tool，对端直接调用
- meta（元工具）：只暴露 search / grep / describe / run 四个固定工具，
  对端以渐进式披露的方式发现和调用，上下文占用恒定
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

from axi.config import app_config
from axi.context import set_request_env
from axi.daemon.client import daemon_request
from axi.daemon.protocol import LOG_PATH, DaemonRequest
from axi.executor import Executor
from axi.models import RunResult, ToolMeta, ToolSource
from axi.registry import Registry, ToolResolveError, split_names

logger = logging.getLogger(__name__)

_META_INSTRUCTIONS = (
    "axi exposes a searchable tool registry. Workflow: "
    "1) search(query) or grep(pattern) to discover tools; "
    "2) describe(name) to inspect the input schema; "
    "3) run(name, params) to execute. "
    "Results of run are wrapped as {status, data, error}."
)


# ── Registry 构建 ─────────────────────────────────────────────


def build_registry(
    native_metas: list[ToolMeta], servers: str | None, flat: bool = False
) -> Registry:
    """构建 serve 进程的合并 Registry：native 工具 + daemon 的 MCP 工具。

    ``servers`` 为逗号分隔的 server 名，指定时只保留这些组；
    名字不存在时报错退出并列出可用 server。
    只选中 native 组时不启动 daemon；平铺模式不用搜索，不建 embedding。
    """
    names = split_names(servers) if servers else None
    metas = list(native_metas)

    need_mcp = app_config.mcp_servers and (
        names is None or any(n in app_config.mcp_servers for n in names)
    )
    if need_mcp:
        resp = daemon_request(DaemonRequest(method="list_tools"))
        if resp.status == "success":
            metas += [ToolMeta.model_validate(t) for t in resp.data or []]
        else:
            logger.warning("MCP tools unavailable: %s", resp.error)

    if names:
        available = sorted({m.server for m in metas if m.server})
        missing = [n for n in names if n not in available]
        # 区分"配置了但没连上"和"根本不存在"，避免把 daemon 故障误报成配置错误
        unavailable = [n for n in missing if n in app_config.mcp_servers]
        if unavailable:
            raise SystemExit(
                f"Error: MCP server configured but not connected: "
                f"{', '.join(unavailable)}. Check daemon log: {LOG_PATH}"
            )
        if missing:
            raise SystemExit(
                f"Error: server not found: {', '.join(missing)}. "
                f"Available: {', '.join(available)}"
            )
        metas = [m for m in metas if m.server in names]

    registry = Registry() if flat else Registry.from_search_config(app_config.search)
    for m in metas:
        registry.register(m)
    return registry


# ── 执行分发 ─────────────────────────────────────────────────


async def _execute(
    server: Server,
    registry: Registry,
    executor: Executor,
    name: str,
    params: dict[str, Any],
) -> RunResult:
    """按来源分发执行：native 进程内，MCP 转发 daemon。

    native 执行前把当前 HTTP 请求的 Axi-* header 写入请求级变量
    （stdio 无请求对象，置空）；MCP 工具在 daemon 进程执行，读不到
    contextvar，不捕获。

    Executor.run 与 send_request 内部都会 asyncio.run，
    必须放到 worker 线程执行以避免嵌套事件循环。
    """
    try:
        meta = registry.resolve(name)
    except ToolResolveError as e:
        return RunResult.fail(str(e))

    if meta.source == ToolSource.NATIVE:
        request = server.request_context.request
        set_request_env(request.headers if request else None)
        return await asyncio.to_thread(executor.run, meta.full_name, params)

    # daemon_request 内含 ensure_daemon：daemon idle 自杀后长驻 serve 进程可自动重启它
    resp = await asyncio.to_thread(
        daemon_request,
        DaemonRequest(method="call_tool", tool_name=meta.full_name, params=params),
    )
    if resp.status == "success":
        return RunResult.success(resp.data)
    return RunResult.fail(resp.error or "Unknown error")


def _text(data: Any) -> list[types.TextContent]:
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False, default=str)
    return [types.TextContent(type="text", text=data)]


# ── flat 模式 ────────────────────────────────────────────────


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def flat_name_map(metas: list[ToolMeta]) -> dict[str, str]:
    """MCP 工具名 → full_name。单 server 用裸名，多 server 加 ``server__`` 前缀。

    清洗后同名的工具按注册顺序追加 ``_2``/``_3`` 后缀，避免静默覆盖。
    """
    single = len({m.server for m in metas}) == 1
    mapping: dict[str, str] = {}
    for m in metas:
        base = _sanitize(m.name if single else f"{m.server}__{m.name}")
        name, i = base, 2
        while name in mapping:
            name, i = f"{base}_{i}", i + 1
        mapping[name] = m.full_name
    return mapping


def _tool_description(meta: ToolMeta) -> str:
    if meta.output_example is None:
        return meta.description
    example = json.dumps(meta.output_example, ensure_ascii=False, default=str)
    return f"{meta.description}\n\nOutput example: {example}"


def _build_flat_server(registry: Registry, executor: Executor) -> Server:
    server = Server("axi")
    name_map = flat_name_map(registry.list_all())
    # registry 在 serve 期间不可变，工具列表一次性预构建
    tools = []
    for mcp_name, full_name in name_map.items():
        meta = registry.get(full_name)
        tools.append(
            types.Tool(
                name=mcp_name,
                description=_tool_description(meta),
                inputSchema=meta.input_schema or {"type": "object"},
            )
        )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        logger.info("call_tool %s", name)
        full_name = name_map.get(name)
        if full_name is None:
            raise ValueError(
                f"Unknown tool: {name}. Call tools/list to see the available tools."
            )
        result = await _execute(server, registry, executor, full_name, arguments)
        if result.status == "error":
            raise RuntimeError(result.error)
        return _text(result.data)

    return server


# ── meta 模式 ────────────────────────────────────────────────

_META_TOOLS = [
    types.Tool(
        name="search",
        description="Hybrid search (BM25 + embedding) over available tools. "
        "Use natural language describing the capability you need.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="grep",
        description="Regex search over tool names and descriptions. "
        "Use when you know a fragment of the tool or server name.",
        inputSchema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["pattern"],
        },
    ),
    types.Tool(
        name="describe",
        description="Show a tool's full metadata including input schema. "
        "Accepts comma-separated names for batch lookup.",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    ),
    types.Tool(
        name="run",
        description="Execute a tool by name with a params object. "
        "Returns {status, data, error}.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["name"],
        },
    ),
]


def _describe_one(registry: Registry, name: str) -> dict[str, Any]:
    try:
        return registry.resolve(name).model_dump(exclude_none=True)
    except ToolResolveError as e:
        return {"error": str(e)}


def _build_meta_server(registry: Registry, executor: Executor) -> Server:
    server = Server("axi", instructions=_META_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _META_TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        logger.info("call_tool %s", name)
        if name == "search":
            results = await asyncio.to_thread(
                registry.search, arguments["query"], arguments.get("top_k", 5)
            )
            return _text([r.model_dump(exclude_none=True) for r in results])
        if name == "grep":
            results = await asyncio.to_thread(
                registry.grep, arguments["pattern"], arguments.get("limit", 10)
            )
            return _text([r.model_dump(exclude_none=True) for r in results])
        if name == "describe":
            names = split_names(arguments["name"])
            out = [_describe_one(registry, n) for n in names]
            return _text(out[0] if len(out) == 1 else out)
        if name == "run":
            result = await _execute(
                server,
                registry,
                executor,
                arguments["name"],
                arguments.get("params") or {},
            )
            return _text(result.model_dump(exclude_none=True))
        raise ValueError(
            f"Unknown tool: {name}. Available: search, grep, describe, run."
        )

    return server


# ── transport 与入口 ─────────────────────────────────────────


async def _run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def _setup_http_logging() -> None:
    """HTTP 模式把 axi 与 mcp 的日志打到 stderr（INFO），让连接/请求可见。

    只在 HTTP 模式调用：stdio 的 stdout 是协议通道不能污染，而未配置 handler 时
    Python 的 lastResort 只在 WARNING 以上输出，故 stdio/cli 的 info 日志天然静默。
    uvicorn 自身的 access log 由 Config(log_level="info") 负责，这里补齐 axi/mcp。
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


async def _run_http(server: Server, host: str, port: int) -> None:
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    manager = StreamableHTTPSessionManager(app=server)
    app = Starlette(
        routes=[Mount("/mcp", app=manager.handle_request)],
        lifespan=lambda app: manager.run(),
    )
    logger.info("axi MCP server listening on http://%s:%d/mcp", host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    await uvicorn.Server(config).serve()


def serve(
    native_metas: list[ToolMeta],
    transport: str,
    servers: str | None,
    flat: bool,
    host: str,
    port: int,
) -> None:
    """构建合并 Registry 并运行 MCP server，阻塞直到进程退出。

    stdio 模式下 stdout 是协议通道，日志只能走 stderr。
    """
    registry = build_registry(native_metas, servers, flat)
    if not registry.list_all():
        raise SystemExit(
            "Error: no tools to serve. Configure mcpServers or nativeTools "
            "in the axi.json pointed to by AXI_CONFIG."
        )

    executor = Executor(registry)
    if flat:
        server = _build_flat_server(registry, executor)
    else:
        server = _build_meta_server(registry, executor)

    if transport == "http":
        _setup_http_logging()
        asyncio.run(_run_http(server, host, port))
    else:
        asyncio.run(_run_stdio(server))
