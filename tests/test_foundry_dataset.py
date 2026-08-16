"""The Foundry dataset has to be right before anyone spends tokens on it.

Two families of evaluator read `query` and `response` to mean different things - one a
string, one a conversation - and the failure when a row carries only the string shape
is not an exception. The service falls back, logs that accuracy will degrade, and
returns a number; on a terse follow-up it skips outright because the referent is
missing. Both are silent, so they are asserted here.
"""

from __future__ import annotations

import json

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.runner import run
from judgeguard.scorers.foundry import coverage, rows

PACK = "corpus/qa-pod"


@pytest.fixture(scope="module")
def pack():
    return Corpus.load(PACK)


@pytest.fixture(scope="module")
def outcomes(pack):
    return run(pack, Bm25Retriever(pack.documents), TemplateCandidate()).outcomes


def row_for(outcomes, case_id):
    outcome = next(o for o in outcomes if o.case.id == case_id)
    return rows.to_eval_row(outcome.transcript, outcome.case)


# --- both shapes, on every row ----------------------------------------------


def test_every_row_carries_both_shapes(outcomes):
    for outcome in outcomes:
        row = rows.to_eval_row(outcome.transcript, outcome.case)
        assert isinstance(row["query"], str)
        assert isinstance(row["response"], str)
        assert isinstance(row["query_messages"], list)
        assert isinstance(row["response_messages"], list)


def test_the_message_shapes_are_well_formed(outcomes):
    for outcome in outcomes:
        row = rows.to_eval_row(outcome.transcript, outcome.case)
        for message in row["query_messages"] + row["response_messages"]:
            assert message["role"] in ("user", "assistant", "tool")
            assert isinstance(message["content"], list)
            assert all("type" in block for block in message["content"])


def test_tool_calls_are_typed_blocks_not_prose(outcomes):
    """An agent evaluator reads tool calls structurally; prose is not gradable."""
    row = row_for(outcomes, "QA-01")
    calls = [
        block
        for message in row["response_messages"]
        for block in message["content"]
        if block["type"] == "tool_call"
    ]
    assert calls, "the retrieval turn made a tool call"
    for call in calls:
        assert call["name"] and "arguments" in call and call["tool_call_id"]


def test_every_tool_call_is_followed_by_its_result(outcomes):
    row = row_for(outcomes, "QA-01")
    roles = [m["role"] for m in row["response_messages"]]
    for index, role in enumerate(roles[:-1]):
        if role == "assistant" and any(
            b["type"] == "tool_call" for b in row["response_messages"][index]["content"]
        ):
            assert roles[index + 1] == "tool", "a call with no result cannot be graded"


# --- the multi-turn failure this prevents ------------------------------------


def test_a_follow_up_turn_carries_the_turns_before_it(outcomes):
    """Without this a terse follow-up has no referent and evaluators skip.

    Observed in a real run: on a turn whose text was "Open it.", two evaluators
    skipped saying the conversation history was not provided, and four more scored
    it a failure. The agent had done nothing wrong.
    """
    row = row_for(outcomes, "QA-07")
    texts = [b["text"] for m in row["query_messages"] for b in m["content"]]
    assert len(texts) > 1, "QA-07 is a follow-up; its history must be carried"
    assert "engagement letter" in texts[0]
    assert texts[-1] == row["query"], "the current turn is last"


def test_a_single_turn_case_carries_only_itself(outcomes):
    row = row_for(outcomes, "QA-01")
    assert len(row["query_messages"]) == 1


# --- the criteria route each family to the right shape -----------------------


def test_rag_evaluators_read_strings():
    for dimension in ("groundedness", "relevance", "retrieval"):
        mapping = coverage.BY_DIMENSION[dimension].data_mapping()
        assert mapping["query"] == "query"
        if "response" in mapping:
            assert mapping["response"] == "response"


def test_agent_evaluators_read_the_conversation():
    for dimension in ("intent_resolution", "tool_call_accuracy", "task_adherence"):
        mapping = coverage.BY_DIMENSION[dimension].data_mapping()
        assert mapping["query"] == "query_messages"
        assert mapping["response"] == "response_messages"


def test_every_service_evaluator_reads_fields_the_row_supplies(outcomes):
    row = row_for(outcomes, "QA-01")
    for spec in coverage.service_specs():
        for field, source in spec.data_mapping().items():
            assert source in row, f"{spec.dimension} reads {source}, absent from the row"


def test_the_criteria_payload_is_service_shaped():
    criteria = coverage.testing_criteria("judge-deployment")
    assert criteria
    for item in criteria:
        assert item["type"] == "azure_ai_evaluator"
        assert item["evaluator_name"].startswith("builtin.")
        assert item["initialization_parameters"]["deployment_name"] == "judge-deployment"
        for template in item["data_mapping"].values():
            assert template.startswith("{{item.") and template.endswith("}}")


def test_the_pods_thirteen_evaluators_are_all_present():
    """The Q&A pod named thirteen. Fewer would be a silently narrower run."""
    expected = {
        "builtin.retrieval",
        "builtin.groundedness",
        "builtin.relevance",
        "builtin.response_completeness",
        "builtin.document_retrieval",
        "builtin.intent_resolution",
        "builtin.tool_call_accuracy",
        "builtin.tool_selection",
        "builtin.tool_input_accuracy",
        "builtin.tool_output_utilization",
        "builtin.tool_call_success",
        "builtin.task_adherence",
        "builtin.task_completion",
    }
    assert {spec.service for spec in coverage.service_specs()} == expected


def test_a_service_only_evaluator_never_runs_in_process():
    """builtin.task_completion has no SDK class; constructing it would fail."""
    service_only = [
        s for s in coverage.COVERAGE if s.stability == coverage.SERVICE_ONLY
    ]
    assert service_only
    runnable = coverage.runnable_with(
        model_config=True, project=True, include_experimental=True
    )
    assert not (set(service_only) & set(runnable))


def test_experimental_evaluators_are_uploadable_but_not_local():
    """Private as SDK classes, ordinary names on the wire."""
    experimental = set(coverage.experimental())
    assert experimental <= set(coverage.service_specs())
    assert not (experimental & set(coverage.runnable_with(model_config=True, project=False)))


# --- the row is serialisable and carries the verdict -------------------------


def test_rows_survive_json(outcomes):
    for outcome in outcomes:
        assert json.dumps(rows.to_eval_row(outcome.transcript, outcome.case))
