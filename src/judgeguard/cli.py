"""judgeguard command line.

`gate` is the entrypoint that matters: it is the one that returns an exit code,
and it derives that code from the deterministic lane alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import baseline as baseline_mod
from . import doctor as doctor_mod
from .adapters import build
from .candidates import TemplateCandidate
from .corpus import Corpus
from .gate import EXIT_OK, EXIT_PRECONDITION_FAILED, exit_code
from .lanes.judge import OfflineStubJudge
from .report import markdown, summary
from .runner import run
from .transcript import write_jsonl

DEFAULT_CORPUS = "corpus"
DEFAULT_OUT = ".judgeguard"


def _load(args) -> tuple[Corpus, object]:
    corpus = Corpus.load(args.corpus)
    return corpus, build(args.provider, corpus.documents)


def _execute(args, provider: str | None = None):
    corpus = Corpus.load(args.corpus)
    retriever = build(provider or args.provider, corpus.documents)
    return run(
        corpus,
        retriever,
        TemplateCandidate(),
        judge=OfflineStubJudge() if args.judge else None,
        top_k=args.top_k,
        variant=args.variant,
    )


def cmd_doctor(args) -> int:
    corpus = Corpus.load(args.corpus) if Path(args.corpus).exists() else None
    retrievers = (
        [build("bm25", corpus.documents), build("canned", corpus.documents)]
        if corpus
        else []
    )
    findings = doctor_mod.diagnose(args.corpus, retrievers)
    worst = EXIT_OK
    for finding in findings:
        mark = {"ok": "\u2713", "warn": "\u26a0", "fail": "\u2717"}[finding.status]
        print(f"{mark} {finding.name:<24} {finding.detail}")
        if finding.status == doctor_mod.FAILED:
            worst = EXIT_PRECONDITION_FAILED
    return worst


def cmd_run(args) -> int:
    result = _execute(args)
    print(summary(result))
    out = Path(args.out)
    write_jsonl(out / "transcripts.jsonl", [o.transcript for o in result.outcomes])
    (out / "report.md").write_text(markdown(result), encoding="utf-8")
    print(f"\ntranscripts: {out / 'transcripts.jsonl'}\nreport:      {out / 'report.md'}")
    return EXIT_OK


def cmd_gate(args) -> int:
    result = _execute(args)
    print(summary(result))
    out = Path(args.out)
    write_jsonl(out / "transcripts.jsonl", [o.transcript for o in result.outcomes])

    baseline_path = Path(args.baseline)
    if baseline_path.exists():
        deltas = baseline_mod.compare(baseline_mod.load(baseline_path), result)
        for delta in deltas:
            flag = "REGRESSED" if delta.regressed else "changed"
            print(f"    {flag} {delta.case_id} {delta.kind}: {delta.before} -> {delta.after}")
    if args.update_baseline:
        baseline_mod.save(baseline_path, result)
        print(f"    baseline written to {baseline_path}")

    code = exit_code(result.all_checks)
    print(f"\nexit {code}")
    return code


def cmd_bakeoff(args) -> int:
    results = [_execute(args, provider=p) for p in (args.a, args.b)]
    for result in results:
        print(f"\n--- {result.provider} ---")
        print(summary(result))
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.out, "bakeoff.md").write_text(
        "\n\n".join(markdown(r) for r in results), encoding="utf-8"
    )
    print(f"\ncomparison: {Path(args.out, 'bakeoff.md')}")
    # A comparison reports; it does not gate. Use `gate` for that.
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="judgeguard", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(sub):
        sub.add_argument("--corpus", default=DEFAULT_CORPUS)
        sub.add_argument("--out", default=DEFAULT_OUT)
        sub.add_argument("--top-k", type=int, default=5)
        sub.add_argument("--variant", default=None, choices=["keyword", "natural", "prefixed"])
        sub.add_argument("--judge", action="store_true", help="run the advisory judge lane")

    doctor = subparsers.add_parser("doctor", help="preflight checks")
    doctor.add_argument("--corpus", default=DEFAULT_CORPUS)
    doctor.set_defaults(func=cmd_doctor)

    runner = subparsers.add_parser("run", help="run one provider, write transcripts")
    common(runner)
    runner.add_argument("--provider", default="bm25")
    runner.set_defaults(func=cmd_run)

    gate = subparsers.add_parser("gate", help="CI entrypoint; deterministic lane sets exit code")
    common(gate)
    gate.add_argument("--provider", default="bm25")
    gate.add_argument("--baseline", default=f"{DEFAULT_OUT}/baseline.json")
    gate.add_argument("--update-baseline", action="store_true")
    gate.set_defaults(func=cmd_gate)

    bakeoff = subparsers.add_parser("bakeoff", help="compare two providers on one corpus")
    common(bakeoff)
    bakeoff.add_argument("--a", default="canned")
    bakeoff.add_argument("--b", default="bm25")
    bakeoff.set_defaults(func=cmd_bakeoff, provider="bm25")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"\u2717 {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
