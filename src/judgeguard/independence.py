"""Judge independence: a model may not evaluate itself.

A judge sharing a deployment with the candidate exhibits self-preference bias, so
its score is not an independent check. judgeguard refuses to start rather than
producing a number that looks like evidence and is not.

Enforced by tests/test_independence_guard.py.
"""

from __future__ import annotations


class JudgeIndependenceError(RuntimeError):
    pass


def assert_independent(candidate: str, judge: str, *, allow_self: bool = False) -> bool:
    """Return whether scores must be marked SELF. Raises unless explicitly overridden."""
    if candidate != judge:
        return False
    if allow_self:
        return True
    raise JudgeIndependenceError(
        f"judge deployment == candidate deployment ({candidate})\n"
        "  A judge cannot independently evaluate itself.\n"
        "  Set JUDGEGUARD_JUDGE_DEPLOYMENT, or pass --allow-self-judge to override\n"
        "  (scores will be marked SELF and excluded from agreement statistics)."
    )
