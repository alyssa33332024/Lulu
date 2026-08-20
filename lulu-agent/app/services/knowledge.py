from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import ROOT
from app.core.enums import IntentId
from app.services.embedding import Embedder, get_embedder

# 意图混合检索：dense + BM25 → RRF → 本地加权定序（全程只 embed 一次 query）
# 有真实语义向量后以 dense 为主；BM25 只作弱补充，避免单字/二元组撞车
RETRIEVAL_CFG: dict[str, Any] = {
    "dense_recall_k": 20,
    "sparse_recall_k": 20,
    "rrf_k": 60,
    "score_pool_k": 12,
    "final_top_k": 3,
    "final_min_score": 0.40,
    "dense_min_score": 0.45,
    "score_weights": {"dense": 0.72, "bm25": 0.18, "overlap": 0.10},
}

KEYWORD_PATTERNS: list[tuple[str, list[str]]] = [
    (IntentId.SING.value, [r"唱", r"来首", r"放歌", r"听歌", r"one last time", r"歌曲"]),
    (IntentId.REMINDER.value, [r"提醒", r"闹钟", r"叫我", r"日程", r"开盘"]),
    (IntentId.CHAT.value, [r"你好", r"嗨", r"在吗", r"聊天"]),
]


def _tokenize(text: str) -> list[str]:
    """中文取二元组：单字粒度太糙，「我不想看」会靠一个「想」字命中「想听歌」。

    孤立单字（如「唱」）没有二元组，仍按单字保留。
    """
    t = (text or "").lower().strip()
    if not t:
        return []
    tokens = re.findall(r"[a-z0-9]+", t)
    for run in re.findall(r"[\u4e00-\u9fff]+", t):
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


class _BM25Index:
    def __init__(self, documents: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = documents
        self.doc_len = [len(d) for d in documents]
        self.avgdl = sum(self.doc_len) / len(documents) if documents else 0.0
        self.df: Counter[str] = Counter()
        for doc in documents:
            for term in set(doc):
                self.df[term] += 1
        self.n_docs = len(documents)

    def score_document(self, query_tokens: list[str], doc_idx: int) -> float:
        if not query_tokens or doc_idx >= len(self.docs):
            return 0.0
        doc = self.docs[doc_idx]
        if not doc:
            return 0.0
        tf = Counter(doc)
        dl = self.doc_len[doc_idx]
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            freq = tf[term]
            df = self.df.get(term, 0)
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
            score += idf * (freq * (self.k1 + 1)) / (denom or 1.0)
        return score

    def search(self, query: str, top_k: int = 20) -> list[tuple[int, float]]:
        q_tokens = _tokenize(query)
        if not q_tokens or not self.docs:
            return []
        scored = [(i, self.score_document(q_tokens, i)) for i in range(len(self.docs))]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


@dataclass
class VectorHit:
    query_id: str
    query: str
    intent_id: str
    score: float
    dense_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0


@dataclass
class IntentHit:
    query_id: str
    query: str
    intent_id: str
    score: float
    dense_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0


@dataclass
class _Candidate:
    query_id: str
    query: str
    intent_id: str
    vector: list[float]
    dense_score: float = 0.0
    bm25_score: float = 0.0
    rrf_score: float = 0.0
    final_score: float = 0.0


class IntentVectorStore:
    """意图语料索引：CSV 建库 → intent_index.json；检索走混合召回。"""

    INDEX_PATH = ROOT / "data" / "intent_index.json"
    CORPUS_PATH = ROOT / "data" / "intent_corpus.csv"

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or get_embedder()
        self.rows: list[dict] = []
        self._bm25: _BM25Index | None = None
        if self.INDEX_PATH.exists():
            raw = json.loads(self.INDEX_PATH.read_text(encoding="utf-8"))
            self.rows = raw.get("rows") or []
            self._build_bm25()

    @property
    def ready(self) -> bool:
        return bool(self.rows)

    def rebuild_from_csv(self, csv_path: Path | None = None) -> int:
        import csv

        csv_path = csv_path or self.CORPUS_PATH
        texts: list[str] = []
        meta: list[dict] = []
        seen_ids: set[str] = set()
        with csv_path.open(encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), start=1):
                q = (row.get("query") or "").strip()
                intent = (row.get("intent_id") or "").strip()
                if not q or not intent:
                    continue
                query_id = (row.get("query_id") or "").strip() or str(i)
                if query_id in seen_ids:
                    raise ValueError(f"duplicate query_id: {query_id}")
                seen_ids.add(query_id)
                texts.append(q)
                meta.append({"query_id": query_id, "query": q, "intent_id": intent})
        vectors = self.embedder.embed(texts)
        self.rows = [{**m, "vector": v, "embedder": self.embedder.name} for m, v in zip(meta, vectors)]
        self.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.INDEX_PATH.write_text(
            json.dumps(
                {"embedder": self.embedder.name, "dim": len(vectors[0]) if vectors else 0, "rows": self.rows},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._build_bm25()
        return len(self.rows)

    def _score_final(self, query: str, qv: list[float], pool: list[_Candidate]) -> None:
        """RRF 候选定序：dense + BM25 + token overlap 加权，复用已算好的 query 向量。"""
        weights = RETRIEVAL_CFG["score_weights"]
        q_tokens = set(_tokenize(query))
        bm25_max = max((c.bm25_score for c in pool), default=0.0)
        for cand in pool:
            dense = _cosine(qv, cand.vector) if cand.vector else cand.dense_score
            bm25_norm = (cand.bm25_score / bm25_max) if bm25_max > 0 else 0.0
            overlap = len(q_tokens & set(_tokenize(cand.query))) / max(len(q_tokens), 1)
            cand.dense_score = dense
            cand.final_score = (
                float(weights["dense"]) * dense
                + float(weights["bm25"]) * bm25_norm
                + float(weights["overlap"]) * overlap
            )
        pool.sort(key=lambda c: c.final_score, reverse=True)

    def search(self, query: str, top_k: int | None = None, min_score: float | None = None) -> list[VectorHit]:
        if not self.rows:
            return []
        cfg = RETRIEVAL_CFG
        final_k = top_k or int(cfg["final_top_k"])
        qv = self.embedder.embed([query])[0]
        pool = self._rrf_merge(
            self._search_dense(qv, int(cfg["dense_recall_k"]), float(cfg["dense_min_score"] if min_score is None else min_score)),
            self._search_sparse(query, int(cfg["sparse_recall_k"])),
            int(cfg["rrf_k"]),
        )[: int(cfg["score_pool_k"])]

        self._score_final(query, qv, pool)
        final_min = float(cfg["final_min_score"])
        dense_min = float(cfg["dense_min_score"])
        # chat 语料参与竞争：若语义上更像闲聊，就不输出技能命中
        best_chat_dense = max(
            (c.dense_score for c in pool if c.intent_id == IntentId.CHAT.value),
            default=-1.0,
        )
        out: list[VectorHit] = []
        for cand in pool:
            if cand.intent_id == IntentId.CHAT.value:
                continue
            if cand.final_score < final_min or cand.dense_score < dense_min:
                continue
            if best_chat_dense >= 0 and cand.dense_score <= best_chat_dense:
                continue
            out.append(
                VectorHit(
                    query_id=cand.query_id,
                    query=cand.query,
                    intent_id=cand.intent_id,
                    score=cand.final_score,
                    dense_score=cand.dense_score,
                    bm25_score=cand.bm25_score,
                    rrf_score=cand.rrf_score,
                )
            )
            if len(out) >= final_k:
                break
        return out

    def _build_bm25(self) -> None:
        docs = [_tokenize(r.get("query") or "") for r in self.rows]
        self._bm25 = _BM25Index(docs) if docs else None

    def _search_dense(self, qv: list[float], top_k: int, min_score: float) -> list[_Candidate]:
        scored: list[_Candidate] = []
        for row in self.rows:
            vector = row.get("vector") or []
            dense = _cosine(qv, vector)
            if dense < min_score:
                continue
            scored.append(
                _Candidate(
                    query_id=str(row.get("query_id") or ""),
                    query=row.get("query") or "",
                    intent_id=row.get("intent_id") or "",
                    vector=vector,
                    dense_score=dense,
                )
            )
        scored.sort(key=lambda c: c.dense_score, reverse=True)
        return scored[:top_k]

    def _search_sparse(self, query: str, top_k: int) -> list[_Candidate]:
        if not self._bm25:
            return []
        out: list[_Candidate] = []
        for doc_idx, bm25_score in self._bm25.search(query, top_k=top_k):
            row = self.rows[doc_idx]
            out.append(
                _Candidate(
                    query_id=str(row.get("query_id") or ""),
                    query=row.get("query") or "",
                    intent_id=row.get("intent_id") or "",
                    vector=row.get("vector") or [],
                    bm25_score=bm25_score,
                )
            )
        return out

    def _rrf_merge(self, dense: list[_Candidate], sparse: list[_Candidate], rrf_k: int) -> list[_Candidate]:
        scores: dict[str, float] = {}
        meta: dict[str, _Candidate] = {}
        for rank, cand in enumerate(dense):
            scores[cand.query_id] = scores.get(cand.query_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            meta.setdefault(cand.query_id, cand)
            meta[cand.query_id].dense_score = max(meta[cand.query_id].dense_score, cand.dense_score)
        for rank, cand in enumerate(sparse):
            scores[cand.query_id] = scores.get(cand.query_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            if cand.query_id in meta:
                meta[cand.query_id].bm25_score = max(meta[cand.query_id].bm25_score, cand.bm25_score)
            else:
                meta[cand.query_id] = cand
        merged = []
        for qid, rrf in scores.items():
            meta[qid].rrf_score = rrf
            merged.append(meta[qid])
        merged.sort(key=lambda c: c.rrf_score, reverse=True)
        return merged


class KnowledgeService:
    """意图证据召回：混合检索 + 关键词兜底。"""

    def __init__(self) -> None:
        self.store = IntentVectorStore()
        if not self.store.ready:
            try:
                self.store.rebuild_from_csv()
            except Exception:
                pass

    def recall(self, query: str, top_k: int | None = None) -> list[IntentHit]:
        top_k = top_k or int(RETRIEVAL_CFG["final_top_k"])
        hits = [
            IntentHit(
                query_id=vh.query_id,
                query=vh.query,
                intent_id=vh.intent_id,
                score=vh.score,
                dense_score=vh.dense_score,
                bm25_score=vh.bm25_score,
                rrf_score=vh.rrf_score,
            )
            for vh in self.store.search(query, top_k=top_k)
        ]
        self._keyword_safety_net(query, hits)
        hits.sort(key=lambda h: h.score, reverse=True)
        return [h for h in hits if h.intent_id != IntentId.CHAT.value][:top_k]

    def _keyword_safety_net(self, query: str, hits: list[IntentHit]) -> None:
        q = query.lower()
        for intent_id, pats in KEYWORD_PATTERNS:
            score = max((0.88 if len(p) > 1 else 0.7 for p in pats if re.search(p, q, flags=re.I)), default=0.0)
            if score <= 0 or intent_id == IntentId.CHAT.value:
                continue
            existing = next((h for h in hits if h.query_id and h.intent_id == intent_id), None)
            if existing:
                existing.score = max(existing.score, score)
            else:
                hits.append(IntentHit(query_id="", query=query, intent_id=intent_id, score=score))
