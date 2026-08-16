"""Transcript to evaluator row, and results back onto the transcript.

Pure data transformation with no SDK import, so the conversion is testable offline
and the round-trip fidelity test runs on every commit rather than only when someone
has credentials.

Two fields are easy to confuse and are not interchangeable. `ground_truth` is
reference answer text, consumed by reference-scored evaluators such as
ResponseCompleteness. `retrieval_ground_truth` is a list of relevance-labelled
document identifiers, consumed by ranking evaluators. Feeding document identifiers
to a reference-scored evaluator produces a confident number about nothing.
"""

from __future__ import annotations

from typing import Any

from ...corpus import Case
from ...transcript import Transcript
from .coverage import BY_DIMENSION, EvaluatorSpec

CONTEXT_SEPARATOR = "\n\n"

# The corpus labels a source as expected or not, with no intermediate grades, so
# every expected source carries the same positive label. Graded relevance would
# need graded labels in the corpus; inventing a spread here would fabricate them.
EXPECTED_SOURCE_RELEVANCE = 4

USER = "user"
ASSISTANT = "assistant"
TOOL = "tool"


def to_messages(
    transcript: Transcript, case: Case
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the message-shaped `query` and `response` the agent evaluators want.

    Two shapes exist and they are not interchangeable. Reference-scored and RAG
    evaluators read `query`, `response` and `context` as plain strings. The agent
    evaluators read a conversation: `query` is the history up to and including the
    user's turn, `response` is what the agent produced, with tool calls and tool
    results as typed content blocks rather than prose.

    Handing an agent evaluator a bare string is not a hard failure, which is what
    makes it dangerous. The service falls back to raw input, logs that accuracy will
    degrade, and still returns a number. Worse, a terse follow-up such as "Open it."
    carries no referent without the prior turns, and evaluators observed skipping
    outright with "the CONVERSATION_HISTORY content is not actually provided" - a
    silent deflation that reads downstream as an agent that performed badly.

    `Case.prior_turns` is what makes the history reconstructable, which is why a
    multi-turn case has to declare it.

    Microsoft Agent Framework solves the same problem in `AgentEvalConverter`, and
    this function deliberately produces the identical shape. It is written out by
    hand only because the deterministic lane carries no runtime dependencies and so
    cannot import a framework to emit a dictionary. Two implementations of one wire
    format drift silently - a shape that is merely close still returns numbers - so
    `tests/test_message_shape_parity.py` asserts they are equal whenever
    agent-framework-core is installed, and treats the framework as the authority.
    """
    query: list[dict[str, Any]] = [
        {"role": USER, "content": [{"type": "text", "text": turn}]}
        for turn in case.prior_turns
    ]
    query.append(
        {"role": USER, "content": [{"type": "text", "text": transcript.query}]}
    )

    response: list[dict[str, Any]] = []
    for index, call in enumerate(transcript.tool_calls):
        call_id = f"call_{transcript.case_id}_{index}"
        response.append(
            {
                "role": ASSISTANT,
                "content": [
                    {
                        "type": "tool_call",
                        "tool_call_id": call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                ],
            }
        )
        response.append(
            {
                "role": TOOL,
                "tool_call_id": call_id,
                "content": [
                    {
                        "type": "tool_result",
                        "tool_result": call.error if call.error else call.result,
                    }
                ],
            }
        )
    if transcript.answer:
        response.append(
            {
                "role": ASSISTANT,
                "content": [{"type": "text", "text": transcript.answer}],
            }
        )
    return query, response


def to_eval_row(
    transcript: Transcript,
    case: Case,
    *,
    tool_definitions: list[dict[str, Any]] | None = None,
    system_message: str = "",
) -> dict[str, Any]:
    """The union row. Each evaluator is later handed only the fields it declares."""
    passages = transcript.passages
    query_messages, response_messages = to_messages(transcript, case)
    return {
        # judgeguard provenance - not consumed by evaluators, carried so a score
        # can always be traced back to the run and the level that produced it.
        "case_id": transcript.case_id,
        "evidence_level": transcript.evidence_level,
        "provider": transcript.provider,
        "variant": case.variant,
        # evaluator inputs, string-shaped: RAG and reference-scored evaluators
        "query": transcript.query,
        "response": transcript.answer,
        "context": CONTEXT_SEPARATOR.join(p.get("text", "") for p in passages),
        "system_message": system_message,
        # evaluator inputs, message-shaped: agent evaluators. Both shapes ship on
        # every row and each evaluator's data mapping selects the one it reads,
        # because the same field name means different things to the two families.
        "query_messages": query_messages,
        "response_messages": response_messages,
        "tool_calls": [
            {
                "type": "tool_call",
                "name": call.name,
                "arguments": call.arguments,
            }
            for call in transcript.tool_calls
        ],
        "tool_definitions": tool_definitions or _default_tool_definitions(),
        "ground_truth": case.expected_answer or "",
        "retrieved_documents": [
            {"document_id": p["id"], "relevance_score": p.get("score", 0.0)}
            for p in passages
        ],
        "retrieval_ground_truth": [
            {"document_id": source, "query_relevance_label": EXPECTED_SOURCE_RELEVANCE}
            for source in case.expected_sources
        ],
    }


def inputs_for(spec: EvaluatorSpec, row: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in spec.inputs if field not in row]
    if missing:
        raise KeyError(f"{spec.evaluator} needs {missing}, absent from the row")
    return {field: row[field] for field in spec.inputs}


def ungradable_reason(spec: EvaluatorSpec, row: dict[str, Any]) -> str | None:
    """Why this evaluator cannot grade this row, or None if it can.

    An evaluator handed an empty reference still returns a number. That number is
    a property of the empty reference, not of the response, so it is worse than no
    number at all. Refusing to call is the honest outcome.
    """
    for field in spec.requires_nonempty:
        if not row.get(field):
            return f"{spec.evaluator} needs a non-empty {field}; this case declares none"
    return None


def from_eval_results(
    results: dict[str, Any], row: dict[str, Any], judge_id: str, *, self_judged: bool = False
):
    """Merge service results back into JudgeScore objects.

    Imported here rather than at module scope so this module stays free of the
    lanes package for the fidelity test.
    """
    from ...lanes.judge import JudgeScore

    scores = []
    for dimension, payload in results.items():
        spec = BY_DIMENSION.get(dimension)
        if spec is None:
            continue
        scores.append(
            JudgeScore(
                dimension=dimension,
                score=float(payload.get("score", 0.0)),
                reasoning=str(payload.get("reason", "")) or f"{spec.evaluator}: no reason returned",
                judge_id=judge_id,
                self_judged=self_judged,
            )
        )
    return scores


def _default_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "retrieve",
            "description": "Retrieve passages the caller is authorized to read.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "principal": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        }
    ]
