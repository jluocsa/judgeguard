"""Scorer backends for the advisory judge lane.

Every scorer here implements `judgeguard.lanes.judge.Judge`. Which one you use
changes what appears in the score column and changes nothing about what gates.
"""

from ..lanes.judge import Judge, JudgeScore, OfflineStubJudge

__all__ = ["Judge", "JudgeScore", "OfflineStubJudge", "build"]

# Options that describe a real judge and mean nothing to the stub. Accepted and
# dropped so a caller can pass them uniformly without branching on the backend.
_MEANINGLESS_OFFLINE = ("allow_self_judge", "include_experimental")


def build(name: str, **kwargs) -> Judge:
    if name in ("offline", "stub", "none"):
        for key in _MEANINGLESS_OFFLINE:
            kwargs.pop(key, None)
        if kwargs:
            raise RuntimeError(
                f"the offline scorer takes no options, got {sorted(kwargs)}"
            )
        return OfflineStubJudge()
    if name == "foundry":
        from .foundry.scorer import FoundryScorer

        return FoundryScorer(**kwargs)
    raise RuntimeError(f"unknown scorer {name!r}; known: offline, foundry")
