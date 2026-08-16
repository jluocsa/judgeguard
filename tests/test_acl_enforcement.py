"""Authorization has to survive the plumbing.

Both failures here were silent. A clearance containing an apostrophe was dropped
from the search filter rather than escaped, which narrows what the caller can see
and reads downstream as a retrieval quality problem. And the leakage check matched
forbidden entries against a passage's id only, so a case that named a source path -
the same identifier the corpus uses in its `source` field - passed while the
forbidden document sat in the passage list.
"""

from __future__ import annotations

import pytest

from judgeguard.adapters.azure_search import AzureSearchRetriever
from judgeguard.contract import Identity
from judgeguard.corpus import Case
from judgeguard.lanes.checks.leakage import leakage
from judgeguard.lanes.deterministic import FAIL, PASS
from judgeguard.transcript import L1, Transcript


@pytest.fixture
def retriever():
    """The filter is pure string work; building it needs no client and no network."""
    instance = object.__new__(AzureSearchRetriever)
    instance._acl_field = "acl"
    return instance


def identity(*clearances: str) -> Identity:
    return Identity(principal="tester", clearances=frozenset(clearances))


# --- the search filter ------------------------------------------------------


def test_a_quoted_clearance_is_escaped_not_discarded(retriever):
    expression = retriever._filter(identity("o'brien-team"))
    assert "o''brien-team" in expression
    assert expression.count("'") % 2 == 0, "unbalanced quotes would be rejected"


def test_no_clearance_is_dropped_from_the_filter(retriever):
    clearances = {"hr", "legal-o'connor", "finance"}
    expression = retriever._filter(identity(*clearances))
    assert expression.count("c eq ") == len(clearances)


def test_an_uncleared_caller_sees_only_unrestricted_documents(retriever):
    assert retriever._filter(identity()) == "not acl/any()"


def test_the_unrestricted_clause_is_written_one_way(retriever):
    """Two spellings of the same predicate is one spelling too many to review."""
    uncleared = retriever._filter(identity())
    cleared = retriever._filter(identity("hr"))
    assert uncleared in cleared


# --- the leakage check ------------------------------------------------------


def transcript_with(passage: dict, answer: str = "redacted") -> Transcript:
    return Transcript(
        case_id="c",
        query="q",
        principal="analyst",
        provider="stub",
        evidence_level=L1,
        passages=[passage],
        answer=answer,
    )


def case_forbidding(*sources: str) -> Case:
    return Case(
        id="c",
        query="q",
        identity=identity(),
        forbidden_sources=tuple(sources),
    )


PASSAGE = {
    "id": "doc-salary-bands",
    "source": "restricted/salary-bands",
    "text": "Band 4 ranges from 125000 to 175000 units.",
}


@pytest.mark.parametrize(
    "forbidden", ["doc-salary-bands", "restricted/salary-bands"]
)
def test_forbidden_material_is_caught_by_id_or_by_source(forbidden):
    result = leakage(transcript_with(PASSAGE), case_forbidding(forbidden))
    assert result.status == FAIL
    assert forbidden in result.detail


def test_an_unrelated_passage_does_not_trip_the_check():
    allowed = {"id": "doc-travel-policy", "source": "handbook/travel-policy", "text": "..."}
    result = leakage(transcript_with(allowed), case_forbidding("restricted/salary-bands"))
    assert result.status == PASS


def test_forbidden_content_in_the_answer_is_still_caught():
    empty = {"id": "doc-travel-policy", "source": "handbook/travel-policy", "text": "..."}
    result = leakage(
        transcript_with(empty, answer="see restricted/salary-bands for the numbers"),
        case_forbidding("restricted/salary-bands"),
    )
    assert result.status == FAIL
