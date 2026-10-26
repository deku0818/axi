"""MCP Provider 集成测试。"""

import sys
import asyncio
import os
import signal
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
        assert len(tools) == 3

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
        assert len(tools) == 3

        result = await provider.call_tool("test-server", "echo", {"message": "test"})
        assert result.status == "success"
        assert result.data == "test"
    finally:
        await provider.close_all()


@pytest.mark.asyncio
async def test_mcp_tool_error_returns_error_envelope(mock_config):
    """server 返回 is_error 的结果必须落进 error 信封，不能伪装成 success。"""
    provider = MCPProvider()
    try:
        await provider.connect_all([mock_config])
        result = await provider.call_tool("test-server", "boom", {})
        assert result.status == "error"
        assert "kaboom" in result.error
    finally:
        await provider.close_all()


@pytest.mark.asyncio
async def test_reconnect_from_concurrent_request_tasks(mock_config, tmp_path):
    pid_path = tmp_path / "worker.pid"
    config = mock_config.model_copy(
        update={"env": {"AXI_TEST_PID_PATH": str(pid_path)}}
    )
    provider = MCPProvider()
    try:
        await provider.connect_all([config])
        old_pid = int(pid_path.read_text())
        os.kill(old_pid, signal.SIGKILL)
        await asyncio.sleep(0.1)
        results = await asyncio.wait_for(
            asyncio.gather(
                provider.call_tool(config.server, "echo", {"message": "one"}),
                provider.call_tool(config.server, "echo", {"message": "two"}),
            ),
            timeout=10,
        )
        assert [r.status for r in results] == ["success", "success"]
        assert [r.data for r in results] == ["one", "two"]
        assert int(pid_path.read_text()) != old_pid
    finally:
        await provider.close_all()


@pytest.mark.asyncio
async def test_list_failure_is_cleaned_up_and_does_not_block_other_servers(
    mock_config, tmp_path
):
    pid_path = tmp_path / "failed-worker.pid"
    bad = mock_config.model_copy(
        update={
            "server": "bad",
            "env": {"AXI_TEST_LIST_ERROR": "1", "AXI_TEST_PID_PATH": str(pid_path)},
        }
    )
    provider = MCPProvider()
    try:
        tools = await asyncio.wait_for(provider.connect_all([bad, mock_config]), 10)
        assert len(tools) == 3
        assert {t.server for t in tools} == {mock_config.server}
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_path.read_text()), 0)
        result = await asyncio.create_task(
            provider.call_tool(mock_config.server, "echo", {"message": "healthy"})
        )
        assert result.data == "healthy"
    finally:
        await provider.close_all()


@pytest.mark.asyncio
async def test_list_tools_follows_pagination(mock_config):
    conn = MCPConnection(
        mock_config.model_copy(update={"env": {"AXI_TEST_PAGINATED": "1"}})
    )
    try:
        await conn.connect()
        tools = await conn.list_tools()
        assert [t.name for t in tools] == ["echo", "add", "boom"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_inflight_failure_does_not_reconnect_after_shutdown(
    mock_config, monkeypatch
):
    provider = MCPProvider()
    await provider.connect_all([mock_config])
    conn = provider._connections[mock_config.server]
    started = asyncio.Event()

    async def failed_call(name, params):
        started.set()
        raise ConnectionError("MCP disconnected")

    monkeypatch.setattr(conn, "call_tool", failed_call)
    async with conn.reconnect_lock:
        task = asyncio.create_task(
            provider.call_tool(mock_config.server, "echo", {"message": "late"})
        )
        await started.wait()
        shutdown = asyncio.create_task(provider.close_all())
        await asyncio.sleep(0)
    try:
        await shutdown
        result = await asyncio.wait_for(task, 10)
        assert result.status == "error"
        assert conn.session is None
    finally:
        await task
        await conn.close()


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
