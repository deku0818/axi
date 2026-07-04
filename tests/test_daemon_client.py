"""Daemon 客户端测试：连接错误处理和超时。"""

import pytest

from axi.config import DaemonConfig
from axi.daemon.client import _send
from axi.daemon.protocol import DaemonRequest


class TestRequestTimeout:
    """AXI_REQUEST_TIMEOUT 优先于 axi.json，落在 DaemonConfig 的 env 校验里。"""

    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("AXI_REQUEST_TIMEOUT", "7")
        cfg = DaemonConfig.model_validate({"requestTimeout": 45})
        assert cfg.request_timeout == 7.0

    def test_invalid_env_keeps_config(self, monkeypatch):
        monkeypatch.setenv("AXI_REQUEST_TIMEOUT", "not-a-number")
        cfg = DaemonConfig.model_validate({"requestTimeout": 45})
        assert cfg.request_timeout == 45.0

    def test_default_without_env(self, monkeypatch):
        monkeypatch.delenv("AXI_REQUEST_TIMEOUT", raising=False)
        assert DaemonConfig.model_validate({}).request_timeout == 120.0


class TestDaemonClientErrors:
    @pytest.mark.asyncio
    async def test_connection_refused_returns_error(self, tmp_path, monkeypatch):
        """daemon 未运行时 _send 返回友好错误而非抛异常。"""
        fake_socket = str(tmp_path / "nonexistent.sock")
        monkeypatch.setattr("axi.daemon.client.SOCKET_PATH", fake_socket)

        resp = await _send(DaemonRequest(method="list_tools"))
        assert resp.status == "error"
        assert "Cannot connect to daemon" in resp.error


class TestDaemonParamsValidation:
    @pytest.mark.asyncio
    async def test_call_tool_rejects_invalid_params(self, monkeypatch):
        """daemon 在转发前按 input_schema 校验 MCP 工具入参。"""
        from axi.config import AxiConfig
        from axi.daemon.server import DaemonServer
        from axi.models import ToolMeta, ToolSource

        monkeypatch.setattr("axi.daemon.server.app_config", AxiConfig())
        server = DaemonServer()
        server.registry.register(
            ToolMeta(
                name="echo",
                server="mock",
                description="echo",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
                source=ToolSource.MCP,
            )
        )

        resp = await server._handle_call_tool(
            DaemonRequest(method="call_tool", tool_name="mock/echo", params={})
        )
        assert resp.status == "error"
        assert "Invalid params" in resp.error

        # 数字 → string 由 _coerce_to_schema 转换，通过校验后到达连接层
        resp = await server._handle_call_tool(
            DaemonRequest(
                method="call_tool", tool_name="mock/echo", params={"message": 42}
            )
        )
        assert resp.status == "error"
        assert "not connected" in resp.error

        # 完全错误的类型（list → string）仍被拦截
        resp = await server._handle_call_tool(
            DaemonRequest(
                method="call_tool", tool_name="mock/echo", params={"message": [1]}
            )
        )
        assert resp.status == "error"
        assert "Invalid params" in resp.error

    @pytest.mark.asyncio
    async def test_call_tool_bad_schema_does_not_block(self, monkeypatch):
        """schema 含不可解析 $ref 时不拦调用（到达连接层而非校验报错）。"""
        from axi.config import AxiConfig
        from axi.daemon.server import DaemonServer
        from axi.models import ToolMeta, ToolSource

        monkeypatch.setattr("axi.daemon.server.app_config", AxiConfig())
        server = DaemonServer()
        server.registry.register(
            ToolMeta(
                name="reffy",
                server="mock",
                description="",
                input_schema={
                    "type": "object",
                    "properties": {"x": {"$ref": "#/$defs/missing"}},
                },
                source=ToolSource.MCP,
            )
        )
        resp = await server._handle_call_tool(
            DaemonRequest(method="call_tool", tool_name="mock/reffy", params={"x": 1})
        )
        assert resp.status == "error"
        assert "not connected" in resp.error


class TestCoerceToSchema:
    def test_coercions(self):
        from axi.daemon.server import _coerce_to_schema

        schema = {
            "type": "object",
            "properties": {
                "msg": {"type": "string"},
                "port": {"type": "integer"},
                "rate": {"type": "number"},
                "on": {"type": "boolean"},
            },
        }
        assert _coerce_to_schema(
            {"msg": 42, "port": "08080", "rate": "1.5", "on": "true"}, schema
        ) == {"msg": "42", "port": 8080, "rate": 1.5, "on": True}
        # 不可转换的原样保留，交给校验报错
        assert _coerce_to_schema({"port": "abc", "msg": [1]}, schema) == {
            "port": "abc",
            "msg": [1],
        }
