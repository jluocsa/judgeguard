"""Grade a CSA Workbench Foundry run with judgeguard, without rerunning anything.

CSA Workbench already has a good deterministic oracle. `harness.py` diffs the whole
Engagement store, enforces the role-rank rules, and rides its `harness_pass` verdict
into Foundry *with* each row, so the deterministic verdict and the judge scores land
side by side. Nothing here replaces that, and nothing here re-runs the agent.

What this adds is the question that run cannot answer on its own: **are those judges
worth anything?** A completed run reports `8/11` and `10/11` per evaluator, and those
numbers look like quality measurements. Whether they track the deterministic oracle -
the only rater here with a defensible claim to being right - is a separate question,
and it is measurable.

This is also a working prototype of transcript ingest. judgeguard's `run()` drives a
retriever and a candidate, so it cannot grade an agent that owns its own tool loop.
Reading a finished run into judgeguard's own types is the way in, and everything
downstream - the two lanes, the agreement statistics - then works unchanged.

    python ingest.py                      # the committed sample run
    python ingest.py --results path.json  # a run you produced
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from judgeguard.agreement import cohens_kappa
from judgeguard.contract import Identity
from judgeguard.corpus import Case
from judgeguard.labeling import ACCEPTABLE, UNACCEPTABLE
from judgeguard.lanes.deterministic import FAIL, PASS, CheckResult
from judgeguard.lanes.judge import JudgeScore
from judgeguard.runner import CaseOutcome, RunResult
from judgeguard.transcript import L2, Transcript

HERE = Path(__file__).parent
SAMPLE = HERE / "sample-run.json"

# The oracle's own name for its verdict, carried on every dataset row.
GATE_CHECK = "harness_pass"

# Foundry marks an evaluator it declined to run. A skipped evaluation is not a zero:
# scoring it would invent a judgement nobody made.
SKIPPED = "skipped"


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def to_run_result(items: list[dict]) -> RunResult:
    """Read a finished Foundry run into judgeguard's types.

    The deterministic verdict becomes a CheckResult, so it keeps its ability to gate.
    Every evaluator becomes a JudgeScore, so none of them can. That mapping is the
    whole point: it is chosen once, here, rather than argued about per release.
    """
    outcomes = []
    for index, item in enumerate(items):
        # Turn index disambiguates multi-turn cases, which repeat their item_id.
        case_id = f"{item['item_id']}#{item['turn']}"
        case = Case(
            id=case_id,
            query=item.get("query", ""),
            identity=Identity(principal="csa", clearances=frozenset()),
        )
        transcript = Transcript(
            case_id=case_id,
            query=item.get("query", ""),
            principal="csa",
            provider="csa-workbench/agent-framework-lane",
            # A real agent run under a real model produced this.
            evidence_level=L2,
        )
        passed = bool(item["harness_pass"])
        check = CheckResult(
            GATE_CHECK,
            PASS if passed else FAIL,
            "deterministic state oracle" if passed else "state oracle rejected the turn",
        )
        scores = [
            JudgeScore(
                dimension=result["name"],
                score=float(result["score"]),
                reasoning=result.get("reason", ""),
                judge_id="foundry:csa-workbench-run",
            )
            for result in item["results"]
            if result.get("status") != SKIPPED and result.get("score") is not None
        ]
        outcomes.append(
            CaseOutcome(case=case, transcript=transcript, checks=[check], scores=scores)
        )
    return RunResult(
        provider="csa-workbench/agent-framework-lane",
        candidate_id="agent-framework-lane",
        evidence_level=L2,
        outcomes=outcomes,
    )


def per_evaluator_agreement(items: list[dict]):
    """Kappa per evaluator, never on a mean across them.

    judgeguard's default `judge_labels` averages every score and thresholds the mean.
    That is wrong for this run and would quietly produce a number: two evaluators are
    scored 1-5 and six are scored 0/1, so their mean is not on any scale, and the
    thresholds differ per evaluator too. Each evaluator's own `passed` flag is the
    only defensible verdict, so each is compared to the gate separately.
    """
    pairs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    skipped: dict[str, int] = defaultdict(int)

    for item in items:
        gate = ACCEPTABLE if item["harness_pass"] else UNACCEPTABLE
        for result in item["results"]:
            name = result["name"]
            if result.get("status") == SKIPPED or result.get("score") is None:
                skipped[name] += 1
                continue
            judge = ACCEPTABLE if result["passed"] else UNACCEPTABLE
            pairs[name].append((gate, judge))

    return {name: (cohens_kappa(rows), skipped[name]) for name, rows in sorted(pairs.items())}


def gate_is_degenerate(items: list[dict]) -> bool:
    """True when the gate used a single category, which makes kappa meaningless.

    Worth stating plainly because the number still prints. If the gate passes every
    turn then agreement happens exactly when the judge also passes, so observed and
    expected agreement are identically equal and kappa is forced to 0.000 - whether
    the judge failed one turn or nine. It is arithmetic about the gate's variance,
    not a measurement of the judge.
    """
    return len({bool(item["harness_pass"]) for item in items}) < 2


def disagreements(items: list[dict]) -> dict[str, list[str]]:
    """Turns the oracle passed and at least one judge failed."""
    found: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if not item["harness_pass"]:
            continue
        for result in item["results"]:
            if result.get("status") == SKIPPED or result.get("score") is None:
                continue
            if not result["passed"]:
                found[f"{item['item_id']}#{item['turn']}"].append(result["name"])
    return found


def skipped_reasons(items: list[dict]) -> list[tuple[str, str, str]]:
    out = []
    for item in items:
        for result in item["results"]:
            if result.get("status") == SKIPPED:
                out.append((f"{item['item_id']}#{item['turn']}", result["name"],
                            result.get("reason", "")))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=str(SAMPLE), help="Foundry eval run JSON")
    arguments = parser.parse_args()

    items = load(Path(arguments.results))
    run = to_run_result(items)

    graded = [o for o in run.outcomes if o.verdict == PASS]
    print(f"ingested {len(run.outcomes)} turns at {run.evidence_level} "
          f"from {run.provider}")
    print(f"deterministic gate: {len(graded)}/{len(run.outcomes)} passed\n")

    degenerate = gate_is_degenerate(items)

    print("agreement with the deterministic oracle, per evaluator")
    print(f"  {'evaluator':<26}{'n':>3}  {'agree':>6}  {'kappa':>9}  skipped")
    for name, (agreement, skips) in per_evaluator_agreement(items).items():
        kappa = "n/a" if degenerate or agreement.kappa is None else f"{agreement.kappa:.2f}"
        print(
            f"  {name:<26}{agreement.n:>3}  {agreement.observed:>5.0%}  "
            f"{kappa:>9}  {skips or '-'}"
        )

    if degenerate:
        print(
            "\n  kappa is not reportable for this run, and the reason is worth keeping.\n"
            "  The gate passed every turn. When one rater uses a single category,\n"
            "  agreement happens exactly when the other rater agrees, so observed and\n"
            "  expected agreement are identically equal and kappa is forced to 0.000 -\n"
            "  whether the judge failed one turn or nine. Printing it as a score would\n"
            "  be reporting arithmetic about the gate's variance as a fact about the\n"
            "  judge.\n"
            "\n  To get a discriminating number, compare against a rater that varies:\n"
            "  a run containing real gate failures, or human labels via `judgeguard\n"
            "  label` then `judgeguard agree`. Raw agreement above is descriptive only."
        )

    contradicted = disagreements(items)
    if contradicted:
        print("\nturns the oracle passed and a judge failed")
        for case_id, names in contradicted.items():
            print(f"  {case_id}")
            print(f"    {', '.join(names)}")
        print(
            "\nThe pattern is the finding, not the count. These are not spread evenly\n"
            "across the suite - they cluster on two shapes of turn:\n"
            "\n  Declining was correct. A refusal of an action the caller was not\n"
            "  authorized to take, and a clarification asked instead of a guess. The\n"
            "  agent was penalised for behaving well. Judges are known to score correct\n"
            "  refusals poorly, which is precisely why a judge score must never reach an\n"
            "  exit code.\n"
            "\n  The judge could not see prior turns. A terse referential turn cannot be\n"
            "  graded without the conversation that gives it a referent, and several\n"
            "  evaluators skipped outright saying so. That is a payload problem, not an\n"
            "  agent problem, and it inflates nothing - it silently deflates."
        )

    skips = skipped_reasons(items)
    if skips:
        print(f"\n{len(skips)} evaluations were skipped by the service and are excluded")
        print("  A skipped evaluation is not a zero. Averaging it in as one would")
        print("  manufacture a judgement nobody made.")
        for case_id, name, reason in skips[:3]:
            print(f"    {case_id:<34}{name:<24}{reason[:58]}")
        if len(skips) > 3:
            print(f"    ... and {len(skips) - 3} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
