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
    assert len(everything) == len(coverage.stable())


def test_experimental_evaluators_are_opt_in():
    """A private SDK class must never be picked up by default.

    They are listed so the coverage map tells the truth about what exists, and
    excluded so an upgrade that renames one cannot silently change a run.
    """
    default = coverage.runnable_with(model_config=True, project=True)
    assert all(s.stability == coverage.STABLE for s in default)

    opted_in = coverage.runnable_with(
        model_config=True, project=True, include_experimental=True
    )
    assert len(opted_in) == len(coverage.COVERAGE)
    assert set(default) < set(opted_in)


def test_experimental_specs_say_where_to_import_an_unexported_class():
    evaluation = pytest.importorskip(
        "azure.ai.evaluation", reason="needs the foundry extra"
    )
    for spec in coverage.experimental():
        if not hasattr(evaluation, spec.evaluator):
            assert spec.module, (
                f"{spec.evaluator} is not exported by the SDK and the spec gives no "
                "module to import it from"
            )


def test_the_sdk_ships_every_evaluator_the_map_claims():
    """The map is only useful if it describes the installed package."""
    import importlib

    evaluation = pytest.importorskip(
        "azure.ai.evaluation", reason="needs the foundry extra"
    )
    for spec in coverage.COVERAGE:
        if hasattr(evaluation, spec.evaluator):
            continue
        module = importlib.import_module(spec.module)
        assert hasattr(module, spec.evaluator), f"{spec.evaluator} is gone"


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


# --- the two ground truths are not interchangeable ---------------------------


def test_ground_truth_is_reference_text_not_document_identifiers(outcomes):
    """ResponseCompleteness compares a response against an expected answer.

    It was being handed the joined `expected_sources` - document identifiers - so
    it returned a confident number about how well an answer matched a list of ids.
    """
    outcome = next(o for o in outcomes if o.case.expected_answer)
    row = rows.to_eval_row(outcome.transcript, outcome.case)

    assert row["ground_truth"] == outcome.case.expected_answer
    for source in outcome.case.expected_sources:
        assert source not in row["ground_truth"]


def test_expected_sources_still_reach_the_ranking_evaluator(outcomes):
    outcome = next(o for o in outcomes if o.case.expected_sources)
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    labelled = {d["document_id"] for d in row["retrieval_ground_truth"]}
    assert labelled == set(outcome.case.expected_sources)


def test_a_case_with_a_reference_answer_is_gradable(outcomes):
    outcome = next(o for o in outcomes if o.case.expected_answer)
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    spec = coverage.BY_DIMENSION["response_completeness"]
    assert rows.ungradable_reason(spec, row) is None


def test_an_absent_reference_is_reported_rather_than_scored(outcomes):
    outcome = outcomes[0]
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    row["ground_truth"] = ""
    reason = rows.ungradable_reason(
        coverage.BY_DIMENSION["response_completeness"], row
    )
    assert reason and "ground_truth" in reason


def test_a_case_expecting_no_documents_is_not_ranked(outcomes):
    """A denial case has no relevant documents, so there is nothing to rank against."""
    outcome = next(o for o in outcomes if not o.case.expected_sources)
    row = rows.to_eval_row(outcome.transcript, outcome.case)
    assert row["retrieval_ground_truth"] == []
    assert rows.ungradable_reason(coverage.BY_DIMENSION["retrieval_ranking"], row)


def test_every_case_in_the_corpus_carries_a_reference_answer(outcomes):
    """Otherwise the reference-scored evaluators quietly grade nothing."""
    missing = [o.case.id for o in outcomes if not o.case.expected_answer]
    assert not missing, f"cases without an expected answer: {missing}"


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
