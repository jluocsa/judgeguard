"""Transcripts round-trip losslessly, and baselines detect verdict regressions."""

from __future__ import annotations

import json

from judgeguard.adapters import Bm25Retriever
from judgeguard.baseline import compare, save, snapshot
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.runner import run
from judgeguard.transcript import Transcript, read_jsonl, write_jsonl


def _run():
    corpus = Corpus.load("corpus")
    return run(corpus, Bm25Retriever(corpus.documents), TemplateCandidate())


def test_transcript_roundtrips_through_disk(tmp_path):
    result = _run()
    path = tmp_path / "transcripts.jsonl"
    write_jsonl(path, [o.transcript for o in result.outcomes])

    restored = list(read_jsonl(path))
    assert len(restored) == len(result.outcomes)
    for before, after in zip(result.outcomes, restored):
        assert isinstance(after, Transcript)
        assert before.transcript.to_dict() == after.to_dict()


def test_transcript_carries_the_whole_row():
    result = _run()
    transcript = result.outcomes[0].transcript
    row = transcript.to_dict()
    for field in ("query", "tool_calls", "passages", "answer", "evidence_level"):
        assert field in row, f"a gate-3 row must carry {field}"
    assert row["tool_calls"][0]["arguments"]["query"] == transcript.query
    assert json.dumps(row)  # must be serialisable without custom encoders


def test_baseline_flags_a_verdict_regression(tmp_path):
    result = _run()
    path = tmp_path / "baseline.json"
    save(path, result)

    clean = snapshot(result)
    for case in clean["cases"].values():
        case["verdict"] = "pass"

    deltas = compare(clean, result)
    regressions = [d for d in deltas if d.regressed]
    assert regressions, "a pass turning into a fail must be reported as a regression"
    assert all(d.kind == "verdict" for d in regressions)
