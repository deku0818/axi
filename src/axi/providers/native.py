"""原生工具注册 Provider：通过 @tool 装饰器注册 Python 函数。"""

import inspect
from typing import Any, Callable, get_type_hints

from axi.models import ToolMeta, ToolSource

# 全局注册表，存储原生工具的函数引用
_native_functions: dict[str, Callable] = {}


def _extract_input_schema(func: Callable) -> dict[str, Any]:
    """从函数签名和 type hints 提取 JSON Schema。"""
    hints = get_type_hints(func)
    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for name, param in sig.parameters.items():
        if name == "return":
            continue

        prop: dict[str, Any] = {}
        hint = hints.get(name)
        if hint and hint in type_map:
            prop["type"] = type_map[hint]

        # 用参数默认值判断 required
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            prop["default"] = param.default

        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def register_tool(
    func: Callable,
    name: str | None = None,
    description: str | None = None,
    output_example: Any | None = None,
) -> ToolMeta:
    """注册一个原生 Python 函数为 axi 工具。"""
    tool_name = name or func.__name__
    tool_desc = description or func.__doc__ or ""

    meta = ToolMeta(
        name=tool_name,
        description=tool_desc,
        input_schema=_extract_input_schema(func),
        output_example=output_example,
        source=ToolSource.NATIVE,
    )

    _native_functions[tool_name] = func
    return meta


def get_native_function(name: str) -> Callable | None:
    """获取已注册的原生函数。"""
    return _native_functions.get(name)
