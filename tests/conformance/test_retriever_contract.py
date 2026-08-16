"""The suite every adapter must pass identically.

This is what makes a provider swap a comparison rather than a rewrite: if two
adapters both pass this unchanged, a difference in results is a difference in
retrieval quality and not a difference in behaviour.

Third parties: import `conformance_cases` and parametrise over your own adapter.
"""

from __future__ import annotations

import pytest

from judgeguard.adapters import Bm25Retriever, CannedRetriever
from judgeguard.contract import Identity, Passage, RetrievalResult, Retriever
from judgeguard.corpus import Corpus
from judgeguard.transcript import EVIDENCE_LEVELS, L1


@pytest.fixture(scope="module")
def corpus():
    return Corpus.load("corpus")


@pytest.fixture(params=["bm25", "canned"])
def adapter(request, corpus):
    builders = {"bm25": Bm25Retriever, "canned": CannedRetriever}
    return builders[request.param](corpus.documents)


def test_satisfies_the_protocol(adapter):
    assert isinstance(adapter, Retriever)


def test_declares_a_known_evidence_level(adapter):
    assert adapter.evidence_level in EVIDENCE_LEVELS


def test_returns_a_retrieval_result(adapter):
    result = adapter.retrieve("travel", identity=Identity("anon"), top_k=3)
    assert isinstance(result, RetrievalResult)
    assert result.provider == adapter.name
    assert all(isinstance(p, Passage) for p in result.passages)


def test_respects_top_k(adapter):
    result = adapter.retrieve("policy", identity=Identity("anon"), top_k=2)
    assert len(result.passages) <= 2


def test_is_deterministic_for_one_query(adapter):
    identity = Identity("anon")
    first = adapter.retrieve("retention", identity=identity, top_k=5)
    second = adapter.retrieve("retention", identity=identity, top_k=5)
    assert [p.id for p in first.passages] == [p.id for p in second.passages]


def test_l1_adapters_enforce_the_acl(adapter):
    """Only an adapter claiming L1 is asserted against real world state."""
    if adapter.evidence_level != L1:
        pytest.skip(f"{adapter.name} declares {adapter.evidence_level}, not gradable here")

    uncleared = Identity("analyst", frozenset())
    cleared = Identity("hr-lead", frozenset({"hr"}))

    denied = adapter.retrieve("band 4 salary ranges", identity=uncleared, top_k=5)
    assert all(not p.acl for p in denied.passages)

    allowed = adapter.retrieve("band 4 salary ranges", identity=cleared, top_k=5)
    assert any("hr" in p.acl for p in allowed.passages)
