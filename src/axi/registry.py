"""工具注册中心：管理所有工具元数据，提供搜索接口。"""

from __future__ import annotations

from axi.models import SearchResult, ToolMeta
from axi.search.cache import EmbeddingCache
from axi.search.embedding import EmbeddingProvider
from axi.search.hybrid import HybridSearch
from axi.search.regex import RegexSearch


class ToolResolveError(Exception):
    """工具名解析失败（未找到或存在歧义）。"""


class ToolNotFoundError(ToolResolveError):
    """工具未找到。"""


class AmbiguousToolError(ToolResolveError):
    """工具名存在歧义。"""


class Registry:
    """axi 的工具注册中心。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_cache: EmbeddingCache | None = None,
        weight_bm25: float = 0.3,
        weight_embedding: float = 0.7,
    ) -> None:
        self._tools: dict[str, ToolMeta] = {}
        self._regex = RegexSearch()
        self._hybrid = HybridSearch(
            embedding_provider=embedding_provider,
            embedding_cache=embedding_cache,
            weight_bm25=weight_bm25,
            weight_embedding=weight_embedding,
        )
        self._dirty = True

    def register(self, meta: ToolMeta) -> None:
        """注册一个工具。"""
        self._tools[meta.full_name] = meta
        self._dirty = True

    def get(self, full_name: str) -> ToolMeta | None:
        """按完整名称获取工具元数据。"""
        return self._tools.get(full_name)

    def resolve(self, name: str) -> ToolMeta:
        """解析工具名：支持完整名称和短名称。

        - 含 ``/`` → 按 full_name 精确查找
        - 不含 ``/`` → 在所有工具的 ``.name`` 中精确匹配
          - 唯一匹配 → 返回
          - 多个匹配 → 抛 ToolResolveError，列出所有候选
          - 无匹配 → 抛 ToolResolveError
        """
        if "/" in name:
            meta = self._tools.get(name)
            if meta is None:
                raise ToolNotFoundError(f"Tool not found: {name}")
            return meta

        matches = [t for t in self._tools.values() if t.name == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            candidates = ", ".join(t.full_name for t in matches)
            raise AmbiguousToolError(
                f"Ambiguous tool name '{name}', candidates: {candidates}"
            )
        raise ToolNotFoundError(f"Tool not found: {name}")

    def list_all(self) -> list[ToolMeta]:
        """列出所有工具。"""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """列出所有工具的 full_name。"""
        return list(self._tools.keys())

    def set_server(self, full_name: str, server: str) -> None:
        """更新工具的 server 名，同时更新注册 key。"""
        meta = self._tools.pop(full_name, None)
        if meta is None:
            return
        updated = meta.model_copy(update={"server": server})
        self._tools[updated.full_name] = updated
        self._dirty = True

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """混合搜索工具（BM25 + Embedding）。"""
        self._rebuild_index()
        return self._hybrid.search(query, top_k=top_k)

    def grep(self, pattern: str, top_k: int = 10) -> list[SearchResult]:
        """正则表达式搜索工具。"""
        self._rebuild_index()
        return self._regex.search(pattern, top_k=top_k)

    def _rebuild_index(self) -> None:
        if not self._dirty:
            return
        tools = list(self._tools.values())
        self._regex.build(tools)
        self._hybrid.build(tools)
        self._dirty = False
