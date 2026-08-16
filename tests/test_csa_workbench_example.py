"""The CSA Workbench example must keep working, and keep telling the truth.

Two things are asserted here. That the ingest produces judgeguard types correctly, so
the two-lane invariant survives data arriving from outside - a judge score that came
from another system still cannot gate. And that the degenerate-kappa guard holds,
because the failure it prevents is the one this repository exists to prevent: printing
a number that describes the gate's variance as though it described the judge.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from judgeguard.agreement import cohens_kappa
from judgeguard.gate import EXIT_VERDICT_FAILED, exit_code
from judgeguard.labeling import ACCEPTABLE, UNACCEPTABLE
from judgeguard.lanes.deterministic import PASS
from judgeguard.transcript import L2

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "csa-workbench"
sys.path.insert(0, str(EXAMPLE))

EVALUATOR_NAMES = (
    "intent_resolution",
    "task_adherence",
    "task_completion",
    "tool_call_accuracy",
    "tool_call_success",
    "tool_input_accuracy",
    "tool_output_utilization",
    "tool_selection",
)

ingest = pytest.importorskip("ingest", reason="the csa-workbench example is not present")


@pytest.fixture(scope="module")
def items():
    return ingest.load(EXAMPLE / "sample-run.json")


@pytest.fixture(scope="module")
def run(items):
    return ingest.to_run_result(items)


# --- the ingest -------------------------------------------------------------


def test_every_row_becomes_an_outcome(items, run):
    assert len(run.outcomes) == len(items)
    assert run.evidence_level == L2, "a real agent run under a real model produced these"


def test_the_deterministic_verdict_stays_deterministic(run):
    """harness_pass arrives as a CheckResult, so it keeps its ability to gate."""
    for outcome in run.outcomes:
        assert len(outcome.checks) == 1
        assert outcome.checks[0].check == ingest.GATE_CHECK
    assert all(o.verdict == PASS for o in run.outcomes)


def test_judge_scores_from_another_system_still_cannot_gate(run):
    """The invariant has to survive data that judgeguard did not produce."""
    scores = [s for o in run.outcomes for s in o.scores]
    assert scores, "the sample run carries judge scores"
    with pytest.raises(TypeError, match="only deterministic CheckResult"):
        exit_code(scores)


def test_the_gate_alone_decides_the_exit_code(run):
    assert exit_code(run.all_checks) != EXIT_VERDICT_FAILED

    failing = ingest.to_run_result(
        [{**items_row, "harness_pass": False} for items_row in ingest.load(
            EXAMPLE / "sample-run.json")]
    )
    assert exit_code(failing.all_checks) == EXIT_VERDICT_FAILED


def test_skipped_evaluations_are_excluded_not_scored_zero(items, run):
    """Averaging a skip in as zero would manufacture a judgement nobody made."""
    skipped = sum(
        1
        for item in items
        for result in item["results"]
        if result.get("status") == ingest.SKIPPED
    )
    assert skipped, "the sample run contains skipped evaluations"

    ingested = sum(len(o.scores) for o in run.outcomes)
    total = sum(len(item["results"]) for item in items)
    assert ingested == total - skipped


def test_turn_index_keeps_multi_turn_cases_distinct(run):
    """A multi-turn case repeats its item_id; collapsing them would lose turns."""
    ids = [o.case.id for o in run.outcomes]
    assert len(ids) == len(set(ids))


# --- the number that must not be printed ------------------------------------


@pytest.mark.parametrize("failures", [0, 1, 3, 5, 10])
def test_a_single_category_gate_forces_kappa_to_zero(failures):
    """The arithmetic behind the guard, asserted rather than asserted about.

    With the gate on one category, agreement happens exactly when the judge agrees,
    so observed == expected and kappa is 0 however badly the judge does. Reporting it
    would describe the gate's variance as a fact about the judge.
    """
    pairs = [(ACCEPTABLE, ACCEPTABLE)] * (11 - failures)
    pairs += [(ACCEPTABLE, UNACCEPTABLE)] * failures
    result = cohens_kappa(pairs)
    if failures == 0:
        assert result.kappa is None  # both raters single-category
    else:
        assert result.kappa == 0.0
        assert result.observed == pytest.approx(result.expected)


def test_the_example_refuses_to_report_kappa_for_this_run(items):
    assert ingest.gate_is_degenerate(items)


def test_a_varying_gate_makes_kappa_reportable_again(items):
    flipped = [dict(item) for item in items]
    flipped[0]["harness_pass"] = False
    assert not ingest.gate_is_degenerate(flipped)


# --- the finding ------------------------------------------------------------


def test_disagreements_are_reported_per_turn(items):
    found = ingest.disagreements(items)
    assert found, "the sample run contains judge/oracle disagreements"
    for names in found.values():
        assert names


def test_the_example_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, "ingest.py"],
        cwd=EXAMPLE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert "kappa is not reportable" in result.stdout

    # Every evaluator row must carry n/a in the kappa column. Matched on the table
    # row shape - name, count, percentage - rather than anywhere the name appears,
    # because the disagreement list names evaluators too, and the explanation of why
    # kappa is forced to 0.000 legitimately contains that number.
    table_row = re.compile(
        rf"^\s+({'|'.join(EVALUATOR_NAMES)})\s+\d+\s+\d+%\s+(\S+)"
    )
    rows = [m for m in (table_row.match(l) for l in result.stdout.splitlines()) if m]
    assert len(rows) == len(EVALUATOR_NAMES), [m.group(0) for m in rows]
    for match in rows:
        assert match.group(2) == "n/a", (
            f"a degenerate kappa was printed for {match.group(1)}: {match.group(2)}"
        )


def test_the_sample_run_is_valid_json():
    rows = json.loads((EXAMPLE / "sample-run.json").read_text(encoding="utf-8"))
    assert rows
    for row in rows:
        assert {"item_id", "turn", "harness_pass", "results"} <= set(row)
