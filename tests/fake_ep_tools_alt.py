"""第二个 entry_points 测试 fixture：用于 server 名碰撞测试，
与 fake_ep_tools 是两个不同的模块路径。不要在其它测试里 import。"""

from axi import tool


@tool(name="pong_ep", description="用于 server 名碰撞测试的第二个工具")
def pong_ep() -> dict:
    return {"ok": True, "source": "entry_points_alt"}
