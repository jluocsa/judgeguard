"""Grading a run judgeguard did not perform.

The runner drives a retriever and a candidate, which cannot express an agent that
decides when to retrieve, retries, declines, or routes elsewhere. Ingest is the way
in for those, and the property that matters is that nothing downstream can tell the
difference: same corpus, same checks, same verdict, whoever produced the transcript.

The other half is refusing to be fooled. A transcript naming a case nobody declared
is not evidence, and a subset graded as though it were the suite is worse than no
run at all - so both fail loudly rather than producing a number.
"""

from __future__ import annotations

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.gate import exit_code
from judgeguard.ingest import TranscriptMismatch, grade, load, pair
from judgeguard.lanes.deterministic import FAIL, PASS, UNGRADABLE
from judgeguard.runner import run
from judgeguard.transcript import L0, L1, L2, ToolCall, Transcript, write_jsonl

PACK = "corpus/qa-pod"


@pytest.fixture(scope="module")
def pack():
    return Corpus.load(PACK)


@pytest.fixture(scope="module")
def driven(pack):
    """A run judgeguard performed itself."""
    return run(pack, Bm25Retriever(pack.documents), TemplateCandidate())


@pytest.fixture
def on_disk(tmp_path, driven):
    path = tmp_path / "transcripts.jsonl"
    write_jsonl(path, [o.transcript for o in driven.outcomes])
    return path


# --- the property that makes ingest worth having -----------------------------


def test_grading_a_driven_run_reproduces_it_exactly(pack, driven, on_disk):
    """Round-trip through disk must not change a single verdict."""
    ingested = grade(pack, load(on_disk))

    assert len(ingested.outcomes) == len(driven.outcomes)
    assert ingested.evidence_level == driven.evidence_level
    for before, after in zip(driven.outcomes, ingested.outcomes):
        assert before.case.id == after.case.id
        assert before.verdict == after.verdict
        assert [c.status for c in before.checks] == [c.status for c in after.checks]


def test_the_exit_code_is_the_same_either_way(pack, driven, on_disk):
    assert exit_code(grade(pack, load(on_disk)).all_checks) == exit_code(
        driven.all_checks
    )


# --- refusing to be fooled ---------------------------------------------------


def test_a_transcript_for_an_undeclared_case_is_rejected(pack):
    stray = Transcript(
        case_id="not-in-the-corpus",
        query="q",
        principal="p",
        provider="x",
        evidence_level=L1,
    )
    with pytest.raises(TranscriptMismatch, match="absent from the corpus"):
        pair(pack, [stray])


def test_a_partial_run_is_rejected_by_default(pack, on_disk):
    transcripts = load(on_disk)[:-2]
    with pytest.raises(TranscriptMismatch, match="no transcript"):
        pair(pack, transcripts)


def test_a_partial_run_can_be_graded_when_asked_for(pack, on_disk):
    transcripts = load(on_disk)[:-2]
    result = grade(pack, transcripts, allow_partial=True)
    assert len(result.outcomes) == len(transcripts)


def test_an_empty_file_is_not_a_clean_run(tmp_path, pack):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(TranscriptMismatch, match="no transcripts"):
        load(empty)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.jsonl")


# --- the evidence level comes from the emitter -------------------------------


def agent_transcript(case_id, *, level=L2, passages=(), calls=(), answer="an answer"):
    return Transcript(
        case_id=case_id,
        query="q",
        principal="consultant",
        provider="external-agent",
        evidence_level=level,
        tool_calls=list(calls),
        passages=list(passages),
        answer=answer,
    )


def test_the_declared_level_decides_what_can_be_graded(pack):
    """An emitter claiming L0 must not have world-state checks graded against it."""
    low = grade(
        pack,
        [agent_transcript(case.id, level=L0) for case in pack.cases],
        allow_partial=True,
    )
    assert low.evidence_level == L0
    statuses = {c.check: c.status for o in low.outcomes for c in o.checks}
    assert statuses["authorized_sources"] == UNGRADABLE


def test_the_run_takes_the_lowest_level_present(pack):
    mixed = [agent_transcript(pack.cases[0].id, level=L2),
             agent_transcript(pack.cases[1].id, level=L1)]
    assert grade(pack, mixed, allow_partial=True).evidence_level == L1


def test_a_mixed_provider_run_is_reported_as_mixed(pack):
    first = agent_transcript(pack.cases[0].id)
    second = agent_transcript(pack.cases[1].id)
    second.provider = "another-agent"
    assert grade(pack, [first, second], allow_partial=True).provider == "mixed"


# --- what a real tool loop unlocks -------------------------------------------


def status_of(result, case_id, check_name):
    outcome = next(o for o in result.outcomes if o.case.id == case_id)
    return next(c for c in outcome.checks if c.check == check_name).status


def test_a_clarification_is_gradable_once_the_agent_chose(pack):
    """At L1 the harness always retrieves, so there is no decision to grade.

    A real agent records whether it asked or searched, and that is an outcome.
    """
    case = next(c for c in pack.cases if c.expected_behavior == "clarification")

    asked = grade(pack, [agent_transcript(case.id, answer="Which part?")],
                  allow_partial=True)
    assert status_of(asked, case.id, "expected_behavior") == PASS

    searched = grade(
        pack,
        [agent_transcript(case.id, passages=[{"id": "d", "source": "s", "text": "t"}])],
        allow_partial=True,
    )
    assert status_of(searched, case.id, "expected_behavior") == FAIL


def test_a_clarification_stays_ungradable_below_l2(pack):
    case = next(c for c in pack.cases if c.expected_behavior == "clarification")
    result = grade(pack, [agent_transcript(case.id, level=L1)], allow_partial=True)
    assert status_of(result, case.id, "expected_behavior") == UNGRADABLE


def test_a_refusal_stays_a_judge_question_at_every_level(pack):
    """Its security outcome is asserted by leakage and authorized_sources instead."""
    case = next(c for c in pack.cases if c.expected_behavior == "refusal")
    result = grade(pack, [agent_transcript(case.id)], allow_partial=True)
    assert status_of(result, case.id, "expected_behavior") == UNGRADABLE
    assert status_of(result, case.id, "leakage") == PASS


def test_an_agent_that_routes_away_satisfies_tool_scope(pack):
    """The wrong-capability case: Q&A stays inactive, so nothing is retrieved."""
    case = next(c for c in pack.cases if "retrieve" in c.forbidden_tools)
    routed = agent_transcript(
        case.id,
        calls=[ToolCall(name="route_to_capability", arguments={"capability": "crud"})],
    )
    result = grade(pack, [routed], allow_partial=True)
    assert status_of(result, case.id, "tool_scope") == PASS
    assert status_of(result, case.id, "expected_behavior") == PASS


def test_a_multi_step_loop_survives_the_round_trip(tmp_path, pack):
    """Several calls, in order, with their results - none of it flattened."""
    case = pack.cases[0]
    original = agent_transcript(
        case.id,
        calls=[
            ToolCall(name="retrieve", arguments={"q": "first"}, result=[]),
            ToolCall(name="retrieve", arguments={"q": "second"}, result=["doc"]),
        ],
    )
    path = tmp_path / "t.jsonl"
    write_jsonl(path, [original])

    restored = load(path)[0]
    assert [c.name for c in restored.tool_calls] == ["retrieve", "retrieve"]
    assert restored.tool_calls[1].arguments["q"] == "second"
    assert restored.tool_calls[1].result == ["doc"]
