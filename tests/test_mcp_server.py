"""axi 作为 MCP Server 对外暴露工具的测试。"""

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from axi.cli import get_registry
from axi.daemon.protocol import DaemonResponse
from axi.mcp_server import build_mcp_server
from axi.providers.native import register_tool


@pytest.fixture(autouse=True)
def no_daemon(monkeypatch):
    """避免测试启动真实 daemon：MCP 代理工具列表返回空。"""
    monkeypatch.setattr("axi.mcp_server.ensure_daemon", lambda: False)


def _register(func, name: str, server: str, description: str) -> str:
    """在全局 registry 注册一个原生工具，返回其 MCP tool name。"""
    meta = register_tool(func, name=name, description=description)
    updated = meta.model_copy(update={"server": server})
    get_registry().register(updated)
    return updated.full_name.replace("/", "__")


def test_build_returns_fastmcp():
    assert isinstance(build_mcp_server(), FastMCP)


def test_native_tool_registered():
    def greet(who: str) -> str:
        return f"hi {who}"

    mcp_name = _register(greet, "greet", "demo", "greet someone")
    mcp = build_mcp_server()

    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    assert mcp_name in tools
    tool = tools[mcp_name]
    assert tool.description == "greet someone"
    # input_schema 透传自 ToolMeta，who 为必填字符串
    assert tool.parameters["properties"]["who"]["type"] == "string"
    assert "who" in tool.parameters["required"]


@pytest.mark.asyncio
async def test_native_tool_call_executes():
    def add(a: int, b: int) -> int:
        return a + b

    mcp_name = _register(add, "add_nums", "demo", "add two numbers")
    mcp = build_mcp_server()

    result = await mcp._tool_manager.call_tool(mcp_name, {"a": 2, "b": 3})
    assert result == 5


@pytest.mark.asyncio
async def test_native_tool_error_raises_tool_error():
    def boom() -> None:
        raise RuntimeError("kaboom")

    mcp_name = _register(boom, "boom", "demo", "always fails")
    mcp = build_mcp_server()

    with pytest.raises(ToolError, match="kaboom"):
        await mcp._tool_manager.call_tool(mcp_name, {})


@pytest.mark.asyncio
async def test_mcp_proxy_tool(monkeypatch):
    """daemon 可用时，MCP 工具被注册为代理并转发 call_tool。"""
    tool_meta = {
        "name": "click",
        "server": "browser",
        "description": "click element",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
        "source": "mcp",
    }

    def fake_send_request(req):
        if req.method == "list_tools":
            return DaemonResponse.success([tool_meta])
        if req.method == "call_tool":
            assert req.tool_name == "browser/click"
            return DaemonResponse.success({"clicked": req.params["selector"]})
        return DaemonResponse.fail("unexpected")

    monkeypatch.setattr("axi.mcp_server.ensure_daemon", lambda: True)
    monkeypatch.setattr("axi.mcp_server.send_request", fake_send_request)

    mcp = build_mcp_server()
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    assert "browser__click" in tools

    result = await mcp._tool_manager.call_tool("browser__click", {"selector": "#ok"})
    assert result == {"clicked": "#ok"}
