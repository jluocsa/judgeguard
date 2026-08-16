"""Every source the case expects has to actually come back.

This is a binary outcome assertion, not a ranking metric: the question is whether the
authoritative document was returned at all, not where it placed. That distinction is
why it can gate. NDCG has a tunable threshold and reintroduces the argument the two
lanes exist to end; "the engagement letter was not in the results" does not.

`docs/evaluator-coverage.md` makes the same point from the other side - if you want a
retrieval outcome to block a build, write it here where it is visible, versioned and
reviewable, rather than inheriting a gate from a metric's default threshold.

A case that expects no sources is silent here. Whether returning nothing was correct
is `expected_behavior`'s question, not this one.
"""

from __future__ import annotations

from ...corpus import Case
from ...transcript import L1, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check

NAME = "expected_sources"


@check(NAME, L1)
def expected_sources(transcript: Transcript, case: Case) -> CheckResult:
    if not case.expected_sources:
        return CheckResult(NAME, PASS, "no sources declared")

    returned = set()
    for passage in transcript.passages:
        returned.add(passage.get("id"))
        returned.add(passage.get("source"))

    missing = sorted(set(case.expected_sources) - returned)
    if missing:
        return CheckResult(
            NAME,
            FAIL,
            f"expected source(s) not retrieved: {missing}",
        )
    return CheckResult(
        NAME, PASS, f"{len(case.expected_sources)} expected source(s) retrieved"
    )
