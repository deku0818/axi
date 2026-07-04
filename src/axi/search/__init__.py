"""搜索模块。

子模块按需直接 import（``from axi.search.bm25 import BM25Search``）。
此处不做包级 re-export，避免 ``import axi.search.cache`` 这类轻量导入
连带把 bm25s/jieba/numpy 拖进来——describe/run/list 完全用不到搜索栈。
"""
