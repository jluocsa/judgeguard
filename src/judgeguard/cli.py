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
from .report import markdown, summary
from .runner import run
from .scorers import build as build_scorer
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
        judge=build_scorer(args.scorer) if args.scorer else None,
        top_k=args.top_k,
        variant=args.variant,
    )


def cmd_doctor(args) -> int:
    try:
        corpus = Corpus.load(args.corpus)
    except FileNotFoundError:
        corpus = None
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


def cmd_coverage(args) -> int:
    from .scorers.foundry import coverage as cov

    width = max(len(s.evaluator) for s in cov.COVERAGE)
    print(f"{'evaluator':<{width}}  {'dimension':<20}  requires")
    for spec in cov.COVERAGE:
        print(f"{spec.evaluator:<{width}}  {spec.dimension:<20}  {spec.requires}")
    computable = len(cov.specs_for(cov.COMPUTABLE))
    model = len(cov.specs_for(cov.MODEL_CONFIG))
    project = len(cov.specs_for(cov.AZURE_AI_PROJECT))
    print(
        f"\n{computable} computable, "
        f"{model} need only a model config, "
        f"{project} {'needs' if project == 1 else 'need'} a project connection."
    )
    print("All of them land in the advisory lane. None of them can gate.")
    return EXIT_OK


def cmd_estimate(args) -> int:
    from .estimate import FREE, SERVICE, estimate_run

    corpus = Corpus.load(args.corpus)
    projection = estimate_run(
        corpus,
        backend=args.scorer or "foundry",
        project=args.with_project,
        repeat=args.repeat,
        price_in=args.price_in,
        price_out=args.price_out,
        variant=args.variant,
    )

    if not projection.items:
        print(f"{projection.backend}: no model calls, no cost.")
        return EXIT_OK

    width = max(len(i.dimension) for i in projection.items)
    print(
        f"{projection.cases} cases x {projection.repeat} repeat, "
        f"counting by {projection.method}\n"
    )
    print(f"{'dimension':<{width}}  {'calls':>6}  {'in':>10}  {'out':>8}  metered")
    for item in projection.items:
        print(
            f"{item.dimension:<{width}}  {item.calls:>6}  {item.input_tokens:>10,}  "
            f"{item.output_tokens:>8,}  {item.metered}"
        )
    print(
        f"\n{'TOTAL metered':<{width}}  {projection.calls:>6}  {projection.input_tokens:>10,}  "
        f"{projection.output_tokens:>8,}"
    )

    share = projection.overhead_share
    if share is not None:
        print(
            f"\n{share:.0%} of input tokens is evaluator rubric, not your data "
            f"({projection.overhead_tokens:,} of {projection.input_tokens:,}).\n"
            "Short cases pay mostly for the judge's instructions, so trimming the\n"
            "corpus saves far less than dropping a dimension you do not use."
        )

    cost = projection.cost
    if cost is None:
        print(
            "\nNo cost shown: pass --price-in and --price-out (rates per 1M tokens).\n"
            "judgeguard ships no price table - published rates change and a stale\n"
            "number baked into a tool is worse than none."
        )
    else:
        print(f"\nestimated cost  {cost}  at {projection.price_in}/{projection.price_out} per 1M")

    metered = projection.service_metered
    if metered:
        print(
            f"\nNot included: {', '.join(i.dimension for i in metered)} "
            "- billed per service call, not per token."
        )
    free = [i.dimension for i in projection.items if i.metered == FREE]
    if free:
        print(f"Free (computed locally, no model): {', '.join(free)}")
    return EXIT_OK


def cmd_label(args) -> int:
    from .labeling import SheetExists, emit

    result = _execute(args)
    try:
        written = emit(args.sheet, result, force=args.force)
    except SheetExists as exc:
        print(f"\u2717 {exc}", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED
    print(
        f"{written} rows written to {args.sheet}\n"
        "Fill the `label` column with acceptable or unacceptable, then run "
        "`judgeguard agree`."
    )
    return EXIT_OK


def cmd_agree(args) -> int:
    from .agreement import compare, render
    from .labeling import load

    result = _execute(args)
    labels = None
    if Path(args.sheet).exists():
        labels = load(args.sheet)
    else:
        print(f"note: no label sheet at {args.sheet}, comparing gate and judge only\n")
    print(render(compare(result, labels, threshold=args.judge_threshold)))
    return EXIT_OK


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
        sub.add_argument(
            "--scorer",
            default=None,
            choices=["offline", "foundry"],
            help="advisory judge backend; cannot affect the exit code",
        )

    doctor = subparsers.add_parser("doctor", help="preflight checks")
    doctor.add_argument("--corpus", default=DEFAULT_CORPUS)
    doctor.set_defaults(func=cmd_doctor)

    cov = subparsers.add_parser("coverage", help="which evaluator covers which dimension")
    cov.set_defaults(func=cmd_coverage)

    est = subparsers.add_parser("estimate", help="project tokens and cost for a judged run")
    est.add_argument("--corpus", default=DEFAULT_CORPUS)
    est.add_argument("--scorer", default="foundry", choices=["offline", "foundry"])
    est.add_argument("--variant", default=None, choices=["keyword", "natural", "prefixed"])
    est.add_argument("--repeat", type=int, default=1, help="consistency runs per case")
    est.add_argument("--price-in", type=float, default=None, help="per 1M input tokens")
    est.add_argument("--price-out", type=float, default=None, help="per 1M output tokens")
    est.add_argument(
        "--with-project",
        action="store_true",
        help="include evaluators needing a Foundry project connection",
    )
    est.set_defaults(func=cmd_estimate)

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

    label = subparsers.add_parser("label", help="emit a sheet for human labelling")
    common(label)
    label.add_argument("--provider", default="bm25")
    label.add_argument("--sheet", default=f"{DEFAULT_OUT}/labels.csv")
    label.add_argument("--force", action="store_true", help="overwrite existing labels")
    label.set_defaults(func=cmd_label)

    agree = subparsers.add_parser("agree", help="kappa between gate, judge and humans")
    common(agree)
    agree.add_argument("--provider", default="bm25")
    agree.add_argument("--sheet", default=f"{DEFAULT_OUT}/labels.csv")
    agree.add_argument("--judge-threshold", type=float, default=3.0)
    agree.set_defaults(func=cmd_agree)
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
