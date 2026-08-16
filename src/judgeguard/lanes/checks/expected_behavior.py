"""The run has to end the way the case said it would.

Four end behaviours are declarable: answer, no result, refusal, clarification. The
distinction matters because two of them produce the same retrieval transcript. A run
that returned nothing because the material was not indexed and a run that returned
nothing because the caller was not cleared are identical at the retrieval layer, and
only the declared expectation separates them.

That is also why this check reports `ungradable` more often than it passes. A refusal
is a property of the generated answer, and a clarification is the absence of a
retrieval that a fixed harness always performs. Neither is visible in an L1 run, so
neither is graded at L1 - saying so is the point, because the alternative is a green
check that means nothing.
"""

from __future__ import annotations

from ...corpus import ANSWER, CLARIFICATION, NO_RESULT, REFUSAL, Case
from ...transcript import L1, Transcript
from ..deterministic import FAIL, PASS, UNGRADABLE, CheckResult, check

NAME = "expected_behavior"


@check(NAME, L1)
def expected_behavior(transcript: Transcript, case: Case) -> CheckResult:
    declared = case.expected_behavior
    if declared is None:
        return CheckResult(NAME, PASS, "no end behaviour declared")

    passages = transcript.passages
    if declared == ANSWER:
        if not passages:
            return CheckResult(
                NAME,
                FAIL,
                "expected an answer, but retrieval returned no evidence to ground one",
            )
        return CheckResult(NAME, PASS, f"{len(passages)} passage(s) to answer from")

    if declared == NO_RESULT:
        if passages:
            return CheckResult(
                NAME,
                FAIL,
                f"expected no result, but {len(passages)} passage(s) were returned: "
                f"{sorted(p['id'] for p in passages)}",
            )
        return CheckResult(NAME, PASS, "no result, as expected")

    if declared == REFUSAL:
        # Retrieval can prove nothing forbidden surfaced - `leakage` and
        # `authorized_sources` already assert that - but not that the answer
        # declined. Claiming otherwise would grade a wrong answer as a refusal.
        return CheckResult(
            NAME,
            UNGRADABLE,
            "a refusal is a property of the generated answer; an L1 transcript "
            "cannot distinguish it from an empty or incorrect one",
        )

    if declared == CLARIFICATION:
        return CheckResult(
            NAME,
            UNGRADABLE,
            "a clarification is the absence of a retrieval; this harness retrieves "
            "unconditionally, so there is no decision to grade",
        )

    return CheckResult(NAME, UNGRADABLE, f"unknown end behaviour {declared!r}")
