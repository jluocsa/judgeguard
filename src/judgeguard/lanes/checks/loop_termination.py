"""A retrieve-judge-refine loop must terminate within a declared budget."""

from __future__ import annotations

from ...corpus import Case
from ...transcript import L0, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check

MAX_TOOL_CALLS = 8


@check("loop_termination", L0)
def loop_termination(transcript: Transcript, case: Case) -> CheckResult:
    budget = int(transcript.meta.get("max_tool_calls", MAX_TOOL_CALLS))
    used = len(transcript.tool_calls)
    if used > budget:
        return CheckResult(
            "loop_termination", FAIL, f"{used} tool calls exceeds budget of {budget}"
        )
    return CheckResult("loop_termination", PASS, f"{used}/{budget} tool calls")
