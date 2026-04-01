"""Embedding 文件缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".axi/cache")
CACHE_FILE = CACHE_DIR / "embeddings.json"


def content_hash(text: str) -> str:
    """对文本内容取 MD5 作为缓存 key。"""
    return hashlib.md5(text.encode()).hexdigest()


class EmbeddingCache:
    """基于文件的 embedding 缓存。"""

    def __init__(self, path: Path = CACHE_FILE) -> None:
        self._path = path
        self._data: dict[str, list[float]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                if isinstance(data, dict):
                    self._data = data
                else:
                    logger.warning("Invalid cache format in %s, resetting", self._path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Failed to load embedding cache %s: %s, resetting", self._path, e
                )

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data))

    def get(self, key: str) -> list[float] | None:
        return self._data.get(key)

    def set(self, key: str, vector: list[float]) -> None:
        self._data[key] = vector

    def has(self, key: str) -> bool:
        return key in self._data
