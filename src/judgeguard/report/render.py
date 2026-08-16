"""Terminal and markdown rendering. The verdict column and the score column are
always rendered as separate columns, so nobody reads them as one number.
"""

from __future__ import annotations

from ..lanes.deterministic import FAIL, PASS, UNGRADABLE
from ..runner import RunResult
from ..transcript import EVIDENCE_LEVEL_MEANING

GLYPH = {PASS: "\u2713", FAIL: "\u2717", UNGRADABLE: "\u25cb"}


def summary(run: RunResult) -> str:
    failed = len(run.failed)
    checks = run.all_checks
    ungradable = sum(1 for c in checks if c.status == UNGRADABLE)
    score = run.mean_score
    lines = [
        f"{GLYPH[FAIL] if failed else GLYPH[PASS]} VERDICT   "
        f"{failed} failed, {len(run.outcomes) - failed} passed",
        f"{GLYPH[UNGRADABLE]} SCORE     "
        + (
            f"{score}/10  advisory - does not affect exit code"
            if score is not None
            else "no judge configured"
        ),
        f"\u26a0 EVIDENCE  {run.evidence_level}  "
        f"{EVIDENCE_LEVEL_MEANING[run.evidence_level]}",
    ]
    if ungradable:
        blocked = sorted({c.check for c in checks if c.status == UNGRADABLE})
        lines.append(
            f"{GLYPH[UNGRADABLE]} UNGRADED  {ungradable}/{len(checks)} checks could not "
            f"run at {run.evidence_level}: {', '.join(blocked)}"
        )
    for outcome in run.failed:
        for check in outcome.checks:
            if check.status == FAIL:
                lines.append(f"    {outcome.case.id}  {check.check}: {check.detail}")
    return "\n".join(lines)


def markdown(run: RunResult) -> str:
    rows = [
        f"# judgeguard: {run.provider} / {run.candidate_id}",
        "",
        f"Evidence level **{run.evidence_level}** - {EVIDENCE_LEVEL_MEANING[run.evidence_level]}",
        "",
        "| case | variant | verdict (gates) | score (advisory) | failing checks |",
        "| --- | --- | --- | --- | --- |",
    ]
    for outcome in run.outcomes:
        score = (
            round(sum(s.score for s in outcome.scores) / len(outcome.scores), 2)
            if outcome.scores
            else "-"
        )
        failing = ", ".join(c.check for c in outcome.checks if c.status == FAIL) or "-"
        rows.append(
            f"| {outcome.case.id} | {outcome.case.variant} | "
            f"{GLYPH[outcome.verdict]} {outcome.verdict} | {score} | {failing} |"
        )
    rows += [
        "",
        "The score column is produced by a judge and cannot influence the exit code.",
    ]
    return "\n".join(rows)
