"""正则表达式搜索实现。"""

import re

from axi.models import SearchResult, ToolMeta


class RegexSearch:
    """基于正则表达式的工具搜索。"""

    def __init__(self) -> None:
        self._tools: list[ToolMeta] = []

    def build(self, tools: list[ToolMeta]) -> None:
        self._tools = tools

    def search(self, pattern: str, top_k: int = 10) -> list[SearchResult]:
        """用正则匹配工具名和描述。"""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern {pattern!r}: {e}") from e

        results = []
        for tool in self._tools:
            if compiled.search(tool.full_name) or compiled.search(tool.description):
                results.append(
                    SearchResult(
                        name=tool.full_name,
                        description=tool.description,
                        source=tool.source,
                    )
                )
                if len(results) >= top_k:
                    break
        return results
