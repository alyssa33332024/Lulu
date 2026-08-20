from __future__ import annotations

import hashlib
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Sequence

import httpx
from openai import OpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _l2(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


class Embedder:
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__


class HashingEmbedder(Embedder):
    """Offline fallback until Ark embedding endpoint is created in console."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            t = text.lower().strip()
            toks = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", t)
            for tok in toks:
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
                if len(tok) >= 2:
                    for i in range(len(tok) - 1):
                        big = tok[i : i + 2]
                        h2 = int(hashlib.md5(big.encode("utf-8")).hexdigest(), 16)
                        vec[h2 % self.dim] += 0.5
            out.append(_l2(vec))
        return out


class OllamaEmbedder(Embedder):
    """本地向量模型（bge-m3 等），走 ollama /api/embed。"""

    def __init__(self) -> None:
        s = get_settings()
        self.model = s.ollama_embedding_model.strip()
        self.host = s.ollama_host.rstrip("/")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            resp = client.post(
                f"{self.host}/api/embed",
                json={"model": self.model, "input": list(texts)},
            )
            resp.raise_for_status()
            vectors = resp.json().get("embeddings") or []
        if len(vectors) != len(texts):
            raise ValueError(f"ollama embed 返回 {len(vectors)} 条，期望 {len(texts)}")
        return [_l2([float(x) for x in v]) for v in vectors]

    @property
    def name(self) -> str:
        return f"OllamaEmbedder({self.model})"


class ArkEmbedder(Embedder):
    """方舟标准 /embeddings（文本模型）。"""

    def __init__(self) -> None:
        s = get_settings()
        self.model = s.ark_embedding_model
        self.client = OpenAI(base_url=s.ark_base_url, api_key=s.ark_api_key or "missing")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=list(texts))
        data = sorted(resp.data, key=lambda d: d.index)
        return [_l2(list(d.embedding)) for d in data]


class ArkMultimodalEmbedder(Embedder):
    """方舟多模态 embedding（/embeddings/multimodal）。

    该接口一次请求把整段 input 合成一个向量，批量文本必须逐条请求。
    """

    def __init__(self) -> None:
        s = get_settings()
        self.model = s.ark_embedding_model.strip()
        self.api_key = s.ark_api_key or "missing"
        self.url = s.ark_base_url.rstrip("/") + "/embeddings/multimodal"
        self._workers = 6

    def _one(self, text: str) -> list[float]:
        payload = {
            "model": self.model,
            "input": [{"type": "text", "text": text}],
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                self.url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
        data = body.get("data") or {}
        emb = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(emb, list) or not emb:
            raise ValueError(f"multimodal embed 无向量: {text[:40]!r}")
        return _l2([float(x) for x in emb])

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        if len(items) == 1:
            return [self._one(items[0])]
        out: list[list[float] | None] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=min(self._workers, len(items))) as pool:
            futs = {pool.submit(self._one, t): i for i, t in enumerate(items)}
            for fut in as_completed(futs):
                out[futs[fut]] = fut.result()
        if any(v is None for v in out):
            raise RuntimeError("multimodal embed 有条目失败")
        return out  # type: ignore[return-value]

    @property
    def name(self) -> str:
        return f"ArkMultimodalEmbedder({self.model})"


def _is_multimodal_model(name: str) -> bool:
    n = name.lower()
    return "vision" in n or "multimodal" in n or "embedding-vision" in n


def get_embedder() -> Embedder:
    """按 Ark → 本地 Ollama → 哈希兜底的顺序探活。"""
    s = get_settings()
    candidates: list[type[Embedder]] = []
    model = s.ark_embedding_model.strip()
    if model:
        candidates.append(ArkMultimodalEmbedder if _is_multimodal_model(model) else ArkEmbedder)
    if s.ollama_embedding_model.strip():
        candidates.append(OllamaEmbedder)
    for factory in candidates:
        try:
            emb = factory()
            emb.embed(["ping"])
            return emb
        except Exception:
            logger.warning("%s 不可用，继续探测下一个向量后端", factory.__name__, exc_info=True)
    return HashingEmbedder()
