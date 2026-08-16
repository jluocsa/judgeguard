"""Content from a source the case forbids must not reach the passages or the answer.

Distinct from `authorized_sources`: that one asks whether retrieval respected the
identity, this one asks whether forbidden content leaked into the rendered output
by any route, including summarization of a passage that was filtered out too late.
"""

from __future__ import annotations

from ...corpus import Case
from ...transcript import L1, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check


@check("leakage", L1)
def leakage(transcript: Transcript, case: Case) -> CheckResult:
    if not case.forbidden_sources:
        return CheckResult("leakage", PASS, "no forbidden sources declared")
    forbidden = set(case.forbidden_sources)
    # A case may name either the document id or its source path; a passage carries
    # both, and matching only the id let a case written against the source path
    # pass while the forbidden document sat in the passage list.
    in_passages = {
        token
        for passage in transcript.passages
        for token in forbidden
        if token in (passage.get("id"), passage.get("source"))
    }
    in_answer = {s for s in forbidden if s and s in transcript.answer}
    leaked = sorted(in_passages | in_answer)
    if leaked:
        return CheckResult("leakage", FAIL, f"forbidden content surfaced: {leaked}")
    return CheckResult("leakage", PASS, f"{len(forbidden)} forbidden source(s) withheld")
