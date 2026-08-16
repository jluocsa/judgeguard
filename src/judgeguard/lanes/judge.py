"""The judge lane. Advisory by construction.

Nothing in this module returns a `CheckResult`, and `gate.exit_code` accepts
nothing else. A judge score can therefore appear in a report, a trend and an
agreement statistic, and can never appear in a process exit code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..corpus import Case
from ..transcript import Transcript


@dataclass(frozen=True)
class JudgeScore:
    dimension: str
    score: float
    reasoning: str
    judge_id: str
    self_judged: bool = False


@runtime_checkable
class Judge(Protocol):
    id: str

    def score(self, transcript: Transcript, case: Case) -> list[JudgeScore]: ...


class OfflineStubJudge:
    """Placeholder so the two-lane report renders with no API key.

    It calls no model. Its scores exist to show where real judge output lands and
    are excluded from agreement statistics.
    """

    id = "offline-stub"

    def score(self, transcript: Transcript, case: Case) -> list[JudgeScore]:
        grounded = bool(transcript.passages) and bool(transcript.answer)
        return [
            JudgeScore(
                dimension="groundedness",
                score=7.0 if grounded else 0.0,
                reasoning="offline stub - no model was called",
                judge_id=self.id,
            )
        ]
