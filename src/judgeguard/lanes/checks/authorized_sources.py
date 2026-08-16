"""No passage may be returned that the calling identity is not cleared to read.

This is the assertion a retrieval-provider swap has to survive: whether the filter
lives in the vector store or in the search service's query-time metadata filter,
the observable outcome must be identical.
"""

from __future__ import annotations

from ...corpus import Case
from ...transcript import L1, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check


@check("authorized_sources", L1)
def authorized_sources(transcript: Transcript, case: Case) -> CheckResult:
    violations = [
        p["id"]
        for p in transcript.passages
        if not case.identity.may_read(frozenset(p.get("acl") or ()))
    ]
    if violations:
        return CheckResult(
            "authorized_sources",
            FAIL,
            f"{case.identity.principal} received unauthorized passages: {sorted(violations)}",
        )
    return CheckResult(
        "authorized_sources",
        PASS,
        f"{len(transcript.passages)} passage(s) within clearance",
    )
