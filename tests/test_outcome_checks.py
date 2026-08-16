"""The two checks the Q&A case matrix needed, and the one it made unavoidable.

`expected_behavior` exists because "returned nothing" is not a verdict. Whether an
empty result was correct depends entirely on what the case expected, and until the
case says so there is nothing to grade.

`tool_scope` exists because "the Q&A capability stays inactive" is an observable fact
about a trace rather than an opinion about an answer.

`expected_sources` exists because a retrieval outcome that a build should block on has
to be written down as an assertion, not inherited from a ranking metric's default
threshold.
"""

from __future__ import annotations

import pytest

from judgeguard.contract import Identity
from judgeguard.corpus import ANSWER, CLARIFICATION, NO_RESULT, REFUSAL, Case
from judgeguard.lanes.checks import expected_behavior, expected_sources, tool_scope
from judgeguard.lanes.deterministic import FAIL, PASS, UNGRADABLE
from judgeguard.transcript import L1, ToolCall, Transcript

ANON = Identity("analyst", frozenset())


def case(**kwargs) -> Case:
    return Case(id="c", query="q", identity=ANON, **kwargs)


def transcript(passages=(), tool_calls=()) -> Transcript:
    return Transcript(
        case_id="c",
        query="q",
        principal="analyst",
        provider="stub",
        evidence_level=L1,
        passages=list(passages),
        tool_calls=list(tool_calls),
        answer="an answer",
    )


PASSAGE = {"id": "doc-a", "source": "lib/a", "text": "text", "acl": []}


# --- expected_behavior ------------------------------------------------------


def test_no_declaration_is_not_a_failure():
    assert expected_behavior(transcript([PASSAGE]), case()).status == PASS


def test_an_answer_needs_something_to_answer_from():
    declared = case(expected_behavior=ANSWER)
    assert expected_behavior(transcript([PASSAGE]), declared).status == PASS

    empty = expected_behavior(transcript([]), declared)
    assert empty.status == FAIL
    assert "no evidence to ground one" in empty.detail


def test_a_no_result_case_fails_when_something_came_back():
    declared = case(expected_behavior=NO_RESULT)
    assert expected_behavior(transcript([]), declared).status == PASS

    returned = expected_behavior(transcript([PASSAGE]), declared)
    assert returned.status == FAIL
    assert "doc-a" in returned.detail


@pytest.mark.parametrize("declared", [REFUSAL, CLARIFICATION])
def test_the_behaviours_an_l1_run_cannot_see_are_reported_not_guessed(declared):
    """Both would otherwise be graded from an empty passage list, which is the same
    evidence a wrong answer produces."""
    result = expected_behavior(transcript([]), case(expected_behavior=declared))
    assert result.status == UNGRADABLE
    assert result.detail


def test_a_refusal_is_not_confused_with_an_empty_result():
    empty = transcript([])
    assert expected_behavior(empty, case(expected_behavior=NO_RESULT)).status == PASS
    assert expected_behavior(empty, case(expected_behavior=REFUSAL)).status == UNGRADABLE


# --- tool_scope -------------------------------------------------------------


def call(name: str) -> ToolCall:
    return ToolCall(name=name, arguments={})


def test_no_scope_declared_is_not_a_failure():
    assert tool_scope(transcript(tool_calls=[call("retrieve")]), case()).status == PASS


def test_a_forbidden_tool_fails():
    result = tool_scope(
        transcript(tool_calls=[call("retrieve")]),
        case(forbidden_tools=("retrieve",)),
    )
    assert result.status == FAIL
    assert "retrieve" in result.detail


def test_an_expected_tool_that_was_never_called_fails():
    result = tool_scope(
        transcript(tool_calls=[call("retrieve")]),
        case(expected_tools=("run_report",)),
    )
    assert result.status == FAIL
    assert "run_report" in result.detail


def test_scope_is_satisfied_when_the_right_tools_were_used():
    result = tool_scope(
        transcript(tool_calls=[call("retrieve")]),
        case(expected_tools=("retrieve",), forbidden_tools=("create_record",)),
    )
    assert result.status == PASS


def test_order_is_not_asserted():
    """Scope, not path: which tools were touched, not the sequence they ran in."""
    forward = transcript(tool_calls=[call("retrieve"), call("rerank")])
    backward = transcript(tool_calls=[call("rerank"), call("retrieve")])
    declared = case(expected_tools=("retrieve", "rerank"))
    assert tool_scope(forward, declared).status == tool_scope(backward, declared).status


# --- expected_sources -------------------------------------------------------


def test_no_expected_sources_is_not_a_failure():
    assert expected_sources(transcript([]), case()).status == PASS


def test_a_missing_expected_source_fails():
    result = expected_sources(
        transcript([PASSAGE]), case(expected_sources=("doc-b",))
    )
    assert result.status == FAIL
    assert "doc-b" in result.detail


def test_an_expected_source_may_be_named_by_id_or_by_source_path():
    for declared in ("doc-a", "lib/a"):
        result = expected_sources(
            transcript([PASSAGE]), case(expected_sources=(declared,))
        )
        assert result.status == PASS, declared


def test_rank_is_not_asserted():
    """Binary presence is gateable; position is a tunable threshold and is not."""
    other = {"id": "doc-z", "source": "lib/z", "text": "t", "acl": []}
    declared = case(expected_sources=("doc-a",))
    assert expected_sources(transcript([PASSAGE, other]), declared).status == PASS
    assert expected_sources(transcript([other, PASSAGE]), declared).status == PASS
