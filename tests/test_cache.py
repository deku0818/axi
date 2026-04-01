"""Embedding 缓存测试。"""

from pathlib import Path

from axi.search.cache import EmbeddingCache, content_hash


class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello") == content_hash("hello")

    def test_different_text(self):
        assert content_hash("hello") != content_hash("world")


class TestEmbeddingCache:
    def test_get_set(self, tmp_path: Path):
        cache = EmbeddingCache(tmp_path / "test.json")
        assert cache.get("k1") is None
        cache.set("k1", [0.1, 0.2, 0.3])
        assert cache.get("k1") == [0.1, 0.2, 0.3]

    def test_has(self, tmp_path: Path):
        cache = EmbeddingCache(tmp_path / "test.json")
        assert not cache.has("k1")
        cache.set("k1", [0.1])
        assert cache.has("k1")

    def test_persistence(self, tmp_path: Path):
        path = tmp_path / "test.json"
        cache1 = EmbeddingCache(path)
        cache1.set("k1", [1.0, 2.0])
        cache1.save()

        cache2 = EmbeddingCache(path)
        assert cache2.get("k1") == [1.0, 2.0]
