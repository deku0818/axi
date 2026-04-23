"""验证 Python entry_points (group='axi.native_tools') 的自动发现机制。"""

import sys
from importlib.metadata import EntryPoint
from unittest.mock import patch

from axi.cli import get_registry
from axi.providers.native import load_native_tool_modules

_FAKE_TOOL_SHORT_NAMES = ("ping_ep", "pong_ep")


def _reset_fake_ep_module() -> None:
    """保证测试独立：清 fake_ep_* 的 import 缓存 + 清 registry 里的痕迹。"""
    for mod_name in list(sys.modules):
        if mod_name.startswith("fake_ep"):
            sys.modules.pop(mod_name, None)
    registry = get_registry()
    for full_name in list(registry.list_names()):
        if any(full_name.endswith(f"/{t}") for t in _FAKE_TOOL_SHORT_NAMES):
            registry._tools.pop(full_name, None)
            registry._dirty = True


def _make_ep(name: str, value: str) -> EntryPoint:
    # value 指向 tests/ 目录里的 fake_ep_* 模块，由 pytest rootdir 机制保证可 import。
    return EntryPoint(name=name, value=value, group="axi.native_tools")


def test_entry_points_discovers_and_registers_tool():
    """mock entry_points，确认工具被加载并挂到 server 名下。"""
    _reset_fake_ep_module()
    with patch(
        "axi.providers.native.importlib.metadata.entry_points",
        return_value=[_make_ep("fakepkg", "fake_ep_tools")],
    ):
        load_native_tool_modules()

    registry = get_registry()
    meta = registry.get("fakepkg/ping_ep")
    assert meta is not None, "tool should be registered under entry_points server name"
    assert meta.name == "ping_ep"


def test_entry_points_module_deduped_against_axi_json(monkeypatch):
    """同一个模块被 axi.json 和 entry_points 同时声明时，axi.json 的 server 名赢。"""
    _reset_fake_ep_module()

    from axi.config import NativeToolEntry
    from axi.providers import native as native_module

    monkeypatch.setattr(
        native_module.app_config,
        "native_tools",
        [NativeToolEntry(module="fake_ep_tools", name="jsonname")],
    )
    with patch(
        "axi.providers.native.importlib.metadata.entry_points",
        return_value=[_make_ep("fakepkg", "fake_ep_tools")],
    ):
        load_native_tool_modules()

    registry = get_registry()
    assert registry.get("jsonname/ping_ep") is not None, "axi.json 的 server 名应赢"
    assert registry.get("fakepkg/ping_ep") is None, "entry_points 同模块应被去重跳过"


def test_entry_points_value_colon_suffix_is_stripped():
    """ep.value 形如 'pkg.mod:func' 时，冒号后缀被剥离，模块仍正确加载。"""
    _reset_fake_ep_module()
    with patch(
        "axi.providers.native.importlib.metadata.entry_points",
        return_value=[_make_ep("colonpkg", "fake_ep_tools:ping_ep")],
    ):
        load_native_tool_modules()

    registry = get_registry()
    assert registry.get("colonpkg/ping_ep") is not None, "冒号后缀应被剥离后仍能 import"


def test_entry_points_server_name_collision_warns_and_merges(monkeypatch, caplog):
    """不同模块声明同一个 server 名时：warning + 两边工具都挂到该 server 下。"""
    _reset_fake_ep_module()

    from axi.config import NativeToolEntry
    from axi.providers import native as native_module

    monkeypatch.setattr(
        native_module.app_config,
        "native_tools",
        [NativeToolEntry(module="fake_ep_tools", name="shared")],
    )
    # entry_points 声明另一个模块，但撞了同一个 server 名
    with patch(
        "axi.providers.native.importlib.metadata.entry_points",
        return_value=[_make_ep("shared", "fake_ep_tools_alt")],
    ):
        load_native_tool_modules()

    registry = get_registry()
    assert registry.get("shared/ping_ep") is not None, "axi.json 的工具应挂到 shared 下"
    assert registry.get("shared/pong_ep") is not None, (
        "entry_points 的工具也应挂到 shared 下（warning 后继续加载）"
    )
    assert "Server name collision" in caplog.text, "应记录 collision warning"


def test_entry_points_broken_module_is_logged_and_skipped(monkeypatch, caplog):
    """ep 指向的模块 import 时抛异常 → 记日志、跳过、不影响其它来源。"""
    _reset_fake_ep_module()

    # 让 axi.json 先成功加载一个真实模块，用于验证一个坏 ep 不会影响其它来源
    from axi.config import NativeToolEntry
    from axi.providers import native as native_module

    monkeypatch.setattr(
        native_module.app_config,
        "native_tools",
        [NativeToolEntry(module="fake_ep_tools", name="good")],
    )
    with patch(
        "axi.providers.native.importlib.metadata.entry_points",
        return_value=[_make_ep("brokenpkg", "definitely_not_a_real_module_xyz")],
    ):
        # 不应抛——ModuleNotFoundError 会被 except Exception 捕获
        load_native_tool_modules()

    registry = get_registry()
    assert registry.get("good/ping_ep") is not None, "axi.json 来源的工具应该照常加载"
    assert registry.get("brokenpkg/ping_ep") is None, "坏 ep 不应该注册任何东西"
    assert "Failed to load native tool module" in caplog.text
    assert "definitely_not_a_real_module_xyz" in caplog.text


def test_entry_points_query_failure_is_tolerated(caplog):
    """entry_points 查询本身失败时降级为仅 axi.json 来源，记日志但不抛异常。"""
    _reset_fake_ep_module()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("metadata backend broken")

    with patch(
        "axi.providers.native.importlib.metadata.entry_points", side_effect=_boom
    ):
        load_native_tool_modules()

    assert "Failed to query entry_points" in caplog.text, (
        "entry_points 查询失败应记 exception 日志"
    )
