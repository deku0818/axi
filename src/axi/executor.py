"""统一执行层：执行原生工具。MCP 工具通过 daemon 执行。"""

import asyncio
import inspect
import logging
import traceback
from typing import Any

from pydantic import ValidationError

from axi.models import RunResult, ToolSource
from axi.providers.native import get_native_function, validate_native_params
from axi.registry import Registry

logger = logging.getLogger(__name__)


def _format_validation_error(e: ValidationError) -> str:
    """把 Pydantic 校验错误压成单行：'field: message; field2: message2'。"""
    return "; ".join(
        f"{'.'.join(str(x) for x in err['loc']) or 'params'}: {err['msg']}"
        for err in e.errors()
    )


class Executor:
    """原生工具执行器。"""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def run(self, full_name: str, params: dict[str, Any]) -> RunResult:
        """执行原生工具并返回统一结果。"""
        meta = self._registry.get(full_name)
        if not meta:
            return RunResult.fail(f"Tool not found: {full_name}")

        if meta.source != ToolSource.NATIVE:
            return RunResult.fail(
                f"Non-native tool should be executed via daemon: {full_name}"
            )

        func = get_native_function(meta.full_name)
        if not func:
            return RunResult.fail(f"Native function not found: {meta.full_name}")

        try:
            params = validate_native_params(meta.full_name, params)
        except ValidationError as e:
            return RunResult.fail(f"Invalid params: {_format_validation_error(e)}")

        try:
            result = func(**params)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return RunResult.success(result)
        except Exception as e:
            logger.debug("Tool execution error:\n%s", traceback.format_exc())
            return RunResult.fail(f"{type(e).__name__}: {e}")
