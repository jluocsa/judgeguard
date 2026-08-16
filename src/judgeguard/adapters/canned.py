"""A retriever whose results are canned and whose ACL filter does not exist.

This is not a straw man. It is the shape of an evaluation harness whose tools are
schema-identical no-ops with fixed results, which is where most teams start. It
declares L0 so that every check needing real world state reports `ungradable`
rather than a pass nobody should trust.
"""

from __future__ import annotations

from ..contract import Identity, Passage, RetrievalResult
from ..corpus import Document
from ..transcript import L0


class CannedRetriever:
    name = "canned"
    evidence_level = L0

    def __init__(self, documents: tuple[Document, ...], fixed: int = 3):
        self._fixed = tuple(documents[:fixed])

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult:
        passages = tuple(
            Passage(
                id=d.id, text=d.text, source=d.source, score=1.0, acl=d.acl
            )
            for d in self._fixed[:top_k]
        )
        return RetrievalResult(provider=self.name, passages=passages, latency_ms=0.0)
