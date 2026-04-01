"""MCP Provider 集成测试。"""

import sys
from pathlib import Path

import pytest

from axi.providers.mcp import MCPProvider, MCPServerConfig, MCPConnection
from axi.models import ToolSource


MOCK_SERVER = str(Path(__file__).parent / "mock_mcp_server.py")


@pytest.fixture
def mock_config():
    return MCPServerConfig(
        server="test-server",
        command=sys.executable,
        args=[MOCK_SERVER],
    )


@pytest.mark.asyncio
async def test_mcp_connect_and_list_tools(mock_config):
    conn = MCPConnection(mock_config)
    try:
        await conn.connect()
        tools = await conn.list_tools()
        assert len(tools) == 2

        echo_tool = next(t for t in tools if t.name == "echo")
        assert echo_tool.server == "test-server"
        assert echo_tool.full_name == "test-server/echo"
        assert echo_tool.source == ToolSource.MCP
        assert "message" in echo_tool.input_schema["properties"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mcp_call_tool(mock_config):
    conn = MCPConnection(mock_config)
    try:
        await conn.connect()
        result = await conn.call_tool("echo", {"message": "hello axi"})
        assert result == "hello axi"

        result = await conn.call_tool("add", {"a": 3, "b": 5})
        assert result == 8
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mcp_provider_connect_all(mock_config):
    provider = MCPProvider()
    try:
        tools = await provider.connect_all([mock_config])
        assert len(tools) == 2

        result = await provider.call_tool("test-server", "echo", {"message": "test"})
        assert result.status == "success"
        assert result.data == "test"
    finally:
        await provider.close_all()


def test_mcp_load_config(monkeypatch):
    from axi.config import AxiConfig

    mock_config = AxiConfig.model_validate(
        {
            "mcpServers": {
                "my-server": {
                    "command": "python",
                    "args": ["server.py"],
                    "env": {"API_KEY": "xxx"},
                }
            }
        }
    )
    monkeypatch.setattr("axi.providers.mcp.app_config", mock_config)

    provider = MCPProvider()
    configs = provider.load_config()
    assert len(configs) == 1
    assert configs[0].server == "my-server"
    assert configs[0].command == "python"
    assert configs[0].env == {"API_KEY": "xxx"}
