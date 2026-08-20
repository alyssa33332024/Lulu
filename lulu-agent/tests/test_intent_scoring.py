import unittest

from app.services.knowledge import IntentVectorStore, _Candidate


class _CountingEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [list(self.vector) for _ in texts]


def _store(rows: list[dict], embedder: _CountingEmbedder) -> IntentVectorStore:
    store = IntentVectorStore.__new__(IntentVectorStore)
    store.embedder = embedder
    store.rows = rows
    store._build_bm25()
    return store


class IntentScoringTests(unittest.TestCase):
    def test_orders_by_weighted_score(self) -> None:
        store = IntentVectorStore.__new__(IntentVectorStore)
        pool = [
            _Candidate(query_id="1", query="唱一首歌", intent_id="sing", vector=[1.0, 0.0]),
            _Candidate(query_id="2", query="设个闹钟", intent_id="reminder", vector=[0.0, 1.0]),
        ]
        store._score_final("提醒我开会", [0.0, 1.0], pool)

        self.assertEqual([c.intent_id for c in pool], ["reminder", "sing"])
        self.assertGreater(pool[0].final_score, pool[1].final_score)

    def test_search_embeds_query_once(self) -> None:
        """定序复用召回阶段的向量：一次检索只能有一次 embed 往返。"""
        embedder = _CountingEmbedder([1.0, 0.0])
        store = _store(
            [
                {"query_id": "1", "query": "唱一首歌", "intent_id": "sing", "vector": [1.0, 0.0]},
                {"query_id": "2", "query": "提醒我开会", "intent_id": "reminder", "vector": [0.0, 1.0]},
            ],
            embedder,
        )

        hits = store.search("唱一首歌")

        self.assertEqual(embedder.calls, 1)
        self.assertEqual([h.intent_id for h in hits], ["sing"])


if __name__ == "__main__":
    unittest.main()
