"""Scorer backends for the advisory judge lane.

Every scorer here implements `judgeguard.lanes.judge.Judge`. Which one you use
changes what appears in the score column and changes nothing about what gates.
"""

from ..lanes.judge import Judge, JudgeScore, OfflineStubJudge

__all__ = ["Judge", "JudgeScore", "OfflineStubJudge", "build"]


def build(name: str, **kwargs) -> Judge:
    if name in ("offline", "stub", "none"):
        return OfflineStubJudge()
    if name == "foundry":
        from .foundry.scorer import FoundryScorer

        return FoundryScorer(**kwargs)
    raise RuntimeError(f"unknown scorer {name!r}; known: offline, foundry")
