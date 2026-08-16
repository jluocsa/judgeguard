"""Preflight. Everything here is cheap and everything here has burned someone."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .contract import Retriever
from .corpus import Corpus
from .independence import JudgeIndependenceError, assert_independent

OK = "ok"
WARN = "warn"
FAILED = "fail"


@dataclass(frozen=True)
class Finding:
    name: str
    status: str
    detail: str


def diagnose(corpus_root: str | Path, retrievers: list[Retriever]) -> list[Finding]:
    findings = [
        Finding(
            "python",
            OK if sys.version_info >= (3, 11) else FAILED,
            f"{sys.version_info.major}.{sys.version_info.minor}, need >= 3.11",
        )
    ]

    try:
        corpus = Corpus.load(corpus_root)
        variants = sorted({c.variant for c in corpus.cases})
        findings.append(
            Finding(
                "corpus",
                OK,
                f"{len(corpus.documents)} documents, {len(corpus.cases)} cases, "
                f"variants: {', '.join(variants)}",
            )
        )
    except Exception as exc:
        findings.append(Finding("corpus", FAILED, f"{type(exc).__name__}: {exc}"))
        return findings

    for retriever in retrievers:
        conformant = isinstance(retriever, Retriever)
        findings.append(
            Finding(
                f"adapter:{retriever.name}",
                OK if conformant else FAILED,
                f"declares {retriever.evidence_level}"
                if conformant
                else "does not satisfy the Retriever contract",
            )
        )

    candidate = os.environ.get("JUDGEGUARD_CANDIDATE_DEPLOYMENT")
    judge = os.environ.get("JUDGEGUARD_JUDGE_DEPLOYMENT")
    if not candidate or not judge:
        findings.append(
            Finding(
                "judge-independence",
                WARN,
                "no deployments configured - offline stub judge will be used",
            )
        )
    else:
        try:
            assert_independent(candidate, judge)
            findings.append(
                Finding("judge-independence", OK, f"judge {judge} != candidate {candidate}")
            )
        except JudgeIndependenceError as exc:
            findings.append(Finding("judge-independence", FAILED, str(exc).splitlines()[0]))

    return findings
