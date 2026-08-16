"""Cohen's kappa between the gate, the judge and human labels.

This is what the two-lane split buys you. Once a judge stops gating, its agreement
with ground truth becomes a measurable quantity instead of an assumption, and you
can evaluate your evaluator before trusting its scores.

Self-judged scores are excluded. A model scoring its own output is not an
independent rater, so including it would inflate the agreement it is meant to test.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence

from .labeling import ACCEPTABLE, LabelRow, UNACCEPTABLE, labelled
from .lanes.deterministic import FAIL, PASS, UNGRADABLE
from .runner import RunResult

GATE = "gate"
JUDGE = "judge"
HUMAN = "human"

DEFAULT_JUDGE_THRESHOLD = 3.0

# Landis & Koch (1977). A convention for reading kappa, not a standard.
BANDS = (
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.01, "slight"),
    (-1.0, "none or worse than chance"),
)


@dataclass(frozen=True)
class Agreement:
    a: str
    b: str
    n: int
    observed: float
    expected: float
    kappa: float | None
    matrix: dict[tuple[str, str], int] = field(default_factory=dict)
    undefined: str | None = None

    @property
    def interpretation(self) -> str:
        if self.kappa is None:
            return "undefined"
        for floor, name in BANDS:
            if self.kappa >= floor:
                return name
        return "none or worse than chance"


def cohens_kappa(pairs: Sequence[tuple[str, str]]) -> Agreement:
    n = len(pairs)
    if not n:
        return Agreement("", "", 0, 0.0, 0.0, None, undefined="no overlapping cases")

    observed = sum(1 for x, y in pairs if x == y) / n
    left = Counter(x for x, _ in pairs)
    right = Counter(y for _, y in pairs)
    categories = set(left) | set(right)
    expected = sum(left[c] * right[c] for c in categories) / (n * n)

    matrix = Counter(pairs)
    if expected >= 1.0:
        # Both raters used a single category. Agreement may be perfect, but kappa
        # divides by zero: with no variance there is nothing chance could explain.
        return Agreement(
            "",
            "",
            n,
            observed,
            expected,
            None,
            dict(matrix),
            undefined=(
                "one or both raters used a single category, so kappa has no "
                f"denominator - {observed:.0%} raw agreement over {n} cases"
            ),
        )

    kappa = round((observed - expected) / (1 - expected), 3)
    return Agreement("", "", n, round(observed, 3), round(expected, 3), kappa, dict(matrix))


def gate_labels(run: RunResult) -> dict[str, str]:
    """Ungradable cases are excluded: no verdict was reached, so there is nothing to agree with."""
    return {
        o.case.id: (ACCEPTABLE if o.verdict == PASS else UNACCEPTABLE)
        for o in run.outcomes
        if o.verdict in (PASS, FAIL)
    }


def judge_labels(
    run: RunResult, *, threshold: float = DEFAULT_JUDGE_THRESHOLD
) -> dict[str, str]:
    labels = {}
    for outcome in run.outcomes:
        scores = [s for s in outcome.scores if not s.self_judged]
        if not scores:
            continue
        mean = sum(s.score for s in scores) / len(scores)
        labels[outcome.case.id] = ACCEPTABLE if mean >= threshold else UNACCEPTABLE
    return labels


def compare(
    run: RunResult,
    labels: dict[str, LabelRow] | None = None,
    *,
    threshold: float = DEFAULT_JUDGE_THRESHOLD,
) -> list[Agreement]:
    raters = {GATE: gate_labels(run), JUDGE: judge_labels(run, threshold=threshold)}
    if labels:
        human = labelled(labels)
        if human:
            raters[HUMAN] = human

    results = []
    names = [n for n in (HUMAN, GATE, JUDGE) if raters.get(n)]
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = sorted(set(raters[a]) & set(raters[b]))
            pairs = [(raters[a][c], raters[b][c]) for c in shared]
            result = cohens_kappa(pairs)
            results.append(
                Agreement(
                    a,
                    b,
                    result.n,
                    result.observed,
                    result.expected,
                    result.kappa,
                    result.matrix,
                    result.undefined,
                )
            )
    return results


def render(results: Sequence[Agreement]) -> str:
    if not results:
        return (
            "Nothing to compare. Run with --scorer to produce judge scores, and\n"
            "`judgeguard label` to collect human labels."
        )
    lines = []
    for result in results:
        header = f"{result.a} vs {result.b}   n={result.n}"
        if result.kappa is None:
            lines += [header, f"  kappa undefined - {result.undefined}"]
        else:
            lines += [
                header,
                f"  kappa {result.kappa:>6}  ({result.interpretation})",
                f"  observed {result.observed:.0%}, expected by chance {result.expected:.0%}",
            ]
        for (x, y), count in sorted(result.matrix.items()):
            mark = "=" if x == y else "!"
            lines.append(f"    {mark} {result.a}:{x:<12} {result.b}:{y:<12} {count}")
        lines.append("")
    lines.append(
        "Self-judged scores are excluded: a model rating its own output is not an\n"
        "independent rater, and counting it would inflate the number being tested."
    )
    return "\n".join(lines)
