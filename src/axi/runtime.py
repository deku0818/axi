"""CLI 与 Python PTC 共用的进程内工具状态。"""

from axi.executor import Executor
from axi.registry import Registry

registry = Registry()
executor = Executor(registry)
