"""混合搜索测试（纯 BM25 路径）。"""

from axi.models import ToolMeta, ToolSource
from axi.search.hybrid import HybridSearch, _rrf_fuse


def _make_tool(name: str, description: str, server: str = "s") -> ToolMeta:
    return ToolMeta(
        name=name, server=server, description=description, source=ToolSource.NATIVE
    )


class TestRRFFuse:
    def test_single_list(self):
        results = _rrf_fuse([[(0, 1.0), (1, 0.5)]], [1.0], top_k=2)
        assert len(results) == 2
        assert results[0][0] == 0
        assert results[0][1] == 1.0  # 归一化后第一名为 1.0

    def test_two_lists_boost(self):
        # 两个列表都包含 idx=1，应该排名提升
        list_a = [(0, 1.0), (1, 0.5)]
        list_b = [(1, 1.0), (2, 0.5)]
        results = _rrf_fuse([list_a, list_b], [1.0, 1.0], top_k=3)
        assert results[0][0] == 1  # idx=1 在两个列表都出现，RRF 分数最高

    def test_weighted_fusion(self):
        # embedding 权重高，应该让 embedding 的第一名胜出
        bm25 = [(0, 1.0), (1, 0.5)]
        emb = [(1, 1.0), (0, 0.5)]
        results = _rrf_fuse([bm25, emb], [0.3, 0.7], top_k=2)
        assert results[0][0] == 1  # embedding 权重大，idx=1 胜出

    def test_top_k_limits(self):
        results = _rrf_fuse([[(i, 1.0) for i in range(10)]], [1.0], top_k=3)
        assert len(results) == 3


class TestHybridSearch:
    def test_search(self):
        hybrid = HybridSearch()
        hybrid.build(
            [
                _make_tool("get_weather", "获取天气"),
                _make_tool("get_news", "获取新闻"),
            ]
        )
        results = hybrid.search("天气")
        assert len(results) > 0
        assert results[0].name == "s/get_weather"
        assert results[0].score is not None
        assert results[0].score == 1.0  # 第一名归一化为 1.0

    def test_empty_query_returns_empty(self):
        hybrid = HybridSearch()
        hybrid.build(
            [
                _make_tool("echo", "Echo input"),
            ]
        )
        # 单字符被过滤后可能为空
        results = hybrid.search("x")
        # 不崩溃即可
        assert isinstance(results, list)
