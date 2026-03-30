"""模型验证测试：覆盖本次新增的 validator 和 Literal 约束。"""

import pytest
from pydantic import ValidationError

from axi.models import ResultEnvelope, RunResult, ToolMeta, ToolSource


# ── ToolMeta validator ──────────────────────────────────────────


class TestToolMetaValidation:
    def test_name_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            ToolMeta(name="", description="test", source=ToolSource.NATIVE)

    def test_name_cannot_contain_slash(self):
        with pytest.raises(ValidationError, match="must not contain '/'"):
            ToolMeta(name="a/b", description="test", source=ToolSource.NATIVE)

    def test_mcp_tool_must_have_server(self):
        with pytest.raises(ValidationError, match="MCP tool must have a server name"):
            ToolMeta(name="echo", description="test", source=ToolSource.MCP)

    def test_mcp_tool_with_server_ok(self):
        meta = ToolMeta(
            name="echo", server="my-server", description="test", source=ToolSource.MCP
        )
        assert meta.full_name == "my-server/echo"

    def test_native_tool_without_server_ok(self):
        meta = ToolMeta(name="greet", description="test", source=ToolSource.NATIVE)
        assert meta.full_name == "greet"

    def test_native_tool_with_server_ok(self):
        meta = ToolMeta(
            name="greet", server="my-mod", description="test", source=ToolSource.NATIVE
        )
        assert meta.full_name == "my-mod/greet"


# ── ResultEnvelope Literal status ──────────────────────────────


class TestResultEnvelope:
    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ResultEnvelope(status="banana")

    def test_success_factory(self):
        r = ResultEnvelope.success({"key": "value"})
        assert r.status == "success"
        assert r.data == {"key": "value"}
        assert r.error is None

    def test_fail_factory(self):
        r = ResultEnvelope.fail("something broke")
        assert r.status == "error"
        assert r.error == "something broke"
        assert r.data is None

    def test_run_result_inherits(self):
        r = RunResult.success(42)
        assert isinstance(r, RunResult)
        assert r.status == "success"
        assert r.data == 42
