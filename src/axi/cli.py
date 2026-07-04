"""axi CLI 入口：Typer app。"""

import json
import logging
from enum import Enum

import typer
from pydantic import BaseModel

from axi.config import CONFIG_PATH, app_config
from axi.daemon.client import (
    LOG_PATH,
    daemon_request,
    ensure_daemon,
    is_daemon_running,
    send_request,
)
from axi.daemon.protocol import DaemonRequest
from axi.executor import Executor
from axi.models import RunResult, SearchResult, allowed_types
from axi.registry import (
    AmbiguousToolError,
    Registry,
    ToolNotFoundError,
    split_names,
)

logger = logging.getLogger(__name__)


class Transport(str, Enum):
    stdio = "stdio"
    http = "http"


app = typer.Typer(
    name="axi",
    help="Agent eXecution Interface - unified tool layer for AI Agents",
    no_args_is_help=True,
    rich_markup_mode="rich" if app_config.cli.rich else None,
)

daemon_app = typer.Typer(help="管理 axi daemon")
app.add_typer(daemon_app, name="daemon")

# 全局实例（原生工具用）
_registry = Registry()
_executor = Executor(_registry)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """CLI 启动时加载 axi.json 中配置的原生工具模块。"""
    from axi.providers.native import load_native_tool_modules

    load_native_tool_modules()
    if ctx.invoked_subcommand is None:
        raise typer.Exit()


def get_registry() -> Registry:
    return _registry


def get_executor() -> Executor:
    return _executor


def _output_json(data: object) -> None:
    """统一 JSON 输出。"""
    if isinstance(data, BaseModel):
        d = data.model_dump(exclude_none=True)
    elif isinstance(data, list):
        d = [
            item.model_dump(exclude_none=True) if isinstance(item, BaseModel) else item
            for item in data
        ]
    else:
        d = data
    typer.echo(json.dumps(d, ensure_ascii=False))


# ── daemon 管理命令 ──────────────────────────────────────────────


@daemon_app.command("start")
def daemon_start() -> None:
    """启动 daemon。"""
    if is_daemon_running():
        typer.echo("Daemon is already running.")
        return

    if ensure_daemon():
        typer.echo("Daemon started.")
    else:
        typer.echo(f"Failed to start daemon. Check log: {LOG_PATH}", err=True)
        raise typer.Exit(code=1)


@daemon_app.command("stop")
def daemon_stop() -> None:
    """停止 daemon。"""
    if not is_daemon_running():
        typer.echo("Daemon is not running.")
        return

    try:
        resp = send_request(DaemonRequest(method="shutdown"))
        if resp.status == "error":
            typer.echo(f"Failed to stop daemon: {resp.error}", err=True)
            raise typer.Exit(code=1)
    except OSError as e:
        typer.echo(f"Failed to connect to daemon: {e}", err=True)
        raise typer.Exit(code=1)
    typer.echo("Daemon stopped.")


@daemon_app.command("status")
def daemon_status() -> None:
    """查看 daemon 状态。"""
    if not is_daemon_running():
        _output_json({"status": "stopped"})
        return

    resp = send_request(DaemonRequest(method="status"))
    if resp.status == "error":
        _output_json({"status": "error", "error": resp.error})
        raise typer.Exit(code=1)

    result = {
        "status": "running",
        **resp.data,
        "native_tools": _registry.server_tool_counts(),
    }
    _output_json(result)


# ── 核心命令 ──────────────────────────────────────────────


def _search_and_merge(
    local_results: list[SearchResult],
    daemon_method: str,
    query: str,
    top_k: int,
) -> None:
    """执行 daemon 搜索，合并本地和远程结果后输出 JSON。"""
    mcp_results: list[dict] = []
    resp = daemon_request(DaemonRequest(method=daemon_method, query=query, top_k=top_k))
    if resp.status == "success" and resp.data:
        mcp_results = resp.data
    elif resp.status == "error":
        logger.warning("Daemon search failed: %s", resp.error)

    # native（本地 registry）与 MCP（daemon）是两套独立索引，分数不可比，
    # 无法跨源真正排序；各自已取回 top_k，直接并列拼接（本地在前）。
    combined = [r.model_dump() for r in local_results] + mcp_results
    typer.echo(json.dumps(combined, ensure_ascii=False))


@app.command()
def search(
    query: str = typer.Argument(help="搜索关键词"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="返回结果数量"),
) -> None:
    """混合搜索工具（BM25 + Embedding）。"""
    local_results = _registry.search(query, top_k=top_k)
    _search_and_merge(local_results, "search", query, top_k)


@app.command()
def grep(
    pattern: str = typer.Argument(help="正则表达式"),
    limit: int = typer.Option(10, "--limit", "-l", help="返回结果数量"),
) -> None:
    """正则表达式搜索工具。"""
    try:
        local_results = _registry.grep(pattern, top_k=limit)
    except ValueError as e:
        _output_json({"error": str(e)})
        raise typer.Exit(code=1)
    _search_and_merge(local_results, "grep", pattern, limit)


def _collect_tool_groups() -> dict[str | None, list[dict]]:
    """收集所有工具并按 server 分组。"""
    from axi.providers.mcp import MCPProvider

    groups: dict[str | None, list[dict]] = {}

    # 本地原生工具
    for meta in _registry.list_all():
        groups.setdefault(meta.server, []).append(
            {"name": meta.name, "description": meta.description}
        )

    # MCP 工具（通过 daemon）
    mcp_tools: list[dict] = []
    resp = daemon_request(DaemonRequest(method="list_tools"))
    if resp.status == "success" and resp.data:
        mcp_tools = resp.data
        for t in mcp_tools:
            groups.setdefault(t.get("server"), []).append(
                {"name": t["name"], "description": t.get("description", "")}
            )

    # daemon 未返回工具时，至少从配置列出 server
    if not mcp_tools:
        provider = MCPProvider()
        for cfg in provider.load_config():
            if cfg.server not in groups:
                groups[cfg.server] = []

    return groups


def _filter_groups(
    groups: dict[str | None, list[dict]], server_name: str
) -> dict[str, list[dict]]:
    """按逗号分隔的 server 名过滤分组。未找到时抛 typer.Exit。"""
    names = split_names(server_name)
    filtered = {k: v for k, v in groups.items() if k in names}
    if not filtered:
        missing = [n for n in names if n not in groups]
        available = ", ".join(sorted(k for k in groups if k))
        _output_json(
            {"error": f"Server not found: {', '.join(missing)}. Available: {available}"}
        )
        raise typer.Exit(code=1)
    return filtered


@app.command("list")
def list_tools(
    server_name: str | None = typer.Argument(
        None, help="只列出指定 server 的工具（逗号分隔多个）"
    ),
) -> None:
    """列出所有 server 及其工具。"""
    groups = _collect_tool_groups()

    if server_name is not None:
        filtered = _filter_groups(groups, server_name)
        if len(filtered) == 1:
            key = next(iter(filtered))
            typer.echo(
                json.dumps({"server": key, "tools": filtered[key]}, ensure_ascii=False)
            )
        else:
            typer.echo(
                json.dumps(
                    [{"server": k, "tools": v} for k, v in filtered.items()],
                    ensure_ascii=False,
                )
            )
        return

    # 全部列出（只显示工具名）
    result = [
        {"server": key, "tools": [t["name"] for t in tools]}
        for key, tools in groups.items()
    ]
    typer.echo(json.dumps(result, ensure_ascii=False))


def _resolve_tool(name: str) -> dict:
    """解析单个工具，返回工具详情 dict 或 error dict。"""
    try:
        meta = _registry.resolve(name)
        return meta.model_dump(exclude_none=True)
    except AmbiguousToolError as e:
        return {"error": str(e)}
    except ToolNotFoundError:
        pass  # 本地未找到，继续尝试 daemon

    resp = daemon_request(DaemonRequest(method="describe", tool_name=name))
    if resp.status == "success":
        return resp.data
    return {"error": resp.error or f"Tool not found: {name}"}


def _daemon_input_schema(tool_name: str) -> dict:
    """从 daemon 取 MCP 工具的 input_schema；取不到返回 {}（解析退回 JSON 猜类型）。"""
    resp = daemon_request(DaemonRequest(method="describe", tool_name=tool_name))
    if resp.status == "success" and isinstance(resp.data, dict):
        return resp.data.get("input_schema") or {}
    return {}


@app.command()
def describe(
    tool_name: str = typer.Argument(help="工具完整名称（逗号分隔多个）"),
) -> None:
    """查看工具详情。"""
    names = split_names(tool_name)
    if len(names) == 1:
        result = _resolve_tool(names[0])
        if "error" in result:
            _output_json(result)
            raise typer.Exit(code=1)
        _output_json(result)
        return
    results = [_resolve_tool(n) for n in names]
    typer.echo(json.dumps(results, ensure_ascii=False))


@app.command(
    context_settings={"allow_extra_args": True, "allow_interspersed_args": False},
)
def run(
    ctx: typer.Context,
    tool_name: str = typer.Argument(help="工具完整名称"),
) -> None:
    """执行工具。参数支持 --key value 或 --json '{...}' 格式。"""
    args = ctx.args

    if "--help" in args or "-h" in args:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    json_str, args = _extract_option(args, "--json", "-j")

    # 先解析工具一次：本地命中 → 原生（进程内执行，schema 就在 meta 上）；
    # 未命中 → 走 daemon（MCP）。避免解析参数和执行各 resolve 一遍。
    try:
        meta = _registry.resolve(tool_name)
    except AmbiguousToolError as e:
        _output_json({"error": str(e)})
        raise typer.Exit(code=1)
    except ToolNotFoundError:
        meta = None

    if json_str:
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            _output_json(RunResult.fail(f"Invalid JSON argument: {e}"))
            raise typer.Exit(code=1)
    elif not args:
        parsed = {}
    else:
        # 按目标 schema 解析 --key value（string 字段保留原文）；MCP schema 问 daemon
        schema = meta.input_schema if meta else _daemon_input_schema(tool_name)
        parsed = _parse_params(args, schema)

    if meta is not None:
        _output_json(_executor.run(meta.full_name, parsed))
        return

    resp = daemon_request(
        DaemonRequest(method="call_tool", tool_name=tool_name, params=parsed)
    )
    if resp.status == "success":
        _output_json(RunResult.success(resp.data))
    else:
        _output_json(RunResult.fail(resp.error or "Unknown error"))


@app.command("mcp")
def mcp_command(
    transport: Transport = typer.Option(
        Transport.stdio, "--transport", help="传输方式"
    ),
    server: str | None = typer.Option(
        None, "--server", help="只暴露指定 server 的工具（逗号分隔多个）"
    ),
    flat: bool | None = typer.Option(
        None,
        "--flat/--meta",
        help="平铺每个工具 / 只暴露 search、grep、describe、run 元工具；"
        "缺省自动：指定了 --server 则平铺，否则元工具",
    ),
    port: int = typer.Option(8321, "--port", help="HTTP 端口"),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP 监听地址"),
) -> None:
    """将 axi 工具导出为 MCP server。"""
    from axi import mcp_serve

    if flat is None:
        flat = server is not None
    mcp_serve.serve(
        native_metas=_registry.list_all(),
        transport=transport.value,
        servers=server,
        flat=flat,
        host=host,
        port=port,
    )


@app.command()
def doctor() -> None:
    """自检：配置、daemon、MCP 连接、embedding、native 工具来源。

    有问题时以非零码退出并在 ``issues`` 里给出可执行的下一步。
    配置了 MCP server 时会拉起 daemon 以验证连接。
    """
    import importlib.metadata

    from axi.providers.native import NATIVE_TOOLS_ENTRY_POINT_GROUP

    issues: list[str] = []

    # native 工具及其来源（entry_points 自动发现 = 任何已装包都可能注入工具，需可见）
    try:
        eps = list(
            importlib.metadata.entry_points(group=NATIVE_TOOLS_ENTRY_POINT_GROUP)
        )
    except Exception:
        eps = []
    server_counts = _registry.server_tool_counts()
    native = {
        "total": sum(server_counts.values()),
        "servers": server_counts,
        "from_config": [e.module for e in app_config.native_tools],
        "from_entry_points": [{"name": ep.name, "value": ep.value} for ep in eps],
    }

    # embedding
    emb = app_config.search.embedding
    if emb.provider:
        embedding = {
            "provider": emb.provider,
            "api_key": "present" if emb.api_key else "missing",
            "model": emb.model,
        }
        if not emb.api_key:
            env_name = "JINA_API_KEY" if emb.provider == "jina" else "OPENAI_API_KEY"
            issues.append(
                f"Embedding provider '{emb.provider}' set but no API key. Put it in "
                f"axi.json search.embedding.apiKey or the {env_name} env var."
            )
    else:
        embedding = {"provider": None, "note": "BM25-only, no semantic search"}

    # daemon + MCP 连接（仅在配置了 MCP server 时拉起 daemon 验证）
    configured = set(app_config.mcp_servers)
    mcp_servers: list[dict] = []
    if configured:
        resp = daemon_request(DaemonRequest(method="status"))
        if resp.status == "success":
            connected = resp.data.get("server_tools", {})
            daemon = {
                "running": True,
                "pid": resp.data.get("pid"),
                "uptime_seconds": resp.data.get("uptime_seconds"),
            }
            for name in sorted(configured):
                if name in connected:
                    mcp_servers.append(
                        {
                            "server": name,
                            "status": "connected",
                            "tools": connected[name],
                        }
                    )
                else:
                    mcp_servers.append({"server": name, "status": "not_connected"})
                    issues.append(
                        f"MCP server '{name}' configured but not connected. "
                        f"Check daemon log: {LOG_PATH}"
                    )
        else:
            daemon = {"running": False, "error": resp.error}
            issues.append(f"Daemon unavailable: {resp.error}. Check log: {LOG_PATH}")
    else:
        daemon = {"running": is_daemon_running()}

    report = {
        "ok": not issues,
        "config": {"path": str(CONFIG_PATH), "exists": CONFIG_PATH.exists()},
        "daemon": daemon,
        "native_tools": native,
        "mcp_servers": mcp_servers,
        "embedding": embedding,
        "issues": issues,
    }
    _output_json(report)
    if issues:
        raise typer.Exit(code=1)


# ── 参数解析辅助函数 ──────────────────────────────────────────────


def _extract_option(args: list[str], *names: str) -> tuple[str | None, list[str]]:
    remaining = []
    value = None
    i = 0
    while i < len(args):
        if args[i] in names and i + 1 < len(args):
            value = args[i + 1]
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return value, remaining


def _schema_field_types(schema: dict, key: str) -> set[str]:
    """取字段在 schema 里声明的类型集合；字段不存在或无 schema 返回空集。"""
    props = schema.get("properties")
    if not isinstance(props, dict):
        return set()
    prop = props.get(key)
    return allowed_types(prop) if isinstance(prop, dict) else set()


def _coerce_cli_value(key: str, value: str, schema: dict) -> object:
    """按目标字段类型决定是否 JSON 解析。

    字段声明为 string → 原样保留，避免 ``true``/``42``/``null`` 被解析成
    非字符串类型（``--title false`` 应是字符串 "false"）。其余（含未知字段、
    无 schema）尝试 JSON 解析，让 ``--count 42``→42、``--flag true``→True、
    ``--data {...}``→dict 正常工作，失败落回原字符串。
    """
    if "string" in _schema_field_types(schema, key):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _parse_params(params: list[str], schema: dict | None = None) -> dict:
    schema = schema or {}
    parsed: dict = {}
    i = 0
    while i < len(params):
        arg = params[i]
        if arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(params) and not params[i + 1].startswith("--"):
                parsed[key] = _coerce_cli_value(key, params[i + 1], schema)
                i += 2
            else:
                parsed[key] = True
                i += 1
        else:
            logger.warning("Ignoring unrecognized argument: %s", arg)
            i += 1
    return parsed
