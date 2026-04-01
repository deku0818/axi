"""BM25 搜索：封装 bm25s 库。"""

from __future__ import annotations

import bm25s

from axi.models import ToolMeta
from axi.search.tokenize import preprocess

# 默认 token_pattern 为 \w\w+ 会过滤单字 CJK token，改为允许单字符
_TOKEN_PATTERN = r"(?u)\b\w+\b"


class BM25Search:
    """基于 bm25s 的关键词搜索。"""

    def __init__(self) -> None:
        self._retriever: bm25s.BM25 | None = None
        self._tools: list[ToolMeta] = []

    def build(self, tools: list[ToolMeta]) -> None:
        """构建 BM25 索引。"""
        self._tools = tools
        if not tools:
            self._retriever = None
            return
        corpus = [preprocess(f"{t.full_name} {t.description}") for t in tools]
        corpus_tokens = bm25s.tokenize(
            corpus, token_pattern=_TOKEN_PATTERN, stopwords=None
        )
        self._retriever = bm25s.BM25()
        self._retriever.index(corpus_tokens)

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """搜索，返回 (工具索引, 分数) 列表。"""
        if not self._retriever or not self._tools:
            return []
        query_text = preprocess(query)
        if not query_text.strip():
            return []
        query_tokens = bm25s.tokenize(
            query_text, token_pattern=_TOKEN_PATTERN, stopwords=None
        )
        k = min(top_k, len(self._tools))
        results, scores = self._retriever.retrieve(query_tokens, k=k)
        return [
            (int(idx), float(score))
            for idx, score in zip(results[0], scores[0])
            if score > 0
        ]
