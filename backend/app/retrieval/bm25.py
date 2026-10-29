from __future__ import annotations

import math
from collections import Counter

from .textutil import tokenize


class BM25:
    """Okapi BM25 with a compact inverted index.

    Works per-document; ranks are fused across documents with RRF, so per-document
    IDF differences do not distort the merged ordering.
    """

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs_tokens = [tokenize(doc) for doc in documents]
        self.doc_len = [len(tokens) for tokens in self.docs_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self.term_freqs = [Counter(tokens) for tokens in self.docs_tokens]
        df: Counter[str] = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        n = len(documents)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        self.n = n

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        if not terms or not self.n:
            return [0.0] * self.n
        scores = [0.0] * self.n
        for term in terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.term_freqs):
                freq = tf.get(term)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * (self.doc_len[i] / (self.avg_len or 1)))
                scores[i] += idf * (freq * (self.k1 + 1)) / denom
        return scores

    def term_coverage(self, query: str, index: int) -> float:
        terms = set(tokenize(query))
        if not terms:
            return 0.0
        present = [t for t in terms if self.term_freqs[index].get(t)]
        weighted = sum(self.idf.get(t, 1.0) for t in present)
        total = sum(self.idf.get(t, 1.0) for t in terms)
        return weighted / total if total else 0.0
