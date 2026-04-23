"""原生工具 Provider：通过 @tool 装饰器注册 Python 函数，
并负责从 axi.json 的 nativeTools 与 Python entry_points 加载工具模块。"""

import importlib
import importlib.metadata
import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any, Callable, get_type_hints

from pydantic import create_model

from axi.config import NativeToolEntry, app_config
from axi.models import ToolMeta, ToolSource

logger = logging.getLogger(__name__)

# 全局注册表，存储原生工具的函数引用
_native_functions: dict[str, Callable] = {}


# ── 工具注册（@tool 装饰器的执行层）────────────────────────────


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


# ── 模块发现与加载 ─────────────────────────────────────────────

NATIVE_TOOLS_ENTRY_POINT_GROUP = "axi.native_tools"


def _import_from_file(file_path: str) -> None:
    """通过文件路径 import 模块，触发 @tool 注册。"""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def _resolve_server_name(entry: NativeToolEntry) -> str:
    """推导 native tool 的 server 名称。"""
    if entry.name is not None:
        return entry.name
    if entry.module.endswith(".py"):
        return Path(entry.module).stem
    return entry.module.rsplit(".", 1)[-1]


def _load_native_entry(
    registry: Any,
    module: str,
    server_name: str,
    loaded: dict[str, str],
    source: str,
) -> None:
    """加载单个原生工具模块并把新增工具归到 server_name 下。

    ``loaded`` 以 "模块路径 → server 名" 映射**仅记录成功加载**的模块：
    - 模块路径重复 → 跳过（axi.json 与 entry_points 声明同一个模块是预期情况）
    - 导入抛异常 → logger.exception 后 return，不占坑也不让一个坏包搞崩 CLI
    - 加载成功但 server 名被别的模块占了 → logger.warning，继续挂到该 server 下

    失败的模块不写入 ``loaded`` 可以避免对后续合法包误报 collision。
    """
    if module in loaded:
        return
    try:
        before = set(registry.list_names())
        if module.endswith(".py"):
            _import_from_file(module)
        else:
            importlib.import_module(module)
        new_names = [n for n in registry.list_names() if n not in before]
    except Exception:
        logger.exception(
            "Failed to load native tool module '%s' (from %s)", module, source
        )
        return
    if server_name in loaded.values():
        other = next(m for m, s in loaded.items() if s == server_name)
        logger.warning(
            "Server name collision: '%s' already claimed by module '%s'; "
            "tools from '%s' (%s) will be merged under the same server",
            server_name,
            other,
            module,
            source,
        )
    loaded[module] = server_name
    for name in new_names:
        registry.set_server(name, server_name)


def load_native_tool_modules() -> None:
    """从 axi.json 的 nativeTools 与 Python entry_points 加载原生工具模块。

    合并规则：
    - axi.json 先遍历，entry_points 后遍历；按**模块路径**去重（同一个模块只加载一次）
    - 因此重复声明时 axi.json 的 server 名赢
    - 不同模块声明同一个 server 名时仅 log warning，两边工具都会注册到该 server
    """
    from axi.cli import get_registry

    registry = get_registry()
    loaded: dict[str, str] = {}

    # 来源 1：axi.json 的 nativeTools（显式配置，优先级更高）
    for entry in app_config.native_tools:
        _load_native_entry(
            registry,
            entry.module,
            _resolve_server_name(entry),
            loaded,
            source="axi.json",
        )

    # 来源 2：Python entry_points group="axi.native_tools"
    # 任何 pip 安装的包在 pyproject.toml 里声明就会被自动发现，
    # 无需在 axi.json 里重复登记。
    try:
        eps = importlib.metadata.entry_points(group=NATIVE_TOOLS_ENTRY_POINT_GROUP)
    except Exception:
        logger.exception(
            "Failed to query entry_points for %s", NATIVE_TOOLS_ENTRY_POINT_GROUP
        )
        eps = []
    for ep in eps:
        module_path = ep.value.split(":", 1)[0].strip()
        _load_native_entry(
            registry,
            module_path,
            ep.name,
            loaded,
            source=f"entry_points:{ep.name}",
        )
