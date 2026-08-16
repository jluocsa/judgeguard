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


def to_eval_row(
    transcript: Transcript,
    case: Case,
    *,
    tool_definitions: list[dict[str, Any]] | None = None,
    system_message: str = "",
) -> dict[str, Any]:
    """The union row. Each evaluator is later handed only the fields it declares."""
    passages = transcript.passages
    return {
        # judgeguard provenance - not consumed by evaluators, carried so a score
        # can always be traced back to the run and the level that produced it.
        "case_id": transcript.case_id,
        "evidence_level": transcript.evidence_level,
        "provider": transcript.provider,
        "variant": case.variant,
        # evaluator inputs
        "query": transcript.query,
        "response": transcript.answer,
        "context": CONTEXT_SEPARATOR.join(p.get("text", "") for p in passages),
        "system_message": system_message,
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
