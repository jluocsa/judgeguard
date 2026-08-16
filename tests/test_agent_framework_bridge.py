"""The Agent Framework bridge, tested against the real framework types.

Constructed from `agent_framework` objects rather than from dictionaries shaped like
them, because the failure this guards against is the framework changing how it models
a run - and a dictionary that imitates today's shape would keep passing while the
bridge broke.

No model and no credentials: an `AgentResponse` is directly constructible, so the
whole path is exercised offline.

    pip install agent-framework-core
"""

from __future__ import annotations

import pytest

from judgeguard.bridges import transcript_from_agent_response
from judgeguard.contract import Identity
from judgeguard.corpus import Case
from judgeguard.gate import EXIT_VERDICT_FAILED, exit_code
from judgeguard.ingest import grade
from judgeguard.lanes.deterministic import PASS
from judgeguard.transcript import L0, L2

af = pytest.importorskip(
    "agent_framework", reason="needs agent-framework-core for the bridge"
)

QUERY = "what notice period does the engagement letter require"


def case(**kwargs) -> Case:
    return Case(
        id=kwargs.pop("id", "AF-1"),
        query=kwargs.pop("query", QUERY),
        identity=Identity(principal="consultant", clearances=frozenset()),
        **kwargs,
    )


def response(*messages):
    return af.AgentResponse(messages=list(messages))


def assistant(*contents):
    return af.Message("assistant", list(contents))


def tool(*contents):
    return af.Message("tool", list(contents))


def call(call_id, name, arguments):
    return af.Content("function_call", call_id=call_id, name=name, arguments=arguments)


def result(call_id, value=None, exception=None):
    return af.Content(
        "function_result", call_id=call_id, result=value, exception=exception
    )


def text(value):
    return af.Content("text", text=value)


# --- the translation ---------------------------------------------------------


def test_a_single_tool_call_round_trips():
    reply = response(
        assistant(call("c1", "retrieve", {"query": "notice period"})),
        tool(result("c1", ["doc-v3"])),
        assistant(text("30 days written notice.")),
    )
    transcript = transcript_from_agent_response(reply, case())

    assert transcript.case_id == "AF-1"
    assert transcript.answer == "30 days written notice."
    assert transcript.evidence_level == L2
    assert len(transcript.tool_calls) == 1

    only = transcript.tool_calls[0]
    assert only.name == "retrieve"
    assert only.arguments == {"query": "notice period"}
    assert only.result == ["doc-v3"]
    assert only.error is None


def test_call_order_survives_a_retry():
    """A reformulate-and-retry is the shape a re-execution would flatten."""
    reply = response(
        assistant(call("c1", "retrieve", {"query": "first"})),
        tool(result("c1", [])),
        assistant(call("c2", "retrieve", {"query": "second"})),
        tool(result("c2", ["doc-v3"])),
        assistant(text("found on the second try")),
    )
    transcript = transcript_from_agent_response(reply, case())

    assert [c.arguments["query"] for c in transcript.tool_calls] == ["first", "second"]
    assert transcript.tool_calls[0].result == []
    assert transcript.tool_calls[1].result == ["doc-v3"]


def test_results_are_matched_by_id_not_by_position():
    """Interleaved or out-of-order results must still land on the right call."""
    reply = response(
        assistant(call("a", "first_tool", {})),
        assistant(call("b", "second_tool", {})),
        tool(result("b", "second result")),
        tool(result("a", "first result")),
    )
    transcript = transcript_from_agent_response(reply, case())
    by_name = {c.name: c.result for c in transcript.tool_calls}
    assert by_name == {"first_tool": "first result", "second_tool": "second result"}


def test_a_failed_call_keeps_its_error():
    """A swallowed failure grades as a legitimate empty result."""
    reply = response(
        assistant(call("c1", "retrieve", {})),
        tool(result("c1", exception="HTTP 429 Too Many Requests")),
        assistant(text("The knowledge base is unavailable.")),
    )
    transcript = transcript_from_agent_response(reply, case())
    assert "429" in transcript.tool_calls[0].error


def test_an_unmatched_result_is_reported_rather_than_dropped():
    reply = response(tool(result("orphan", "something")))
    transcript = transcript_from_agent_response(reply, case())
    assert transcript.tool_calls
    assert transcript.tool_calls[0].name == "<unmatched result>"


def test_json_string_arguments_are_decoded():
    """Some providers hand back arguments as a JSON string."""
    reply = response(assistant(call("c1", "retrieve", '{"query": "notice"}')))
    transcript = transcript_from_agent_response(reply, case())
    assert transcript.tool_calls[0].arguments == {"query": "notice"}


def test_an_agent_that_called_nothing_is_still_a_transcript():
    """A clarification is a real outcome, and it has no tool calls."""
    reply = response(assistant(text("Which part of the letter do you need?")))
    transcript = transcript_from_agent_response(reply, case())
    assert transcript.tool_calls == []
    assert transcript.answer.startswith("Which part")


# --- the claim judgeguard cannot verify --------------------------------------


def test_the_evidence_level_can_be_lowered_when_the_tools_were_mocked():
    reply = response(assistant(text("canned")))
    transcript = transcript_from_agent_response(reply, case(), evidence_level=L0)
    assert transcript.evidence_level == L0


def test_passages_are_never_inferred_from_tool_results():
    """What counts as a retrieved passage is the tool's shape, not the bridge's guess."""
    reply = response(
        assistant(call("c1", "retrieve", {})),
        tool(result("c1", [{"id": "doc-v3", "text": "..."}])),
    )
    assert transcript_from_agent_response(reply, case()).passages == []

    supplied = [{"id": "doc-v3", "source": "library/x", "text": "...", "acl": []}]
    transcript = transcript_from_agent_response(reply, case(), passages=supplied)
    assert transcript.passages == supplied


# --- and it grades ------------------------------------------------------------


def test_a_bridged_transcript_grades_like_any_other(tmp_path):
    """The point of the bridge: everything downstream works unchanged."""
    from judgeguard.corpus import Corpus

    pack = Corpus.load("corpus/qa-pod")
    target = next(c for c in pack.cases if c.expected_behavior == "clarification")

    reply = response(assistant(text("Which part of the letter do you need?")))
    transcript = transcript_from_agent_response(reply, target)

    run = grade(pack, [transcript], allow_partial=True)
    assert run.evidence_level == L2
    statuses = {c.check: c.status for o in run.outcomes for c in o.checks}
    # It asked instead of retrieving, which at L2 is a gradable outcome.
    assert statuses["expected_behavior"] == PASS
    assert exit_code(run.all_checks) != EXIT_VERDICT_FAILED
