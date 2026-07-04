"""工具注册中心：管理所有工具元数据，提供搜索接口。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from axi.config import SearchConfig
from axi.models import SearchResult, ToolMeta
from axi.search.cache import EmbeddingCache
from axi.search.embedding import EmbeddingProvider, create_embedding_provider

if TYPE_CHECKING:
    from axi.search.hybrid import HybridSearch
    from axi.search.regex import RegexSearch


def split_names(value: str) -> list[str]:
    """解析逗号分隔的名称列表，忽略空段。"""
    return [n.strip() for n in value.split(",") if n.strip()]


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
        # 搜索引擎按需构建：bm25s/jieba/numpy 是重 import，describe/run/list
        # 完全用不到，延迟到 search()/grep() 首次调用时才付这笔冷启动成本。
        self._embedding_provider = embedding_provider
        self._embedding_cache = embedding_cache
        self._weight_bm25 = weight_bm25
        self._weight_embedding = weight_embedding
        self._regex: RegexSearch | None = None
        self._hybrid: HybridSearch | None = None
        # 工具集每变一次 _version +1；各引擎记住自己上次 build 的 version，
        # 只在落后时重建——晚建的引擎不再拖着已是最新的另一引擎陪跑一次。
        self._version = 0
        self._regex_version = -1
        self._hybrid_version = -1

    @classmethod
    def from_search_config(cls, cfg: SearchConfig) -> Registry:
        """按 axi.json 的 search 配置构建带混合搜索的 Registry。"""
        provider = create_embedding_provider(cfg.embedding)
        return cls(
            embedding_provider=provider,
            embedding_cache=EmbeddingCache() if provider else None,
            weight_bm25=cfg.weights.bm25,
            weight_embedding=cfg.weights.embedding,
        )

    def register(self, meta: ToolMeta) -> None:
        """注册一个工具。"""
        self._tools[meta.full_name] = meta
        self._version += 1

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
                raise ToolNotFoundError(
                    f"Tool not found: {name}. Use search to discover available tools."
                )
            return meta

        matches = [t for t in self._tools.values() if t.name == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            candidates = ", ".join(t.full_name for t in matches)
            raise AmbiguousToolError(
                f"Ambiguous tool name '{name}'. Use a full name: {candidates}"
            )
        raise ToolNotFoundError(
            f"Tool not found: {name}. Use search to discover available tools."
        )

    def list_all(self) -> list[ToolMeta]:
        """列出所有工具。"""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """列出所有工具的 full_name。"""
        return list(self._tools.keys())

    def server_tool_counts(self) -> dict[str, int]:
        """按 server 统计工具数量（无 server 归入 "unknown"）。"""
        return dict(Counter(m.server or "unknown" for m in self._tools.values()))

    def set_server(self, full_name: str, server: str) -> None:
        """更新工具的 server 名，同时更新注册 key。"""
        meta = self._tools.pop(full_name, None)
        if meta is None:
            return
        updated = meta.model_copy(update={"server": server})
        self._tools[updated.full_name] = updated
        self._version += 1

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """混合搜索工具（BM25 + Embedding）。"""
        if self._hybrid is None:
            from axi.search.hybrid import HybridSearch

            self._hybrid = HybridSearch(
                embedding_provider=self._embedding_provider,
                embedding_cache=self._embedding_cache,
                weight_bm25=self._weight_bm25,
                weight_embedding=self._weight_embedding,
            )
        if self._hybrid_version != self._version:
            self._hybrid.build(list(self._tools.values()))
            self._hybrid_version = self._version
        return self._hybrid.search(query, top_k=top_k)

    def grep(self, pattern: str, top_k: int = 10) -> list[SearchResult]:
        """正则表达式搜索工具。"""
        if self._regex is None:
            from axi.search.regex import RegexSearch

            self._regex = RegexSearch()
        if self._regex_version != self._version:
            self._regex.build(list(self._tools.values()))
            self._regex_version = self._version
        return self._regex.search(pattern, top_k=top_k)
