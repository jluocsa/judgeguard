"""The Foundry bridge: coverage map, row conversion, and the gating invariant.

None of these need the SDK or a credential. That is deliberate - the conversion is
the part that has to be right, and it should be verified on every commit rather
than only when someone has a subscription.
"""

from __future__ import annotations

import json

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.gate import exit_code
from judgeguard.runner import run
from judgeguard.scorers.foundry import coverage, rows


@pytest.fixture(scope="module")
def outcomes():
    corpus = Corpus.load("corpus")
    return run(corpus, Bm25Retriever(corpus.documents), TemplateCandidate()).outcomes


# --- coverage map -----------------------------------------------------------


def test_every_spec_declares_a_known_requirement():
    allowed = {coverage.COMPUTABLE, coverage.MODEL_CONFIG, coverage.AZURE_AI_PROJECT}
    assert {s.requires for s in coverage.COVERAGE} <= allowed


def test_dimensions_are_unique():
    dimensions = [s.dimension for s in coverage.COVERAGE]
    assert len(dimensions) == len(set(dimensions))


def test_credentials_gate_which_evaluators_can_run():
    nothing = coverage.runnable_with(model_config=False, project=False)
    assert {s.requires for s in nothing} == {coverage.COMPUTABLE}

    with_model = coverage.runnable_with(model_config=True, project=False)
    assert coverage.AZURE_AI_PROJECT not in {s.requires for s in with_model}
    assert len(with_model) > len(nothing)

    everything = coverage.runnable_with(model_config=True, project=True)
    assert len(everything) == len(coverage.COVERAGE)


def test_a_bare_model_config_covers_most_of_the_map():
    """The finding that decides whether adopting Foundry is config or procurement."""
    model_only = coverage.specs_for(coverage.MODEL_CONFIG)
    assert len(model_only) >= len(coverage.COVERAGE) / 2


# --- row conversion ---------------------------------------------------------


def test_row_carries_every_declared_input(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    for field in coverage.ALL_INPUTS:
        assert field in row, f"no evaluator input {field!r} in the row"


def test_every_evaluator_can_be_fed_from_one_row(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    for spec in coverage.COVERAGE:
        payload = rows.inputs_for(spec, row)
        assert set(payload) == set(spec.inputs)


def test_row_preserves_the_transcript_without_loss(outcomes):
    outcome = outcomes[0]
    transcript = outcome.transcript
    row = rows.to_eval_row(transcript, outcome.case)

    assert row["query"] == transcript.query
    assert row["response"] == transcript.answer
    assert len(row["tool_calls"]) == len(transcript.tool_calls)
    assert len(row["retrieved_documents"]) == len(transcript.passages)
    for passage in transcript.passages:
        assert passage["text"] in row["context"]


def test_row_carries_provenance_back_to_the_run(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    assert row["case_id"] == outcome.transcript.case_id
    assert row["evidence_level"] == outcome.transcript.evidence_level
    assert row["provider"] == outcome.transcript.provider


def test_row_is_serialisable(outcomes):
    outcome = outcomes[0]
    assert json.dumps(rows.to_eval_row(outcome.transcript, outcome.case))


def test_missing_input_fails_loud(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    del row["context"]
    with pytest.raises(KeyError, match="context"):
        rows.inputs_for(coverage.BY_DIMENSION["groundedness"], row)


# --- results merge back -----------------------------------------------------


def test_service_results_become_judge_scores(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    service = {
        "groundedness": {"score": 4.0, "reason": "supported by the retrieved context"},
        "relevance": {"score": 3.0, "reason": "addresses the question"},
        "not_a_dimension": {"score": 9.9},
    }
    scores = rows.from_eval_results(service, row, "foundry:judge-deployment")

    assert {s.dimension for s in scores} == {"groundedness", "relevance"}
    assert all(s.judge_id == "foundry:judge-deployment" for s in scores)
    assert all(s.reasoning for s in scores)


def test_self_judged_marking_survives_the_merge(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    scores = rows.from_eval_results(
        {"groundedness": {"score": 5.0, "reason": "ok"}}, row, "j", self_judged=True
    )
    assert all(s.self_judged for s in scores)


# --- the invariant ----------------------------------------------------------


def test_foundry_scores_still_cannot_gate(outcomes):
    """Changing scoring platform must not change what fails the build."""
    row = rows.to_eval_row(outcomes[0].transcript, outcomes[0].case)
    scores = rows.from_eval_results(
        {"groundedness": {"score": 0.0, "reason": "completely ungrounded"}}, row, "j"
    )
    with pytest.raises(TypeError, match="only deterministic CheckResult"):
        exit_code(scores)


def test_importing_the_bridge_does_not_import_the_sdk():
    """Fresh interpreter: the coverage map and row conversion stay SDK-free."""
    import subprocess
    import sys

    probe = (
        "import sys; from judgeguard.scorers import foundry;"
        "print('azure.ai.evaluation' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"
