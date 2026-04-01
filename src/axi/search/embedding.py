"""Embedding 搜索：向量相似度匹配。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from axi.models import ToolMeta
from axi.search.cache import EmbeddingCache, content_hash

if TYPE_CHECKING:
    from axi.config import EmbeddingConfig


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embedding provider 接口，兼容 LangChain Embeddings。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def create_embedding_provider(
    embedding_config: EmbeddingConfig,
) -> EmbeddingProvider | None:
    """根据配置创建 embedding provider。"""
    if not embedding_config.provider:
        return None

    if embedding_config.provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict[str, Any] = {}
        if embedding_config.api_key:
            kwargs["api_key"] = embedding_config.api_key
        if embedding_config.model:
            kwargs["model"] = embedding_config.model
        if embedding_config.base_url:
            kwargs["base_url"] = embedding_config.base_url
        return OpenAIEmbeddings(**kwargs)  # type: ignore[return-value]

    if embedding_config.provider == "jina":
        from langchain_community.embeddings import JinaEmbeddings

        kwargs = {}
        if embedding_config.api_key:
            kwargs["jina_api_key"] = embedding_config.api_key
        if embedding_config.model:
            kwargs["model_name"] = embedding_config.model
        return JinaEmbeddings(**kwargs)  # type: ignore[return-value]

    raise ValueError(
        f"Unknown embedding provider: '{embedding_config.provider}'. "
        f"Supported: 'openai', 'jina'"
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingSearch:
    """基于向量相似度的搜索。"""

    def __init__(self, provider: EmbeddingProvider, cache: EmbeddingCache) -> None:
        self._provider = provider
        self._cache = cache
        self._tools: list[ToolMeta] = []
        self._vectors: list[list[float]] = []

    def build(self, tools: list[ToolMeta]) -> None:
        """构建 embedding 索引：优先从缓存读取，缺失的批量调 API。"""
        self._tools = tools
        self._vectors = []

        texts = [f"{t.full_name} {t.description}" for t in tools]
        hashes = [content_hash(t) for t in texts]

        # 分离命中/未命中
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        cached_vectors: dict[int, list[float]] = {}

        for i, h in enumerate(hashes):
            vec = self._cache.get(h)
            if vec is not None:
                cached_vectors[i] = vec
            else:
                missing_indices.append(i)
                missing_texts.append(texts[i])

        # 批量请求缺失的 embedding
        if missing_texts:
            new_vectors = self._provider.embed_documents(missing_texts)
            for idx, vec in zip(missing_indices, new_vectors):
                cached_vectors[idx] = vec
                self._cache.set(hashes[idx], vec)
            self._cache.save()

        # 按顺序排列
        self._vectors = [cached_vectors[i] for i in range(len(tools))]

    def search_with_query(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """搜索，返回 (工具索引, 相似度) 列表。"""
        if not self._vectors:
            return []
        query_vec = self._provider.embed_query(query)
        scored = [
            (i, _cosine_similarity(query_vec, vec))
            for i, vec in enumerate(self._vectors)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scored[:top_k] if s > 0]
