"""统一执行层：执行原生工具。MCP 工具通过 daemon 执行。"""

import asyncio
import inspect
import logging
import traceback
from typing import Any

logger = logging.getLogger(__name__)

from axi.models import RunResult, ToolSource
from axi.providers.native import get_native_function
from axi.registry import Registry


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
            return RunResult.fail(f"Non-native tool should be executed via daemon: {full_name}")

        func = get_native_function(meta.name)
        if not func:
            return RunResult.fail(f"Native function not found: {meta.name}")

        try:
            result = func(**params)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return RunResult.success(result)
        except Exception as e:
            logger.debug("Tool execution error:\n%s", traceback.format_exc())
            return RunResult.fail(f"{type(e).__name__}: {e}")
