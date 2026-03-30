"""Registry 测试：覆盖 resolve、set_server、list_names 及搜索错误处理。"""

import pytest

from axi.models import ToolMeta, ToolSource
from axi.registry import Registry, ToolResolveError


@pytest.fixture
def registry():
    r = Registry()
    r.register(
        ToolMeta(
            name="echo",
            server="server-a",
            description="Echo tool",
            source=ToolSource.MCP,
        )
    )
    r.register(
        ToolMeta(
            name="echo",
            server="server-b",
            description="Another echo",
            source=ToolSource.MCP,
        )
    )
    r.register(
        ToolMeta(
            name="greet",
            server="server-a",
            description="Greet tool",
            source=ToolSource.MCP,
        )
    )
    return r


# ── resolve ──────────────────────────────────────────────


class TestResolve:
    def test_resolve_by_full_name(self, registry):
        meta = registry.resolve("server-a/echo")
        assert meta.name == "echo"
        assert meta.server == "server-a"

    def test_resolve_full_name_not_found(self, registry):
        with pytest.raises(ToolResolveError, match="Tool not found"):
            registry.resolve("server-x/echo")

    def test_resolve_unique_short_name(self, registry):
        meta = registry.resolve("greet")
        assert meta.name == "greet"
        assert meta.server == "server-a"

    def test_resolve_ambiguous_short_name(self, registry):
        with pytest.raises(ToolResolveError, match="Ambiguous"):
            registry.resolve("echo")

    def test_resolve_short_name_not_found(self, registry):
        with pytest.raises(ToolResolveError, match="Tool not found"):
            registry.resolve("nonexistent")


# ── set_server / list_names ──────────────────────────────


class TestRegistryMethods:
    def test_list_names(self, registry):
        names = registry.list_names()
        assert set(names) == {"server-a/echo", "server-b/echo", "server-a/greet"}

    def test_set_server(self):
        r = Registry()
        r.register(
            ToolMeta(name="my_tool", description="test", source=ToolSource.NATIVE)
        )
        assert "my_tool" in r.list_names()

        r.set_server("my_tool", "my-module")
        names = r.list_names()
        assert "my_tool" not in names
        assert "my-module/my_tool" in names

        meta = r.get("my-module/my_tool")
        assert meta is not None
        assert meta.server == "my-module"

    def test_set_server_nonexistent(self):
        r = Registry()
        r.set_server("nonexistent", "server")  # 不抛异常
        assert r.list_names() == []


# ── search 错误处理 ──────────────────────────────────────


class TestSearchErrors:
    def test_invalid_regex_raises_value_error(self, registry):
        with pytest.raises(ValueError, match="Invalid regex pattern"):
            registry.search("[invalid", regex=True)

    def test_valid_regex_search(self, registry):
        results = registry.search("echo", regex=True)
        assert len(results) == 2

    def test_substring_search(self, registry):
        results = registry.search("greet")
        assert len(results) == 1
        assert results[0].name == "server-a/greet"
