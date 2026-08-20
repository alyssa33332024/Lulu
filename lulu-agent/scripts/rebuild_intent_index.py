#!/usr/bin/env python
"""Rebuild intent vector index from data/intent_corpus.csv"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.knowledge import IntentVectorStore


def main() -> int:
    store = IntentVectorStore()
    n = store.rebuild_from_csv()
    print(f"indexed {n} rows → {store.INDEX_PATH} (embedder={store.embedder.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
