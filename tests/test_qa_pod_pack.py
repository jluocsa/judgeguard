"""The Q&A pod case matrix, expressed in judgeguard's corpus schema.

QA-01 to QA-11 were written as a scenario table. Three things happen when they are
made executable, and all three are findings rather than mechanics:

  - Some cases declare two acceptable outcomes ("infer intent **or** clarify"), and
    a case with a disjunctive expectation cannot be deterministically graded.
  - Some need evidence an L1 run does not produce - a refusal lives in the generated
    answer, a clarification is the absence of a retrieval.
  - Some need harness capabilities that do not exist: routing, prior-turn context,
    fault injection, paired run configuration.

The tests below pin the mapping so the gaps stay visible instead of being quietly
absorbed into a green run.
"""

from __future__ import annotations

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import BEHAVIOURS, CLARIFICATION, REFUSAL, Corpus
from judgeguard.lanes.deterministic import FAIL, PASS, UNGRADABLE
from judgeguard.runner import run

PACK = "corpus/qa-pod"

# Carried in the pack and gradable to some degree.
MAPPED = [f"QA-0{n}" for n in range(1, 10)]

# Not in the pack, and deliberately so. A case whose distinguishing condition cannot
# be produced would pass vacuously, which is worse than an acknowledged gap.
UNMAPPED = {
    "QA-10": "needs fault injection; covered by tests/conformance/test_option_equivalence.py",
    "QA-11": "a paired run configuration, not a case; expressed by `judgeguard bakeoff`",
}


@pytest.fixture(scope="module")
def pack():
    return Corpus.load(PACK)


@pytest.fixture(scope="module")
def result(pack):
    return run(pack, Bm25Retriever(pack.documents), TemplateCandidate())


def outcome(result, case_id):
    return next(o for o in result.outcomes if o.case.id == case_id)


def status_of(result, case_id, check_name):
    checks = outcome(result, case_id).checks
    return next(c for c in checks if c.check == check_name).status


# --- the mapping ------------------------------------------------------------


def test_the_pack_carries_every_mappable_case(pack):
    assert [c.id for c in pack.cases] == MAPPED


def test_the_unmapped_cases_are_named_rather_than_forgotten(pack):
    present = {c.id for c in pack.cases}
    assert not (set(UNMAPPED) & present), (
        "a case whose distinguishing condition cannot be produced would pass "
        "vacuously; keep it out of the pack and record where it is covered"
    )


def test_every_case_declares_an_end_behaviour(pack):
    """Section 9.7.5's requirement: without it, 'answered nothing' and 'correctly
    declined' are the same transcript."""
    missing = [c.id for c in pack.cases if c.expected_behavior is None]
    assert not missing, f"cases with no declared end behaviour: {missing}"
    assert all(c.expected_behavior in BEHAVIOURS for c in pack.cases)


def test_every_case_declares_who_is_asking(pack):
    assert all(c.identity.principal for c in pack.cases)


def test_every_case_carries_a_reference_answer(pack):
    missing = [c.id for c in pack.cases if not c.expected_answer]
    assert not missing, f"not gradable on completeness: {missing}"


# --- what the pack actually proves today ------------------------------------


def test_qa01_a_direct_answer_is_graded_on_the_source_it_used(result):
    assert status_of(result, "QA-01", "expected_sources") == PASS
    assert status_of(result, "QA-01", "expected_behavior") == PASS


def test_qa03_and_qa04_prove_a_no_result_really_returned_nothing(result):
    for case_id in ("QA-03", "QA-04"):
        assert status_of(result, case_id, "expected_behavior") == PASS
        assert not outcome(result, case_id).transcript.passages


def test_qa08_requires_both_conflicting_versions_to_come_back(result):
    """Surfacing a conflict is judged; retrieving both sides of it is not."""
    assert status_of(result, "QA-08", "expected_sources") == PASS
    retrieved = {p["id"] for p in outcome(result, "QA-08").transcript.passages}
    assert {"qa-doc-engagement-letter-v3", "qa-doc-engagement-letter-v2"} <= retrieved


def test_qa09_withholds_the_unauthorized_best_match(result):
    """The highest-scoring document is restricted; none of it may surface."""
    assert status_of(result, "QA-09", "leakage") == PASS
    assert status_of(result, "QA-09", "authorized_sources") == PASS
    retrieved = {p["id"] for p in outcome(result, "QA-09").transcript.passages}
    assert "qa-doc-partner-comp" not in retrieved


# --- and what it cannot prove, stated as tests so it cannot rot -------------


@pytest.mark.parametrize("case_id", ["QA-02", "QA-05"])
def test_a_clarification_cannot_be_graded_by_a_harness_that_always_retrieves(
    result, case_id
):
    assert outcome(result, case_id).case.expected_behavior == CLARIFICATION
    assert status_of(result, case_id, "expected_behavior") == UNGRADABLE


def test_a_refusal_cannot_be_graded_from_a_retrieval_transcript(result):
    assert outcome(result, "QA-09").case.expected_behavior == REFUSAL
    assert status_of(result, "QA-09", "expected_behavior") == UNGRADABLE


def test_qa06_fails_because_this_harness_cannot_decline_to_retrieve(result):
    """A wrong-capability request should leave Q&A inactive. This harness retrieves
    unconditionally, so the case fails - which is the correct report, not a broken
    fixture. It turns green when a routing layer exists."""
    assert status_of(result, "QA-06", "tool_scope") == FAIL
    assert status_of(result, "QA-06", "expected_behavior") == FAIL


def test_qa07_carries_prior_turns_that_nothing_yet_reads(pack):
    """The context is recorded so the case is complete; the runner is single-turn,
    so a follow-up is graded as though it were asked cold."""
    qa07 = next(c for c in pack.cases if c.id == "QA-07")
    assert qa07.prior_turns
    assert "engagement letter" in qa07.prior_turns[0]


def test_the_pack_gates_on_the_gap_rather_than_hiding_it(result):
    from judgeguard.gate import EXIT_VERDICT_FAILED, exit_code

    assert exit_code(result.all_checks) == EXIT_VERDICT_FAILED
