"""BGE-M3 Embedding 服务：本地 FlagEmbedding -> OpenAI 兼容 API -> 确定性降级向量。"""
import hashlib
import math
import random
import threading
from typing import List, Optional

import httpx

from ..utils.logger import get_logger

logger = get_logger(__name__)


class BGEEmbedder:
    """生成 1024 维查询/文档向量，带 LRU 结果缓存与三级降级。"""

    def __init__(self, config: dict):
        self.model_path: str = config.get("model_path") or "BAAI/bge-m3"
        self.api_url: str = (config.get("api_url") or "").rstrip("/")
        self.api_key: str = config.get("api_key", "")
        self.dim: int = int(config.get("dim", 1024))
        self.timeout: float = float(config.get("timeout", 10))
        self._model = None  # None=未尝试加载, False=不可用
        self._lock = threading.Lock()
        self._cache: dict = {}

    # ---------- 对外接口 ----------
    def embed(self, text: str) -> List[float]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        vec = self._embed_api(text) if self.api_url else self._embed_local(text)
        if vec is None:
            vec = self._embed_fallback(text)
        vec = self._normalize(vec)
        if len(self._cache) >= 4096:
            self._cache.clear()
        self._cache[text] = vec
        return vec

    # ---------- 1. OpenAI 兼容 Embedding API ----------
    def _embed_api(self, text: str) -> Optional[List[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = httpx.post(
                f"{self.api_url}/embeddings",
                json={"model": self.model_path, "input": text},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding API failed, fallback: %s", exc)
            return None

    # ---------- 2. 本地 FlagEmbedding（BGE-M3）----------
    def _embed_local(self, text: str) -> Optional[List[float]]:
        with self._lock:
            if self._model is None:
                try:
                    from FlagEmbedding import BGEM3FlagModel

                    self._model = BGEM3FlagModel(self.model_path, use_fp16=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("FlagEmbedding unavailable, fallback to hash embedder: %s", exc)
                    self._model = False
            if self._model is False:
                return None
        try:
            vecs = self._model.encode([text], batch_size=1)["dense_vecs"]
            return vecs[0].tolist()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local embedding failed, fallback: %s", exc)
            return None

    # ---------- 3. 确定性降级向量（仅联调/熔断使用）----------
    def _embed_fallback(self, text: str) -> List[float]:
        seed = hashlib.md5(text.encode("utf-8")).hexdigest()
        rng = random.Random(seed)
        return [rng.gauss(0.0, 1.0) for _ in range(self.dim)]

    @staticmethod
    def _normalize(vec: List[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
