#!/usr/bin/env python3
"""评估意图混合检索命中率。

intent_rag_eval.json 只需 query + expect，不需 embedding：
  - 语料向量在 intent_index.json（由 intent_corpus.csv 预计算）
  - 评测时对每条 query 实时 embed，走与线上一致的 KnowledgeService.recall()
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.knowledge import KnowledgeService


def main() -> int:
    dataset = ROOT / "data" / "intent_rag_eval.json"
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    svc = KnowledgeService()
    ok = 0
    for case in cases:
        query = case["query"]
        expect = set(case.get("expect") or [])
        hits = svc.recall(query, top_k=5)
        got = {h.intent_id for h in hits}
        # chat：期望 chat 且 hits 为空或只有 chat 也算对
        if "chat" in expect:
            passed = not got or got <= {"chat"}
        else:
            passed = bool(got & expect)
        mark = "OK" if passed else "FAIL"
        if passed:
            ok += 1
        detail = [
            f"{h.intent_id}({h.score:.2f}|d{h.dense_score:.2f}|b{h.bm25_score:.2f})"
            for h in hits[:3]
        ]
        print(f"[{mark}] {query!r} expect={sorted(expect)} got={detail}")
    print(f"\n{ok}/{len(cases)} passed")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
