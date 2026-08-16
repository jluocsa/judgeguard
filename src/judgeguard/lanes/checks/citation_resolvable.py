"""Every citation in the answer must resolve to a passage the run actually retrieved."""

from __future__ import annotations

import re

from ...corpus import Case
from ...transcript import L0, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check

CITATION = re.compile(r"\[S:([^\]]+)\]")


@check("citation_resolvable", L0)
def citation_resolvable(transcript: Transcript, case: Case) -> CheckResult:
    cited = set(CITATION.findall(transcript.answer))
    retrieved = {p["id"] for p in transcript.passages}
    dangling = sorted(cited - retrieved)
    if dangling:
        return CheckResult(
            "citation_resolvable", FAIL, f"cites passages not retrieved: {dangling}"
        )
    # An answer with nothing retrieved is a refusal, which is correct behaviour.
    if not cited and transcript.passages:
        return CheckResult(
            "citation_resolvable", FAIL, "answer cites none of the retrieved passages"
        )
    if not cited:
        return CheckResult("citation_resolvable", PASS, "refusal, nothing retrieved")
    return CheckResult("citation_resolvable", PASS, f"{len(cited)} citation(s) resolved")
