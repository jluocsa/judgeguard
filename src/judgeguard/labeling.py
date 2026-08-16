"""Human labels: emit a sheet, read it back.

CSV rather than JSONL because a person fills this in, usually in a spreadsheet.
The label is deliberately binary. A human asked for a 0-10 score produces noise;
a human asked "would you ship this answer" produces a usable ground truth.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path

from .runner import RunResult

ACCEPTABLE = "acceptable"
UNACCEPTABLE = "unacceptable"
LABELS = (ACCEPTABLE, UNACCEPTABLE)

ANSWER_PREVIEW = 400


@dataclass(frozen=True)
class LabelRow:
    case_id: str
    variant: str
    query: str
    answer: str
    sources: str
    verdict: str
    judge_score: str
    self_judged: str
    label: str = ""
    note: str = ""


COLUMNS = tuple(f.name for f in fields(LabelRow))


class SheetExists(RuntimeError):
    pass


def emit(path: str | Path, run: RunResult, *, force: bool = False) -> int:
    path = Path(path)
    if path.exists() and not force:
        raise SheetExists(
            f"{path} already exists. Overwriting discards any labels already "
            "entered - pass --force if that is what you want."
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for outcome in run.outcomes:
        scores = [s for s in outcome.scores]
        mean = (
            round(sum(s.score for s in scores) / len(scores), 2) if scores else ""
        )
        rows.append(
            LabelRow(
                case_id=outcome.case.id,
                variant=outcome.case.variant,
                query=outcome.case.query,
                answer=outcome.transcript.answer[:ANSWER_PREVIEW],
                sources=" ".join(p["id"] for p in outcome.transcript.passages),
                verdict=outcome.verdict,
                judge_score=str(mean),
                self_judged=str(any(s.self_judged for s in scores)).lower(),
            )
        )

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: getattr(row, c) for c in COLUMNS})
    return len(rows)


def load(path: str | Path) -> dict[str, LabelRow]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no label sheet at {path}; run `judgeguard label` first")

    loaded: dict[str, LabelRow] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for number, raw in enumerate(csv.DictReader(handle), start=2):
            missing = [c for c in COLUMNS if c not in raw]
            if missing:
                raise ValueError(f"{path}:{number} is missing columns {missing}")
            label = (raw["label"] or "").strip().lower()
            if label and label not in LABELS:
                raise ValueError(
                    f"{path}:{number} label {label!r} is not one of {list(LABELS)}"
                )
            loaded[raw["case_id"]] = LabelRow(
                **{**{c: raw[c] for c in COLUMNS}, "label": label}
            )
    return loaded


def labelled(rows: dict[str, LabelRow]) -> dict[str, str]:
    return {case_id: row.label for case_id, row in rows.items() if row.label}
