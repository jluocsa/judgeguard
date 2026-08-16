"""Grade transcripts an external agent produced.

judgeguard's runner drives a retriever and a candidate, which is the right shape for
comparing retrieval backends and the wrong shape for an agent that owns its own tool
loop. A harness that decides when to retrieve, retries, reformulates and declines
cannot be expressed as `retrieve() then answer()` without flattening the behaviour
the evaluation exists to inspect.

So the agent runs itself and writes transcripts, and judgeguard reads them. The two
lanes, the evidence levels, the baselines and the agreement statistics then work
unchanged, because every one of them already reads from the transcript rather than
from the runner.

The evidence level comes from the emitting harness rather than from judgeguard, which
is the one thing here that is taken on trust. A harness claiming L2 for a run whose
tools were mocked gets checks graded against evidence that does not exist - so
`declared_evidence` is reported in the summary, where a reader can challenge it,
rather than being quietly consumed.
"""

from __future__ import annotations

from pathlib import Path

from .corpus import Case, Corpus
from .lanes.checks import DEFAULT_CHECKS
from .lanes.deterministic import Check, run_checks
from .lanes.judge import Judge
from .runner import CaseOutcome, RunResult
from .transcript import Transcript, min_evidence_level, read_jsonl


class TranscriptMismatch(ValueError):
    """A transcript names a case the corpus does not define, or the reverse."""


def load(path: str | Path) -> list[Transcript]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no transcripts at {path}")
    transcripts = list(read_jsonl(path))
    if not transcripts:
        raise TranscriptMismatch(f"{path} contains no transcripts")
    return transcripts


def pair(
    corpus: Corpus, transcripts: list[Transcript], *, allow_partial: bool = False
) -> list[tuple[Case, Transcript]]:
    """Match transcripts to the cases they claim to answer.

    Unknown case ids always fail: a transcript nobody can trace to a declared case is
    not evidence about anything.

    Missing cases fail unless explicitly allowed. Grading nine cases out of eleven and
    reporting the verdict as though the suite had run is how a partial run gets read
    as a complete one - the same trap as a scoped run being mistaken for full evidence.
    """
    by_id = {case.id: case for case in corpus.cases}
    seen = [t.case_id for t in transcripts]

    unknown = sorted({case_id for case_id in seen if case_id not in by_id})
    if unknown:
        raise TranscriptMismatch(
            f"transcripts name {len(unknown)} case(s) absent from the corpus: "
            f"{unknown[:5]}{' ...' if len(unknown) > 5 else ''}"
        )

    missing = sorted(set(by_id) - set(seen))
    if missing and not allow_partial:
        raise TranscriptMismatch(
            f"{len(missing)} case(s) have no transcript: "
            f"{missing[:5]}{' ...' if len(missing) > 5 else ''}\n"
            "  A partial run reported as a full one is not evidence about the suite. "
            "Pass --allow-partial to grade the subset, and read the result as a subset."
        )
    return [(by_id[t.case_id], t) for t in transcripts]


def grade(
    corpus: Corpus,
    transcripts: list[Transcript],
    *,
    judge: Judge | None = None,
    checks: list[Check] | None = None,
    allow_partial: bool = False,
) -> RunResult:
    """Run both lanes over transcripts judgeguard did not produce."""
    checks = checks if checks is not None else DEFAULT_CHECKS
    outcomes = [
        CaseOutcome(
            case=case,
            transcript=transcript,
            checks=run_checks(checks, transcript, case),
            scores=judge.score(transcript, case) if judge else [],
        )
        for case, transcript in pair(corpus, transcripts, allow_partial=allow_partial)
    ]

    providers = {o.transcript.provider for o in outcomes if o.transcript.provider}
    candidates = {
        o.transcript.meta.get("candidate")
        for o in outcomes
        if o.transcript.meta.get("candidate")
    }
    return RunResult(
        provider=_one_of(providers, "mixed"),
        candidate_id=_one_of(candidates, "mixed"),
        evidence_level=min_evidence_level(
            [o.transcript.evidence_level for o in outcomes]
        ),
        outcomes=outcomes,
    )


def _one_of(values: set, fallback: str) -> str:
    """A run that mixes providers is reported as mixed rather than as the first one."""
    if not values:
        return "unknown"
    return values.pop() if len(values) == 1 else fallback
