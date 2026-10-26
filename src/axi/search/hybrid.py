"""混合搜索：BM25 + Embedding，RRF 融合。"""

from __future__ import annotations

import logging

from axi.models import SearchResult, ToolMeta
from axi.search.bm25 import BM25Search
from axi.search.cache import EmbeddingCache
from axi.search.embedding import EmbeddingProvider, EmbeddingSearch

logger = logging.getLogger(__name__)

# RRF 平滑常数（标准值 60，值越大排名差异越平滑）
RRF_K = 60


def _rrf_fuse(
    ranked_lists: list[list[tuple[int, float]]],
    weights: list[float],
    top_k: int,
) -> list[tuple[int, float]]:
    """加权 Reciprocal Rank Fusion：按排名合并多个排序列表。"""
    scores: dict[int, float] = {}
    for ranked, weight in zip(ranked_lists, weights):
        for rank, (idx, _score) in enumerate(ranked):
            scores[idx] = scores.get(idx, 0.0) + weight / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]


class HybridSearch:
    """BM25 + Embedding 混合搜索。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_cache: EmbeddingCache | None = None,
        weight_bm25: float = 0.3,
        weight_embedding: float = 0.7,
    ) -> None:
        self._bm25 = BM25Search()
        self._embedding: EmbeddingSearch | None = None
        if embedding_provider and embedding_cache:
            self._embedding = EmbeddingSearch(embedding_provider, embedding_cache)
        self._weight_bm25 = weight_bm25
        self._weight_embedding = weight_embedding
        self._tools: list[ToolMeta] = []

    def build(self, tools: list[ToolMeta]) -> None:
        """构建所有索引。"""
        self._tools = tools
        self._bm25.build(tools)
        if self._embedding:
            try:
                self._embedding.build(tools)
            except Exception as e:
                logger.warning(
                    "Embedding 索引构建失败，降级为纯 BM25: %s", e, exc_info=True
                )
                self._embedding = None

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """混合搜索：BM25 + Embedding 加权 RRF 融合。"""
        scored = self._bm25.search(query, top_k=top_k)

        if self._embedding:
            try:
                emb_results = self._embedding.search_with_query(query, top_k=top_k)
                scored = _rrf_fuse(
                    [scored, emb_results],
                    [self._weight_bm25, self._weight_embedding],
                    top_k=top_k,
                )
            except Exception as e:
                logger.warning(
                    "Embedding 搜索失败，降级为纯 BM25: %s", e, exc_info=True
                )

        return [
            SearchResult(
                name=self._tools[idx].full_name,
                description=self._tools[idx].description,
                source=self._tools[idx].source,
            )
            for idx, _score in scored
        ]
