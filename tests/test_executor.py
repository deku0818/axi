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
        registry.register(
            ToolMeta(name="ghost_tool", description="test", source=ToolSource.NATIVE)
        )
        # 确保函数不在 native 注册表中
        _native_functions.pop("ghost_tool", None)

        executor = Executor(registry)
        result = executor.run("ghost_tool", {})
        assert result.status == "error"
        assert "Native function not found" in result.error


class TestSameNameTools:
    def test_same_name_in_two_modules_not_shadowed(self, tmp_path):
        """两个模块注册同名工具时，各自的 full_name 路由到各自的函数。"""
        from axi.cli import get_registry
        from axi.providers.native import _load_native_entry

        src = "from axi import tool\n\n@tool(description='{d}')\ndef shadow_ping() -> str:\n    return '{r}'\n"
        (tmp_path / "mod_a.py").write_text(src.format(d="a", r="A"))
        (tmp_path / "mod_b.py").write_text(src.format(d="b", r="B"))

        registry = get_registry()
        loaded: dict[str, str] = {}
        _load_native_entry(registry, str(tmp_path / "mod_a.py"), "mod_a", loaded, "t")
        _load_native_entry(registry, str(tmp_path / "mod_b.py"), "mod_b", loaded, "t")

        executor = Executor(registry)
        assert executor.run("mod_a/shadow_ping", {}).data == "A"
        assert executor.run("mod_b/shadow_ping", {}).data == "B"


class TestParamsValidation:
    def _executor_with(self, func, name: str) -> Executor:
        registry = Registry()
        registry.register(register_tool(func, name=name))
        return Executor(registry)

    def test_missing_required_param(self):
        def need_arg(x: int) -> int:
            return x

        executor = self._executor_with(need_arg, "need_arg")
        result = executor.run("need_arg", {})
        assert result.status == "error"
        assert "Invalid params" in result.error
        assert "x" in result.error

    def test_wrong_type_rejected(self):
        def need_int(x: int) -> int:
            return x

        executor = self._executor_with(need_int, "need_int")
        result = executor.run("need_int", {"x": "abc"})
        assert result.status == "error"
        assert "Invalid params" in result.error

    def test_string_coerced_to_int(self):
        """CLI 传入的字符串数字被转换为目标类型。"""

        def double(x: int) -> int:
            return x * 2

        executor = self._executor_with(double, "double")
        result = executor.run("double", {"x": "3"})
        assert result.status == "success"
        assert result.data == 6

    def test_extra_param_rejected(self):
        def no_extra(x: int = 1) -> int:
            return x

        executor = self._executor_with(no_extra, "no_extra")
        result = executor.run("no_extra", {"typo": 1})
        assert result.status == "error"
        assert "Invalid params" in result.error

    def test_omitted_optional_uses_function_default(self):
        def with_default(x: int = 42) -> int:
            return x

        executor = self._executor_with(with_default, "with_default")
        result = executor.run("with_default", {})
        assert result.status == "success"
        assert result.data == 42

    def test_number_coerced_to_str(self):
        """CLI 把 --name 42 猜成 int，str 参数应接收 \"42\" 而非报错。"""

        def greet(name: str) -> str:
            return f"hi {name}"

        executor = self._executor_with(greet, "greet")
        result = executor.run("greet", {"name": 42})
        assert result.status == "success"
        assert result.data == "hi 42"

    def test_kwargs_function_callable(self):
        """**kwargs 工具可正常调用，多余字段由 kwargs 吸收。"""

        def fetch(url: str, **kwargs) -> dict:
            return {"url": url, "extra": kwargs}

        executor = self._executor_with(fetch, "fetch")
        result = executor.run("fetch", {"url": "http://x", "timeout": 5})
        assert result.status == "success"
        assert result.data == {"url": "http://x", "extra": {"timeout": 5}}

        result = executor.run("fetch", {"url": "http://x"})
        assert result.status == "success"
        assert result.data == {"url": "http://x", "extra": {}}

    def test_nested_model_coerced_to_instance(self):
        from pydantic import BaseModel

        class Range(BaseModel):
            start: int
            end: int

        def span(r: Range) -> int:
            return r.end - r.start  # 需要真实例，dict 会 AttributeError

        executor = self._executor_with(span, "span")
        result = executor.run("span", {"r": {"start": 1, "end": 5}})
        assert result.status == "success"
        assert result.data == 4
