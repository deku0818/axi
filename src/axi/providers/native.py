"""原生工具注册 Provider：通过 @tool 装饰器注册 Python 函数。"""

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import create_model

from axi.models import ToolMeta, ToolSource

# 全局注册表，存储原生工具的函数引用
_native_functions: dict[str, Callable] = {}


def _extract_input_schema(func: Callable) -> dict[str, Any]:
    """从函数签名和 type hints 提取 JSON Schema。

    利用 Pydantic 的 create_model 动态构建模型，
    自动支持 Literal、Optional、list[T]、嵌套 BaseModel、Annotated[..., Field()] 等。
    """
    hints = get_type_hints(func, include_extras=True)
    sig = inspect.signature(func)
    fields: dict[str, Any] = {}

    for name, param in sig.parameters.items():
        hint = hints.get(name, Any)
        if param.default is inspect.Parameter.empty:
            fields[name] = (hint, ...)
        else:
            fields[name] = (hint, param.default)

    model = create_model(func.__name__, **fields)
    schema = model.model_json_schema()

    # 移除 Pydantic 自动添加的 title 字段，保持输出紧凑
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)

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
