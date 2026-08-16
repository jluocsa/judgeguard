"""Checks that need real world state must report ungradable, never pass."""

from __future__ import annotations

from judgeguard.adapters import Bm25Retriever, CannedRetriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.lanes.deterministic import FAIL, PASS, UNGRADABLE
from judgeguard.runner import run
from judgeguard.transcript import L0, L1

NEEDS_REAL_STATE = {"authorized_sources", "leakage", "injection_resistance"}


def _run(retriever_cls):
    corpus = Corpus.load("corpus")
    return run(corpus, retriever_cls(corpus.documents), TemplateCandidate())


def test_mocked_retrieval_cannot_pass_a_world_state_check():
    result = _run(CannedRetriever)
    assert result.evidence_level == L0
    for outcome in result.outcomes:
        for check in outcome.checks:
            if check.check in NEEDS_REAL_STATE:
                assert check.status == UNGRADABLE, (
                    f"{check.check} reported {check.status} at L0 - a mocked run "
                    "must never produce a passing world-state assertion"
                )


def test_real_retrieval_grades_the_same_checks():
    result = _run(Bm25Retriever)
    assert result.evidence_level == L1
    statuses = {
        check.check: check.status
        for outcome in result.outcomes
        for check in outcome.checks
        if check.check in NEEDS_REAL_STATE
    }
    assert statuses
    assert UNGRADABLE not in statuses.values()


def test_acl_is_enforced_and_the_injection_is_caught():
    result = _run(Bm25Retriever)
    by_case = {o.case.id: o for o in result.outcomes}

    denied = by_case["acl-salary-denied"]
    assert all(c.status != FAIL for c in denied.checks)
    assert "doc-salary-bands" not in {p["id"] for p in denied.transcript.passages}

    allowed = by_case["acl-salary-allowed"]
    assert "doc-salary-bands" in {p["id"] for p in allowed.transcript.passages}

    injected = by_case["inj-vendor-marker"]
    failing = {c.check for c in injected.checks if c.status == FAIL}
    assert "injection_resistance" in failing, (
        "the bundled naive candidate echoes retrieved text, so the planted marker "
        "must surface - if this passes, the injection pack has stopped working"
    )


def test_a_passing_case_really_passes():
    result = _run(Bm25Retriever)
    travel = {o.case.id: o for o in result.outcomes}["qa-travel-natural"]
    assert travel.verdict == PASS
    assert "doc-travel-policy" in {p["id"] for p in travel.transcript.passages}
