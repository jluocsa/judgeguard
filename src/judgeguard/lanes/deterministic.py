"""The deterministic lane. This lane, and only this lane, sets the exit code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..corpus import Case
from ..transcript import L0, Transcript, meets

PASS = "pass"
FAIL = "fail"
UNGRADABLE = "ungradable"


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: str
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == FAIL


@runtime_checkable
class Check(Protocol):
    name: str
    min_evidence_level: str

    def __call__(self, transcript: Transcript, case: Case) -> CheckResult: ...


def check(name: str, min_evidence_level: str):
    """Attach the metadata `run_checks` needs to decide gradability."""

    def decorate(fn):
        fn.name = name
        fn.min_evidence_level = min_evidence_level
        return fn

    return decorate


def ungradable(check: Check, actual: str) -> CheckResult:
    return CheckResult(
        check=check.name,
        status=UNGRADABLE,
        detail=(
            f"needs {check.min_evidence_level}, run is {actual} "
            f"- no world state for this assertion to read"
        ),
    )


def run_checks(
    checks: list[Check], transcript: Transcript, case: Case
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in checks:
        if not meets(transcript.evidence_level or L0, check.min_evidence_level):
            results.append(ungradable(check, transcript.evidence_level or L0))
            continue
        results.append(check(transcript, case))
    return results
