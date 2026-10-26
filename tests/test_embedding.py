"""离线验证 embedding 故障降级和模型/端点切换后的缓存隔离。"""

import httpx
import pytest
from openai import APIConnectionError, RateLimitError

from axi.config import SearchConfig
from axi.models import ToolMeta, ToolSource
from axi.registry import Registry
from axi.search.cache import EmbeddingCache
from axi.search.hybrid import HybridSearch


def _tools():
    return [
        ToolMeta(name=name, server="demo", description=name, source=ToolSource.NATIVE)
        for name in ("alpha", "beta")
    ]


@pytest.mark.parametrize(
    "field,changed",
    [("model", "new-model"), ("baseUrl", "https://new.invalid"), ("provider", "jina")],
)
def test_registry_cache_separates_vector_spaces(tmp_path, monkeypatch, field, changed):
    cache_path = tmp_path / "vectors.json"
    calls = []
    original = {
        "provider": "openai",
        "model": "old-model",
        "baseUrl": "https://old.invalid",
        "apiKey": "not-for-cache",
    }

    class Provider:
        def __init__(self, switched):
            self.switched = switched

        def embed_documents(self, texts):
            calls.append(self.switched)
            return (
                [[0.0, 1.0], [1.0, 0.0]] if self.switched else [[1.0, 0.0], [0.0, 1.0]]
            )

        def embed_query(self, text):
            return [1.0, 0.0]

    attribute = "base_url" if field == "baseUrl" else field
    monkeypatch.setattr(
        "axi.registry.create_embedding_provider",
        lambda cfg: Provider(getattr(cfg, attribute) == changed),
    )
    monkeypatch.setattr(
        "axi.registry.EmbeddingCache",
        lambda *, namespace: EmbeddingCache(cache_path, namespace=namespace),
    )
    for config, expected in (
        (original, "demo/alpha"),
        ({**original, field: changed}, "demo/beta"),
        ({**original, field: changed}, "demo/beta"),
    ):
        registry = Registry.from_search_config(
            SearchConfig.model_validate({"embedding": config})
        )
        for tool in _tools():
            registry.register(tool)
        assert registry.search("unmatched")[0].name == expected
    assert calls == [False, True]
    assert "not-for-cache" not in cache_path.read_text()


@pytest.mark.parametrize("stage", ["build", "query"])
@pytest.mark.parametrize("error_type", [APIConnectionError, RateLimitError])
def test_sdk_errors_fall_back_to_bm25(tmp_path, stage, error_type):
    request = httpx.Request("POST", "https://example.invalid/embeddings")
    if error_type is APIConnectionError:
        error = APIConnectionError(request=request)
    else:
        error = RateLimitError(
            "rate limit", response=httpx.Response(429, request=request), body={}
        )

    class Provider:
        def embed_documents(self, texts):
            if stage == "build":
                raise error
            return [[1.0, 0.0], [0.0, 1.0]]

        def embed_query(self, text):
            raise error

    search = HybridSearch(Provider(), EmbeddingCache(tmp_path / "cache.json"))
    search.build(_tools())
    assert search.search("alpha")[0].name == "demo/alpha"
