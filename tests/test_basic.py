"""基础端到端测试。"""

from axi import tool
from axi.cli import get_registry, get_executor


# 注册测试工具
@tool(name="greet", description="向用户打招呼")
def greet(name: str, greeting: str = "Hello") -> dict:
    return {"message": f"{greeting}, {name}!"}


@tool(name="add_numbers", description="两数相加")
def add_numbers(a: int, b: int) -> int:
    return a + b


def test_tool_registration():
    registry = get_registry()
    meta = registry.get("greet")
    assert meta is not None
    assert meta.name == "greet"
    assert meta.description == "向用户打招呼"
    assert "name" in meta.input_schema["properties"]


def test_tool_execution():
    executor = get_executor()
    result = executor.run("greet", {"name": "World"})
    assert result.status == "success"
    assert result.data == {"message": "Hello, World!"}


def test_tool_execution_with_params():
    executor = get_executor()
    result = executor.run("add_numbers", {"a": 3, "b": 5})
    assert result.status == "success"
    assert result.data == 8


def test_tool_not_found():
    executor = get_executor()
    result = executor.run("nonexistent", {})
    assert result.status == "error"


def test_search_substring():
    registry = get_registry()
    results = registry.search("打招呼")
    assert len(results) > 0
    assert results[0].name == "greet"


def test_search_regex():
    registry = get_registry()
    results = registry.search("add_.*", regex=True)
    assert len(results) > 0
    assert results[0].name == "add_numbers"


def test_ptc_call():
    greet_fn = tool("greet")
    result = greet_fn(name="PTC", greeting="Hi")
    assert result == {"message": "Hi, PTC!"}


def test_describe():
    registry = get_registry()
    meta = registry.get("greet")
    assert meta is not None
    assert meta.input_schema["required"] == ["name"]
    assert meta.input_schema["properties"]["greeting"]["default"] == "Hello"
