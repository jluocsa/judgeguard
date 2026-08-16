"""Orchestration: corpus x retriever x candidate -> transcripts -> two lanes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contract import Candidate, Retriever
from .corpus import Case, Corpus
from .lanes.checks import DEFAULT_CHECKS
from .lanes.deterministic import (
    FAIL,
    PASS,
    UNGRADABLE,
    Check,
    CheckResult,
    run_checks,
)
from .lanes.judge import Judge, JudgeScore
from .transcript import ToolCall, Transcript, min_evidence_level


@dataclass
class CaseOutcome:
    case: Case
    transcript: Transcript
    checks: list[CheckResult] = field(default_factory=list)
    scores: list[JudgeScore] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(c.status == FAIL for c in self.checks):
            return FAIL
        if all(c.status == UNGRADABLE for c in self.checks):
            return UNGRADABLE
        return PASS


@dataclass
class RunResult:
    provider: str
    candidate_id: str
    evidence_level: str
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def all_checks(self) -> list[CheckResult]:
        return [c for outcome in self.outcomes for c in outcome.checks]

    @property
    def failed(self) -> list[CaseOutcome]:
        return [o for o in self.outcomes if o.verdict == FAIL]

    @property
    def mean_score(self) -> float | None:
        scores = [s.score for o in self.outcomes for s in o.scores]
        return round(sum(scores) / len(scores), 2) if scores else None


def run(
    corpus: Corpus,
    retriever: Retriever,
    candidate: Candidate,
    *,
    judge: Judge | None = None,
    checks: list[Check] | None = None,
    top_k: int = 5,
    variant: str | None = None,
) -> RunResult:
    checks = checks if checks is not None else DEFAULT_CHECKS
    outcomes: list[CaseOutcome] = []

    for case in corpus.filter(variant=variant):
        result = retriever.retrieve(case.query, identity=case.identity, top_k=top_k)
        call = ToolCall(
            name="retrieve",
            arguments={
                "query": case.query,
                "principal": case.identity.principal,
                "top_k": top_k,
            },
            result=[p.id for p in result.passages],
            error=result.error,
        )
        transcript = Transcript(
            case_id=case.id,
            query=case.query,
            principal=case.identity.principal,
            provider=retriever.name,
            evidence_level=retriever.evidence_level,
            tool_calls=[call],
            passages=[
                {
                    "id": p.id,
                    "source": p.source,
                    "score": p.score,
                    "acl": sorted(p.acl),
                    "text": p.text,
                }
                for p in result.passages
            ],
            answer=candidate.answer(case.query, result.passages),
            latency_ms=round(result.latency_ms, 2),
            meta={"variant": case.variant, "candidate": candidate.id},
        )
        outcome = CaseOutcome(
            case=case,
            transcript=transcript,
            checks=run_checks(checks, transcript, case),
            scores=judge.score(transcript, case) if judge else [],
        )
        outcomes.append(outcome)

    return RunResult(
        provider=retriever.name,
        candidate_id=candidate.id,
        evidence_level=min_evidence_level(
            [o.transcript.evidence_level for o in outcomes] or [retriever.evidence_level]
        ),
        outcomes=outcomes,
    )
