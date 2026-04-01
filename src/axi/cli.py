"""axi CLI 入口：Typer app。"""

import json
import logging
from collections import Counter

import typer
from pydantic import BaseModel

from axi.config import app_config
from axi.daemon.client import ensure_daemon, is_daemon_running, send_request
from axi.daemon.protocol import DaemonRequest, DaemonResponse
from axi.executor import Executor
from axi.models import RunResult, SearchResult
from axi.registry import AmbiguousToolError, Registry, ToolNotFoundError

logger = logging.getLogger(__name__)

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
    from axi.providers.mcp import load_native_tool_modules

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


def _daemon_request(req: DaemonRequest) -> DaemonResponse:
    """向 daemon 发送请求。如果 daemon 未运行则自动启动。"""
    if not ensure_daemon():
        return DaemonResponse.fail(
            "Daemon is not running. Start it with: axi daemon start"
        )
    return send_request(req)


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
        typer.echo("Failed to start daemon.")
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

    data = resp.data
    # 原生工具按 server 统计
    native_server_tools = dict(
        Counter(meta.server or "unknown" for meta in _registry.list_all())
    )

    result = {
        "status": "running",
        **data,
        "native_tools": native_server_tools,
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
    resp = _daemon_request(
        DaemonRequest(method=daemon_method, query=query, top_k=top_k)
    )
    if resp.status == "success" and resp.data:
        mcp_results = resp.data
    elif resp.status == "error":
        logger.warning("Daemon search failed: %s", resp.error)

    combined = [r.model_dump(exclude_none=True) for r in local_results] + (
        mcp_results or []
    )
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
    resp = _daemon_request(DaemonRequest(method="list_tools"))
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
    names = [n.strip() for n in server_name.split(",") if n.strip()]
    filtered = {k: v for k, v in groups.items() if k in names}
    if not filtered:
        missing = [n for n in names if n not in groups]
        _output_json({"error": f"Server not found: {', '.join(missing)}"})
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

    resp = _daemon_request(DaemonRequest(method="describe", tool_name=name))
    if resp.status == "success":
        return resp.data
    return {"error": resp.error or f"Tool not found: {name}"}


@app.command()
def describe(
    tool_name: str = typer.Argument(help="工具完整名称（逗号分隔多个）"),
) -> None:
    """查看工具详情。"""
    names = [n.strip() for n in tool_name.split(",") if n.strip()]
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

    if json_str:
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            _output_json(RunResult.fail(f"Invalid JSON argument: {e}"))
            raise typer.Exit(code=1)
    else:
        parsed = _parse_params(args)

    try:
        meta = _registry.resolve(tool_name)
        result = _executor.run(meta.full_name, parsed)
        _output_json(result)
        return
    except AmbiguousToolError as e:
        _output_json({"error": str(e)})
        raise typer.Exit(code=1)
    except ToolNotFoundError:
        pass  # 本地未找到，继续尝试 daemon

    resp = _daemon_request(
        DaemonRequest(method="call_tool", tool_name=tool_name, params=parsed)
    )
    if resp.status == "success":
        _output_json(RunResult.success(resp.data))
    else:
        _output_json(RunResult.fail(resp.error or "Unknown error"))


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


def _parse_params(params: list[str]) -> dict:
    parsed: dict = {}
    i = 0
    while i < len(params):
        arg = params[i]
        if arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(params) and not params[i + 1].startswith("--"):
                value = params[i + 1]
                try:
                    parsed[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    parsed[key] = value
                i += 2
            else:
                parsed[key] = True
                i += 1
        else:
            logger.warning("Ignoring unrecognized argument: %s", arg)
            i += 1
    return parsed
