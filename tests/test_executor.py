"""Executor 测试：覆盖错误路径和异常处理。"""

from axi.executor import Executor
from axi.models import ToolMeta, ToolSource
from axi.providers.native import register_tool, _native_functions
from axi.registry import Registry


def _make_registry_with_tool(name: str, source: ToolSource, server: str | None = None):
    """辅助：创建包含单个工具的 registry。"""
    r = Registry()
    kwargs = {"name": name, "description": "test", "source": source}
    if server:
        kwargs["server"] = server
    r.register(ToolMeta(**kwargs))
    return r


class TestExecutorErrors:
    def test_non_native_tool_rejected(self):
        registry = _make_registry_with_tool("echo", ToolSource.MCP, server="srv")
        executor = Executor(registry)
        result = executor.run("srv/echo", {})
        assert result.status == "error"
        assert "daemon" in result.error

    def test_tool_exception_captured(self):
        registry = Registry()

        def bad_func():
            raise RuntimeError("boom")

        meta = register_tool(bad_func, name="bad_func", description="will fail")
        registry.register(meta)

        executor = Executor(registry)
        result = executor.run("bad_func", {})
        assert result.status == "error"
        assert "RuntimeError" in result.error
        assert "boom" in result.error

    def test_native_function_not_registered(self):
        """Registry 有 meta 但 _native_functions 中没有对应函数。"""
        registry = Registry()
        registry.register(ToolMeta(
            name="ghost_tool", description="test", source=ToolSource.NATIVE
        ))
        # 确保函数不在 native 注册表中
        _native_functions.pop("ghost_tool", None)

        executor = Executor(registry)
        result = executor.run("ghost_tool", {})
        assert result.status == "error"
        assert "Native function not found" in result.error
