"""统一执行入口：原生工具进程内执行，MCP 工具交给 daemon。"""

import asyncio
import inspect
import logging
from typing import Any

from pydantic import ValidationError

from axi.daemon.client import daemon_request
from axi.daemon.protocol import DaemonRequest
from axi.models import RunResult, ToolSource
from axi.providers.native import get_native_function, validate_native_params
from axi.registry import Registry, ToolNotFoundError, ToolResolveError

logger = logging.getLogger(__name__)


def _format_validation_error(e: ValidationError) -> str:
    """把 Pydantic 校验错误压成单行：'field: message; field2: message2'。"""
    return "; ".join(
        f"{'.'.join(str(x) for x in err['loc']) or 'params'}: {err['msg']}"
        for err in e.errors()
    )


class Executor:
    """按工具来源分发执行并返回统一结果。"""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def run(self, full_name: str, params: dict[str, Any]) -> RunResult:
        """解析名称；本地未找到的工具由 daemon 解析。"""
        try:
            meta = self._registry.resolve(full_name)
        except ToolNotFoundError:
            meta = None
        except ToolResolveError as e:
            return RunResult.fail(str(e))

        if meta is None or meta.source == ToolSource.MCP:
            resp = daemon_request(
                DaemonRequest(
                    method="call_tool",
                    tool_name=meta.full_name if meta else full_name,
                    params=params,
                )
            )
            return RunResult(**resp.model_dump())

        try:
            params = validate_native_params(meta.full_name, params)
        except ValidationError as e:
            return RunResult.fail(f"Invalid params: {_format_validation_error(e)}")

        try:
            result = get_native_function(meta.full_name)(**params)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return RunResult.success(result)
        except Exception as e:
            logger.debug("Tool execution error", exc_info=True)
            return RunResult.fail(f"{type(e).__name__}: {e}")
