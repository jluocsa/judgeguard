"""BM25 retrieval over an in-memory corpus, with the ACL filter applied first.

Filtering before scoring is deliberate: it mirrors a query-time metadata filter in
a search service, so the authorization assertion tests the same observable outcome
regardless of which provider is bound.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter

from ..contract import Identity, Passage, RetrievalResult
from ..corpus import Document
from ..transcript import L1

TOKEN = re.compile(r"\w+")
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class Bm25Retriever:
    name = "bm25"
    evidence_level = L1

    def __init__(self, documents: tuple[Document, ...]):
        self._documents = documents
        self._tokens = {d.id: tokenize(d.text) for d in documents}
        lengths = [len(t) for t in self._tokens.values()] or [0]
        self._avg_len = sum(lengths) / len(lengths)
        self._df: Counter[str] = Counter()
        for tokens in self._tokens.values():
            self._df.update(set(tokens))

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult:
        started = time.perf_counter()
        terms = tokenize(query)
        visible = [d for d in self._documents if identity.may_read(d.acl)]
        n = len(self._documents) or 1

        scored: list[tuple[float, Document]] = []
        for document in visible:
            tokens = self._tokens[document.id]
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                idf = math.log(
                    (n - self._df[term] + 0.5) / (self._df[term] + 0.5) + 1.0
                )
                denominator = frequency + K1 * (
                    1 - B + B * length / (self._avg_len or 1)
                )
                score += idf * (frequency * (K1 + 1)) / denominator
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        passages = tuple(
            Passage(
                id=document.id,
                text=document.text,
                source=document.source,
                score=round(score, 4),
                acl=document.acl,
            )
            for score, document in scored[:top_k]
        )
        return RetrievalResult(
            provider=self.name,
            passages=passages,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
