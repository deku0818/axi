"""axi mcp 导出功能测试：命名规则、--server 过滤、stdio/http 端到端。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from axi.config import AxiConfig
from axi.mcp_serve import _tool_description, build_registry, flat_name_map
from axi.models import ToolMeta, ToolSource
from axi.providers.mcp import MCPConnection, MCPServerConfig

RUN_CLI = "from axi.cli import app; app()"

TOOLS_PY = """
from axi import tool

@tool(description="Add two integers")
def add_nums(a: int, b: int) -> int:
    return a + b

@tool(description="Greet a person by name")
def greet(name: str) -> str:
    return f"hi {name}"
"""


def _meta(name: str, server: str) -> ToolMeta:
    return ToolMeta(
        name=name, server=server, description=name, source=ToolSource.NATIVE
    )


# ── 单元：命名与过滤 ─────────────────────────────────────────


def test_flat_name_map_single_server_uses_bare_names():
    metas = [_meta("add", "demo"), _meta("greet", "demo")]
    assert flat_name_map(metas) == {"add": "demo/add", "greet": "demo/greet"}


def test_flat_name_map_multi_server_adds_prefix():
    metas = [_meta("add", "a"), _meta("add", "b")]
    assert flat_name_map(metas) == {"a__add": "a/add", "b__add": "b/add"}


def test_flat_name_map_sanitizes_invalid_chars():
    metas = [_meta("do.thing", "my.server"), _meta("x", "other")]
    assert flat_name_map(metas)["my_server__do_thing"] == "my.server/do.thing"


def test_flat_name_map_collision_gets_suffix():
    """清洗后同名的工具不互相覆盖，按序加后缀。"""
    metas = [_meta("x", "my.server"), _meta("x", "my_server"), _meta("查询", "s")]
    mapping = flat_name_map(metas)
    assert len(mapping) == 3
    assert mapping["my_server__x"] == "my.server/x"
    assert mapping["my_server__x_2"] == "my_server/x"


def test_tool_description_appends_output_example():
    meta = _meta("add", "demo").model_copy(update={"output_example": {"ok": True}})
    assert _tool_description(meta) == 'add\n\nOutput example: {"ok": true}'
    assert _tool_description(_meta("add", "demo")) == "add"


def test_build_registry_filters_by_server(monkeypatch):
    monkeypatch.setattr("axi.mcp_serve.app_config", AxiConfig())
    metas = [_meta("add", "a"), _meta("sub", "b")]
    registry = build_registry(metas, "a")
    assert registry.list_names() == ["a/add"]


def test_build_registry_unknown_server_exits(monkeypatch):
    monkeypatch.setattr("axi.mcp_serve.app_config", AxiConfig())
    with pytest.raises(SystemExit, match="nope"):
        build_registry([_meta("add", "a")], "nope")


def test_build_registry_configured_but_unconnected_server(monkeypatch):
    """server 配置在 mcpServers 里但没连上时，报连接问题而非'不存在'。"""
    from axi.daemon.protocol import DaemonResponse

    config = AxiConfig.model_validate(
        {"mcpServers": {"browser": {"command": "definitely-not-a-command"}}}
    )
    monkeypatch.setattr("axi.mcp_serve.app_config", config)
    monkeypatch.setattr(
        "axi.mcp_serve.daemon_request",
        lambda req: DaemonResponse.fail("daemon down"),
    )
    with pytest.raises(SystemExit, match="configured but not connected"):
        build_registry([_meta("add", "a")], "browser")


# ── 端到端 ───────────────────────────────────────────────────


@pytest.fixture
def serve_env(tmp_path: Path) -> dict[str, str]:
    """临时 HOME + AXI_CONFIG，注册一个含两个工具的 native 模块。"""
    tools = tmp_path / "demo.py"
    tools.write_text(TOOLS_PY)
    config = tmp_path / "axi.json"
    config.write_text(json.dumps({"nativeTools": [{"module": str(tools)}]}))
    return {
        "AXI_CONFIG": str(config),
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
    }


def _stdio_conn(env: dict[str, str], *cli_args: str) -> MCPConnection:
    return MCPConnection(
        MCPServerConfig(
            server="axi-under-test",
            command=sys.executable,
            args=["-c", RUN_CLI, "mcp", *cli_args],
            env=env,
        )
    )


@pytest.mark.asyncio
async def test_stdio_flat_mode(serve_env):
    conn = _stdio_conn(serve_env, "--server", "demo")
    try:
        await conn.connect()
        tools = await conn.list_tools()
        assert sorted(t.name for t in tools) == ["add_nums", "greet"]

        result = await conn.call_tool("add_nums", {"a": 3, "b": 5})
        assert result == 8
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_stdio_meta_mode(serve_env):
    conn = _stdio_conn(serve_env)
    try:
        await conn.connect()
        tools = await conn.list_tools()
        assert sorted(t.name for t in tools) == ["describe", "grep", "run", "search"]

        found = await conn.call_tool("grep", {"pattern": "add"})
        assert [t["name"] for t in found] == ["demo/add_nums"]

        detail = await conn.call_tool("describe", {"name": "add_nums"})
        assert detail["input_schema"]["required"] == ["a", "b"]

        result = await conn.call_tool(
            "run", {"name": "add_nums", "params": {"a": 1, "b": 2}}
        )
        assert result == {"status": "success", "data": 3}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_http_transport(serve_env):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            RUN_CLI,
            "mcp",
            "--transport",
            "http",
            "--server",
            "demo",
            "--port",
            str(port),
        ],
        env=serve_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    conn = None
    try:
        # server 子进程 import 较慢，先用裸 HTTP 轮询到 uvicorn 应答再建 MCP 连接
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    resp = await client.post(f"http://127.0.0.1:{port}/mcp/", json={})
                    if "uvicorn" in resp.headers.get("server", ""):
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
            else:
                pytest.fail("HTTP server did not start")

        conn = MCPConnection(
            MCPServerConfig(server="axi-http", url=f"http://127.0.0.1:{port}/mcp")
        )
        await conn.connect()
        tools = await conn.list_tools()
        assert sorted(t.name for t in tools) == ["add_nums", "greet"]
        result = await conn.call_tool("greet", {"name": "axi"})
        assert result == "hi axi"
    finally:
        if conn is not None:
            await conn.close()
        proc.terminate()
        proc.wait(timeout=5)
