"""Saved baselines with a regression tolerance, and per-run deltas.

The verdict column and the score column are compared separately and reported
separately, because a judge score moving is information and a verdict flipping is
a build failure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .runner import RunResult

DEFAULT_TOLERANCE = 0.5


@dataclass(frozen=True)
class Delta:
    case_id: str
    kind: str
    before: str | float | None
    after: str | float | None
    regressed: bool


def snapshot(run: RunResult) -> dict:
    return {
        "provider": run.provider,
        "candidate": run.candidate_id,
        "evidence_level": run.evidence_level,
        "cases": {
            o.case.id: {
                "verdict": o.verdict,
                "score": (
                    round(sum(s.score for s in o.scores) / len(o.scores), 3)
                    if o.scores
                    else None
                ),
            }
            for o in run.outcomes
        },
    }


def save(path: str | Path, run: RunResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(run), indent=2) + "\n", encoding="utf-8")


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(
    baseline: dict, run: RunResult, *, tolerance: float = DEFAULT_TOLERANCE
) -> list[Delta]:
    previous = baseline.get("cases", {})
    current = snapshot(run)["cases"]
    deltas: list[Delta] = []

    for case_id, now in current.items():
        was = previous.get(case_id)
        if was is None:
            deltas.append(Delta(case_id, "verdict", None, now["verdict"], False))
            continue
        if was["verdict"] != now["verdict"]:
            deltas.append(
                Delta(
                    case_id,
                    "verdict",
                    was["verdict"],
                    now["verdict"],
                    regressed=now["verdict"] == "fail",
                )
            )
        if was.get("score") is not None and now.get("score") is not None:
            drop = was["score"] - now["score"]
            if abs(drop) > tolerance:
                deltas.append(
                    Delta(case_id, "score", was["score"], now["score"], drop > 0)
                )

    for case_id in previous.keys() - current.keys():
        deltas.append(Delta(case_id, "missing", previous[case_id]["verdict"], None, True))

    return deltas
