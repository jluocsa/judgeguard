"""judgeguard's message shape must equal Microsoft Agent Framework's.

Both exist for the same reason: Foundry's agent evaluators read a conversation of
typed content blocks, and a bare string silently degrades their accuracy. Agent
Framework solves it in `AgentEvalConverter`; judgeguard solves it in
`rows.to_messages`, because the deterministic lane carries no runtime dependencies
and cannot import a framework to emit a dictionary.

Two implementations of one wire format drift, and this one drifts silently - a shape
that is merely *close* still returns numbers. So the parity is asserted rather than
assumed, against the installed framework, and skipped when it is absent.

If this fails after an Agent Framework upgrade, the framework is the authority.
Update `rows.to_messages` to match it.

    pip install agent-framework-core
"""

from __future__ import annotations

import pytest

from judgeguard.contract import Identity
from judgeguard.corpus import Case
from judgeguard.scorers.foundry.rows import to_messages
from judgeguard.transcript import L2, ToolCall, Transcript

af = pytest.importorskip(
    "agent_framework", reason="needs agent-framework-core to compare against"
)
converter = pytest.importorskip("agent_framework._evaluation").AgentEvalConverter

QUERY = "what notice period does the engagement letter require"
ANSWER = "30 days written notice."
TOOL = "retrieve"
ARGUMENTS = {"query": "notice period", "principal": "consultant"}
RESULT = ["doc-engagement-letter-v3"]


@pytest.fixture
def judgeguard_messages():
    case = Case(
        id="PARITY-1",
        query=QUERY,
        identity=Identity(principal="consultant", clearances=frozenset()),
    )
    transcript = Transcript(
        case_id=case.id,
        query=QUERY,
        principal="consultant",
        provider="parity",
        evidence_level=L2,
        tool_calls=[ToolCall(name=TOOL, arguments=ARGUMENTS, result=RESULT)],
        answer=ANSWER,
    )
    return to_messages(transcript, case)


def framework_messages(call_id: str):
    """The same interaction, expressed in Agent Framework types."""
    Content, Message = af.Content, af.Message
    query = [Message("user", [Content("text", text=QUERY)])]
    response = [
        Message(
            "assistant",
            [Content("function_call", call_id=call_id, name=TOOL, arguments=ARGUMENTS)],
        ),
        Message("tool", [Content("function_result", call_id=call_id, result=RESULT)]),
        Message("assistant", [Content("text", text=ANSWER)]),
    ]
    return converter.convert_messages(query), converter.convert_messages(response)


def call_id_from(response: list[dict]) -> str:
    for message in response:
        for block in message.get("content", []):
            if block.get("type") == "tool_call":
                return block["tool_call_id"]
    raise AssertionError("no tool call in the judgeguard response")


def test_the_query_shape_matches(judgeguard_messages):
    mine, _ = judgeguard_messages
    theirs, _ = framework_messages("ignored")
    assert mine == theirs


def test_the_response_shape_matches(judgeguard_messages):
    """Tool calls, tool results and the final text, block for block.

    Identifiers are generated differently and that is not a wire-format concern, so
    the framework is handed judgeguard's id and everything else must agree.
    """
    _, mine = judgeguard_messages
    _, theirs = framework_messages(call_id_from(mine))
    assert mine == theirs


def test_a_tool_result_keeps_its_identifier_at_the_top_level(judgeguard_messages):
    """The detail most likely to be got wrong by hand, and it is load-bearing."""
    _, mine = judgeguard_messages
    tool_message = next(m for m in mine if m["role"] == "tool")
    assert "tool_call_id" in tool_message
    assert tool_message["content"][0]["type"] == "tool_result"


def test_an_error_is_carried_where_a_result_would_be():
    """A failed call must still be gradable, not silently look like an empty one."""
    case = Case(id="E", query="q", identity=Identity(principal="p"))
    transcript = Transcript(
        case_id="E",
        query="q",
        principal="p",
        provider="parity",
        evidence_level=L2,
        tool_calls=[ToolCall(name=TOOL, arguments={}, result=None, error="HTTP 429")],
        answer="",
    )
    _, response = to_messages(transcript, case)
    result_block = next(
        b for m in response for b in m["content"] if b["type"] == "tool_result"
    )
    assert result_block["tool_result"] == "HTTP 429"
