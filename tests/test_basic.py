"""基础端到端测试。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

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
    results = registry.grep("add_.*")
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


# ---- Schema 提取：高级类型 ----


@tool(name="query_orders", description="按区域查询订单")
def query_orders(
    region: Annotated[Literal["cn", "jp"], Field(description="地区只能支持中国和日本")],
    keywords: list[str] = [],
    limit: int = 10,
) -> dict:
    return {"region": region, "keywords": keywords, "limit": limit}


class FilterConfig(BaseModel):
    min_price: float
    max_price: float = 9999.0


@tool(name="search_products", description="搜索商品")
def search_products(
    query: str,
    filter: FilterConfig | None = None,
    page: Annotated[int, Field(ge=1, le=100, description="页码")] = 1,
) -> dict:
    return {"query": query}


def test_schema_literal_with_description():
    """Literal 枚举 + Field description。"""
    meta = get_registry().get("query_orders")
    region = meta.input_schema["properties"]["region"]
    assert region["enum"] == ["cn", "jp"]
    assert region["description"] == "地区只能支持中国和日本"


def test_schema_typed_list():
    """list[str] → array with items。"""
    meta = get_registry().get("query_orders")
    kw = meta.input_schema["properties"]["keywords"]
    assert kw["type"] == "array"
    assert kw["items"] == {"type": "string"}


def test_schema_optional_default():
    """带默认值的参数不在 required 中。"""
    meta = get_registry().get("query_orders")
    assert "region" in meta.input_schema["required"]
    assert "keywords" not in meta.input_schema.get("required", [])
    assert "limit" not in meta.input_schema.get("required", [])


def test_schema_nested_model():
    """Pydantic BaseModel 作为参数类型 → 嵌套 object schema。"""
    meta = get_registry().get("search_products")
    schema = meta.input_schema
    # filter 可以是 FilterConfig 或 None
    # 检查 FilterConfig 的属性被正确展开
    assert "query" in schema["properties"]
    assert "filter" in schema["properties"]


def test_schema_field_constraints():
    """Field(ge=1, le=100) → minimum / maximum。"""
    meta = get_registry().get("search_products")
    page = meta.input_schema["properties"]["page"]
    assert page.get("minimum") == 1
    assert page.get("maximum") == 100
    assert page.get("description") == "页码"
