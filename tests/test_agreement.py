"""Agreement statistics, and the traps that make raw agreement misleading."""

from __future__ import annotations

import csv

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.agreement import (
    GATE,
    HUMAN,
    JUDGE,
    cohens_kappa,
    compare,
    gate_labels,
    judge_labels,
    render,
)
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.labeling import (
    ACCEPTABLE,
    COLUMNS,
    UNACCEPTABLE,
    SheetExists,
    emit,
    load,
)
from judgeguard.lanes.judge import JudgeScore, OfflineStubJudge
from judgeguard.runner import run


@pytest.fixture(scope="module")
def result():
    corpus = Corpus.load("corpus")
    return run(
        corpus,
        Bm25Retriever(corpus.documents),
        TemplateCandidate(),
        judge=OfflineStubJudge(),
    )


# --- kappa maths ------------------------------------------------------------


def test_perfect_agreement_with_variance_is_one():
    pairs = [(ACCEPTABLE, ACCEPTABLE)] * 5 + [(UNACCEPTABLE, UNACCEPTABLE)] * 5
    assert cohens_kappa(pairs).kappa == 1.0


def test_total_disagreement_is_negative():
    pairs = [(ACCEPTABLE, UNACCEPTABLE)] * 5 + [(UNACCEPTABLE, ACCEPTABLE)] * 5
    assert cohens_kappa(pairs).kappa == -1.0


def test_chance_level_agreement_is_zero():
    pairs = [
        (ACCEPTABLE, ACCEPTABLE),
        (ACCEPTABLE, UNACCEPTABLE),
        (UNACCEPTABLE, ACCEPTABLE),
        (UNACCEPTABLE, UNACCEPTABLE),
    ]
    assert cohens_kappa(pairs).kappa == 0.0


def test_high_agreement_can_still_be_worthless():
    """The trap: one rater never varies, so agreeing with it means nothing."""
    pairs = [(ACCEPTABLE, ACCEPTABLE)] * 8 + [(UNACCEPTABLE, ACCEPTABLE)]
    result = cohens_kappa(pairs)
    assert result.observed > 0.85
    assert result.kappa == 0.0
    assert result.interpretation == "none or worse than chance"


def test_no_variance_at_all_leaves_kappa_undefined():
    result = cohens_kappa([(ACCEPTABLE, ACCEPTABLE)] * 10)
    assert result.kappa is None
    assert "single category" in result.undefined
    assert "100% raw agreement" in result.undefined


def test_no_overlap_is_reported_not_crashed():
    result = cohens_kappa([])
    assert result.kappa is None
    assert result.n == 0


# --- rater derivation -------------------------------------------------------


def test_ungradable_cases_are_excluded_from_the_gate_rater():
    corpus = Corpus.load("corpus")
    from judgeguard.adapters import CannedRetriever

    mocked = run(corpus, CannedRetriever(corpus.documents), TemplateCandidate())
    graded = gate_labels(mocked)
    assert len(graded) <= len(mocked.outcomes)


def test_self_judged_scores_are_excluded(result):
    corpus = Corpus.load("corpus")

    class SelfJudge:
        id = "self"

        def score(self, transcript, case):
            return [JudgeScore("groundedness", 9.0, "self", "self", self_judged=True)]

    tainted = run(
        corpus, Bm25Retriever(corpus.documents), TemplateCandidate(), judge=SelfJudge()
    )
    assert judge_labels(tainted) == {}, (
        "a model rating its own output is not an independent rater and must not "
        "contribute to agreement statistics"
    )


def test_judge_threshold_moves_the_boundary(result):
    lenient = judge_labels(result, threshold=1.0)
    strict = judge_labels(result, threshold=9.0)
    assert set(lenient.values()) == {ACCEPTABLE}
    assert set(strict.values()) == {UNACCEPTABLE}


# --- label sheet ------------------------------------------------------------


def test_sheet_round_trips(tmp_path, result):
    sheet = tmp_path / "labels.csv"
    written = emit(sheet, result)
    assert written == len(result.outcomes)

    loaded = load(sheet)
    assert set(loaded) == {o.case.id for o in result.outcomes}
    assert all(row.label == "" for row in loaded.values())


def test_sheet_has_every_column(tmp_path, result):
    sheet = tmp_path / "labels.csv"
    emit(sheet, result)
    with sheet.open(newline="", encoding="utf-8") as handle:
        assert tuple(next(csv.reader(handle))) == COLUMNS


def test_emit_refuses_to_discard_existing_labels(tmp_path, result):
    sheet = tmp_path / "labels.csv"
    emit(sheet, result)
    with pytest.raises(SheetExists, match="already exists"):
        emit(sheet, result)
    assert emit(sheet, result, force=True) == len(result.outcomes)


def test_invalid_label_fails_loud(tmp_path, result):
    sheet = tmp_path / "labels.csv"
    emit(sheet, result)

    rows = list(csv.DictReader(sheet.open(newline="", encoding="utf-8")))
    rows[0]["label"] = "maybe"
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="not one of"):
        load(sheet)


def test_answers_with_newlines_survive_the_round_trip(tmp_path, result):
    """The templated answer is multi-line, so naive line splitting corrupts the sheet."""
    sheet = tmp_path / "labels.csv"
    emit(sheet, result)
    loaded = load(sheet)
    assert any("\n" in row.answer for row in loaded.values())
    assert len(loaded) == len(result.outcomes)


# --- end to end -------------------------------------------------------------


def test_human_labels_enter_the_comparison(tmp_path, result):
    sheet = tmp_path / "labels.csv"
    emit(sheet, result)

    rows = list(csv.DictReader(sheet.open(newline="", encoding="utf-8")))
    for row in rows:
        row["label"] = UNACCEPTABLE if row["verdict"] == "fail" else ACCEPTABLE
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    results = compare(result, load(sheet))
    pairs = {(r.a, r.b) for r in results}
    assert (HUMAN, GATE) in pairs
    assert (HUMAN, JUDGE) in pairs
    assert (GATE, JUDGE) in pairs

    human_gate = next(r for r in results if (r.a, r.b) == (HUMAN, GATE))
    assert human_gate.observed == 1.0


def test_render_states_the_self_judge_exclusion(result):
    assert "Self-judged scores are excluded" in render(compare(result))


def test_render_handles_nothing_to_compare():
    assert "Nothing to compare" in render([])
