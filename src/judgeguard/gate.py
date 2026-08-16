"""The only module that can produce a non-zero exit code.

`exit_code` accepts deterministic check results and nothing else. There is no
overload, no keyword argument and no configuration flag that lets a judge score
reach this function - which is what makes "judges never gate" an invariant rather
than a policy someone can quietly relax.

Enforced by tests/test_judge_cannot_gate.py.
"""

from __future__ import annotations

from typing import Iterable

from .lanes.deterministic import CheckResult

EXIT_OK = 0
EXIT_VERDICT_FAILED = 1
EXIT_PRECONDITION_FAILED = 2


def exit_code(results: Iterable[CheckResult]) -> int:
    for result in results:
        if not isinstance(result, CheckResult):
            raise TypeError(
                f"only deterministic CheckResult can affect the exit code, got "
                f"{type(result).__name__}"
            )
        if result.blocking:
            return EXIT_VERDICT_FAILED
    return EXIT_OK
