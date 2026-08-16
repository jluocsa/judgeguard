"""Invariant 1: the judge lane cannot influence the process exit code.

This is the product. If it ever fails, judgeguard is just another eval runner.
"""

from __future__ import annotations

import pytest

from judgeguard.corpus import Corpus
from judgeguard.gate import EXIT_OK, EXIT_VERDICT_FAILED, exit_code
from judgeguard.lanes.deterministic import FAIL, PASS, CheckResult
from judgeguard.lanes.judge import JudgeScore


def test_exit_code_rejects_judge_scores():
    score = JudgeScore("groundedness", 0.0, "terrible", "judge-a")
    with pytest.raises(TypeError, match="only deterministic CheckResult"):
        exit_code([score])


def test_worst_possible_judge_score_does_not_gate(tmp_path):
    passing = [CheckResult("citation_resolvable", PASS)]
    assert exit_code(passing) == EXIT_OK

    # Nothing about the judge is even reachable from here: exit_code has one
    # parameter and it is typed to the deterministic lane.
    assert exit_code(passing + [CheckResult("leakage", PASS)]) == EXIT_OK
    assert exit_code(passing + [CheckResult("leakage", FAIL)]) == EXIT_VERDICT_FAILED


def test_judge_module_exports_nothing_gate_accepts():
    from judgeguard.lanes import judge

    exported = [getattr(judge, n) for n in dir(judge) if not n.startswith("_")]
    assert not any(
        isinstance(obj, type) and issubclass(obj, CheckResult)
        for obj in exported
        if isinstance(obj, type)
    )


def test_run_exit_code_is_unchanged_by_judge_presence():
    from judgeguard.adapters import Bm25Retriever
    from judgeguard.candidates import TemplateCandidate
    from judgeguard.lanes.judge import OfflineStubJudge
    from judgeguard.runner import run

    corpus = Corpus.load("corpus")
    without = run(corpus, Bm25Retriever(corpus.documents), TemplateCandidate())
    with_judge = run(
        corpus,
        Bm25Retriever(corpus.documents),
        TemplateCandidate(),
        judge=OfflineStubJudge(),
    )
    assert exit_code(without.all_checks) == exit_code(with_judge.all_checks)
    assert with_judge.mean_score is not None
