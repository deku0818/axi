"""测试用的假扩展包工具模块，由 tests/test_entry_points_discovery.py 通过 mock 后的
importlib.metadata.entry_points 触发加载。不要在其它测试里 import 它。"""

from axi import tool


@tool(name="ping_ep", description="从 entry_points 发现并注册的测试工具")
def ping_ep() -> dict:
    return {"ok": True, "source": "entry_points"}
