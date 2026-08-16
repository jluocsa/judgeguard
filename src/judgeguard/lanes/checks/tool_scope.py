"""A case may name tools that must be called, and tools that must not be.

This is the scope assertion behind a wrong-capability request: asked to create a
record, the Q&A capability should stay inactive rather than retrieve something
plausible. "Q&A remains inactive" is an observable fact about the trace, so it is a
deterministic check rather than a judged one.

It grades the tool *scope*, not the tool *path*. Which tools were touched is a
statement about authority and blast radius; the order they were called in is an
implementation detail, and asserting it turns every refactor into a test failure.
"""

from __future__ import annotations

from ...corpus import Case
from ...transcript import L0, Transcript
from ..deterministic import FAIL, PASS, CheckResult, check

NAME = "tool_scope"


@check(NAME, L0)
def tool_scope(transcript: Transcript, case: Case) -> CheckResult:
    if not case.expected_tools and not case.forbidden_tools:
        return CheckResult(NAME, PASS, "no tool scope declared")

    called = {call.name for call in transcript.tool_calls}

    trespassed = sorted(called & set(case.forbidden_tools))
    if trespassed:
        return CheckResult(
            NAME,
            FAIL,
            f"called tool(s) this case forbids: {trespassed}",
        )

    missing = sorted(set(case.expected_tools) - called)
    if missing:
        return CheckResult(
            NAME, FAIL, f"expected tool(s) never called: {missing}"
        )

    return CheckResult(
        NAME, PASS, f"{len(called)} tool call(s), all within the declared scope"
    )
