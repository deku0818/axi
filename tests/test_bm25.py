"""BM25 搜索测试。"""

from axi.models import ToolMeta, ToolSource
from axi.search.bm25 import BM25Search
from axi.search.tokenize import preprocess


def _make_tool(name: str, description: str, server: str = "s") -> ToolMeta:
    return ToolMeta(
        name=name, server=server, description=description, source=ToolSource.NATIVE
    )


class TestBM25Search:
    def test_exact_keyword_match_ranks_first(self):
        bm25 = BM25Search()
        bm25.build(
            [
                _make_tool("get_weather", "获取指定城市的天气信息"),
                _make_tool("get_news", "获取最新新闻列表"),
                _make_tool("set_alarm", "设置闹钟提醒"),
            ]
        )
        results = bm25.search("天气")
        assert len(results) > 0
        assert results[0][0] == 0  # get_weather 排第一

    def test_english_search(self):
        bm25 = BM25Search()
        bm25.build(
            [
                _make_tool("read_file", "Read contents of a file"),
                _make_tool("write_file", "Write data to a file"),
                _make_tool("delete_file", "Delete a file from disk"),
            ]
        )
        results = bm25.search("read")
        assert len(results) > 0
        assert results[0][0] == 0  # read_file 排第一

    def test_empty_corpus(self):
        bm25 = BM25Search()
        bm25.build([])
        results = bm25.search("anything")
        assert results == []

    def test_no_match(self):
        bm25 = BM25Search()
        bm25.build(
            [
                _make_tool("echo", "Echo back the input"),
            ]
        )
        results = bm25.search("zzzzxyz")
        assert results == []

    def test_tool_name_is_searchable(self):
        bm25 = BM25Search()
        bm25.build(
            [
                _make_tool("calculator", "A simple math tool"),
                _make_tool("echo", "Repeat input"),
            ]
        )
        results = bm25.search("calculator")
        assert len(results) > 0
        assert results[0][0] == 0

    def test_single_cjk_char_is_searchable(self):
        """单字 CJK token（如"图""行"）不应被分词器过滤。"""
        bm25 = BM25Search()
        bm25.build(
            [
                _make_tool("image_viewer", "看图说话工具"),
                _make_tool("echo", "回声测试"),
            ]
        )
        # jieba 将 "看图说话" 分词为 "看 图 说话"，"图" 作为独立 token 应可被搜索到
        results = bm25.search("图")
        assert len(results) > 0
        assert results[0][0] == 0  # image_viewer 排第一


class TestPreprocess:
    def test_keeps_single_cjk_char(self):
        result = preprocess("图")
        assert "图" in result

    def test_filters_single_ascii_char(self):
        result = preprocess("a")
        assert result.strip() == ""

    def test_mixed_cjk_and_ascii(self):
        result = preprocess("get_天气")
        assert "天气" in result
        assert "get" in result
