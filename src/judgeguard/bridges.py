"""Bridges from an agent framework's own types into a judgeguard transcript.

judgeguard grades transcripts. A framework that already models an agent run has the
same information in its own shape, so the bridge is a translation rather than a second
execution - the agent is not run again, and nothing about how it ran is inferred.

Currently one bridge: Microsoft Agent Framework.

Nothing here is imported at module scope, and judgeguard does not depend on any
framework. Import the bridge you need and pay for that framework only.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .corpus import Case
from .transcript import L2, ToolCall, Transcript

# Microsoft Agent Framework content type discriminators.
FUNCTION_CALL = "function_call"
FUNCTION_RESULT = "function_result"
TEXT = "text"

AGENT_FRAMEWORK = "agent-framework"


def transcript_from_agent_response(
    response: Any,
    case: Case,
    *,
    passages: Sequence[dict[str, Any]] = (),
    provider: str = AGENT_FRAMEWORK,
    evidence_level: str = L2,
    candidate: str | None = None,
) -> Transcript:
    """Convert a Microsoft Agent Framework `AgentResponse` into a transcript.

    Every tool call is paired with its result by `call_id`, in the order the agent
    made them, so a retry, a decline and a route to another capability all survive
    intact - which is the reason for grading an agent from its own run rather than
    from a re-execution that would flatten them.

    `passages` is not inferred from the tool results. What counts as a retrieved
    passage is a property of the retrieval tool's response shape, and guessing at it
    would silently decide what the authorization checks read. A harness that surfaces
    passages should pass them; one that does not gets a transcript whose checks report
    what they can and no more.

    `evidence_level` defaults to L2 because an `AgentResponse` is the output of a real
    agent run. Pass L0 or L1 if the tools underneath it were mocked - the level is a
    claim judgeguard cannot verify, and overstating it buys checks graded against
    world state that does not exist.

        from judgeguard.bridges import transcript_from_agent_response

        result = await agent.run(case.query)
        transcript = transcript_from_agent_response(result, case)
    """
    messages = list(getattr(response, "messages", None) or ())
    return Transcript(
        case_id=case.id,
        query=case.query,
        principal=case.identity.principal,
        provider=provider,
        evidence_level=evidence_level,
        tool_calls=tool_calls_in(messages),
        passages=list(passages),
        answer=_final_text(response, messages),
        meta={
            "variant": case.variant,
            "candidate": candidate or getattr(response, "agent_id", None) or provider,
            "response_id": getattr(response, "response_id", None),
        },
    )


def tool_calls_in(messages: Iterable[Any]) -> list[ToolCall]:
    """Pair every call with its result, keeping the order the agent used."""
    calls: list[ToolCall] = []
    index_of: dict[str, int] = {}

    for message in messages:
        for content in getattr(message, "contents", None) or ():
            kind = getattr(content, "type", None)
            if kind == FUNCTION_CALL:
                index_of[str(getattr(content, "call_id", len(calls)))] = len(calls)
                calls.append(
                    ToolCall(
                        name=getattr(content, "name", "") or "",
                        arguments=_as_mapping(getattr(content, "arguments", None)),
                    )
                )
            elif kind == FUNCTION_RESULT:
                position = index_of.get(str(getattr(content, "call_id", "")))
                if position is None:
                    # A result with no matching call is reported rather than
                    # dropped: it means the trace is incomplete, and a check that
                    # never sees it would grade the run as though it were whole.
                    calls.append(
                        ToolCall(
                            name="<unmatched result>",
                            arguments={},
                            result=getattr(content, "result", None),
                        )
                    )
                    continue
                call = calls[position]
                exception = getattr(content, "exception", None)
                calls[position] = ToolCall(
                    name=call.name,
                    arguments=call.arguments,
                    result=getattr(content, "result", None),
                    error=str(exception) if exception else None,
                )
    return calls


def _final_text(response: Any, messages: Sequence[Any]) -> str:
    """The answer the user would see."""
    text = getattr(response, "text", None)
    if text:
        return str(text)
    for message in reversed(list(messages)):
        for content in getattr(message, "contents", None) or ():
            if getattr(content, "type", None) == TEXT and getattr(content, "text", None):
                return str(content.text)
    return ""


def _as_mapping(arguments: Any) -> dict[str, Any]:
    """Arguments arrive as a mapping or as a JSON string, depending on the provider."""
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        import json

        try:
            decoded = json.loads(arguments)
        except ValueError:
            return {"_raw": arguments}
        return decoded if isinstance(decoded, dict) else {"_raw": arguments}
    return dict(arguments)
