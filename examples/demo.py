"""Run the demo, with a live status display, and check its own claims as it goes.

A demo that prints whatever happens is a demo that can quietly show the wrong thing
in front of an audience. Every step here declares what it expects - an exit code and
the strings that have to appear - so the display shows a verdict per step rather than
just output. If the environment differs, the presenter finds out on the spot instead
of narrating a number that is no longer true.

    python demo.py                 # the whole session
    python demo.py --pause         # wait for Enter between segments
    python demo.py --segment 2     # rehearse one segment
    python demo.py --check         # verify every claim, no pauses, minimal output

Zero dependencies, like the rest of the deterministic lane.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

PASS, FAIL, RUNNING = "pass", "fail", "running"

GLYPH = {PASS: "\u2713", FAIL: "\u2717", RUNNING: "\u25cf"}
FILLED, EMPTY = "\u25ae", "\u25af"


class Style:
    """ANSI, switched off when the output is not a terminal or NO_COLOR is set."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text):
        return self._wrap("1", text)

    def dim(self, text):
        return self._wrap("2", text)

    def green(self, text):
        return self._wrap("32", text)

    def red(self, text):
        return self._wrap("31", text)

    def cyan(self, text):
        return self._wrap("36", text)

    def yellow(self, text):
        return self._wrap("33", text)


@dataclass
class Step:
    segment: int
    title: str
    command: list[str]
    cwd: Path = ROOT
    expect_exit: int | None = 0
    expect: tuple[str, ...] = ()
    beat: str = ""
    show: int = 14  # lines of output to display; the rest is elided
    status: str = RUNNING
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)


SEGMENTS = {
    0: "Preflight",
    1: "Why two lanes",
    2: "Foundry eval, end to end",
    3: "Option 1 versus Option 2",
}


def build_steps(python: str) -> list[Step]:
    jg = [python, "-m", "judgeguard.cli"]
    return [
        Step(
            segment=0,
            title="The suite is green before anything is claimed",
            # No -q: pyproject already sets addopts = "-q", and a second one
            # suppresses the summary line this step needs to read.
            # test_demo.py is deselected because it runs this very script; without
            # that the preflight step recurses into itself.
            command=[python, "-m", "pytest", "--deselect", "tests/test_demo.py"],
            expect=("passed",),
            beat="A demo that opens with a red suite argues against itself.",
            show=3,
        ),
        Step(
            segment=1,
            title="Grade a completed Foundry run from another harness",
            command=[python, "ingest.py"],
            cwd=HERE / "csa-workbench",
            expect=(
                "deterministic gate: 11/11 passed",
                "kappa is not reportable",
                "ACME-4-boundary",
            ),
            beat=(
                "Real data, 8 evaluators the pod also selected. Every judge/oracle\n"
                "    disagreement is the agent behaving correctly - a refusal it was\n"
                "    right to make, a clarification it was right to ask."
            ),
            # Shown whole: the disagreement list at the end is the point of the
            # segment, and eliding it would hide the finding to save eight lines.
            show=60,
        ),
        Step(
            segment=2,
            title="The gate, with no Foundry and no credentials",
            command=jg + ["gate", "--corpus", "corpus/qa-pod", "--out", ".judgeguard/demo"],
            expect_exit=1,
            expect=("EVIDENCE  L1", "QA-06", "exit 1"),
            beat=(
                "Exit 1, CI-ready today. L1 is printed so a green run cannot be\n"
                "    mistaken for more than it is."
            ),
        ),
        Step(
            segment=2,
            title="The agent runs itself and writes transcripts",
            command=[python, "emit_transcripts.py"],
            cwd=HERE / "agent-transcripts",
            expect=("9 transcripts", "declared evidence: L2"),
            beat="Ten fields per case, five required. The harness integration point.",
            show=4,
        ),
        Step(
            segment=2,
            title="Grade the agent at L2 - the contrast that matters",
            command=jg
            + [
                "grade",
                "--corpus", "../../corpus/qa-pod",
                "--transcripts", ".transcripts/run.jsonl",
                "--out", ".judgeguard",
            ],
            cwd=HERE / "agent-transcripts",
            expect_exit=1,
            expect=("EVIDENCE  L2", "1/72 checks", "QA-08"),
            beat=(
                "Same corpus, same checks, same verdict count - different defects.\n"
                "    QA-06 now passes because the agent declined to retrieve.\n"
                "    QA-08 now fails: it surfaced only the current engagement letter,\n"
                "    not the superseded version it contradicts. L1 could not see that."
            ),
        ),
        Step(
            segment=2,
            title="Emit the same run as a Foundry dataset",
            command=jg
            + [
                "emit-dataset",
                "--corpus", "../../corpus/qa-pod",
                "--transcripts", ".transcripts/run.jsonl",
                "--out", ".foundry",
            ],
            cwd=HERE / "agent-transcripts",
            expect=("13 evaluators requested", "L2 evidence"),
            beat="Thirteen evaluators - the pod's exact list. Eleven need no reference.",
            show=8,
        ),
        Step(
            segment=2,
            title="What would be sent, and which shape each evaluator reads",
            command=[python, "foundry_eval.py", "--dry-run",
                     "--dataset", "../agent-transcripts/.foundry/dataset.jsonl"],
            cwd=HERE / "qa-foundry-eval",
            expect=("query_messages", "builtin.groundedness", "gate verdict"),
            beat=(
                "The trap worth the segment: RAG evaluators read strings, agent\n"
                "    evaluators read a conversation. Send a bare string and it does not\n"
                "    fail - it degrades, downward, and nobody investigates."
            ),
            show=20,
        ),
        Step(
            segment=3,
            title="Both retrieval options, same corpus, same assertions",
            command=jg
            + [
                "bakeoff",
                "--corpus", "corpus/qa-pod",
                "--a", "rag-search-local",
                "--b", "knowledge-base-local",
                "--out", ".judgeguard/demo",
            ],
            expect=("rag-search", "knowledge-base", "L0"),
            beat=(
                "Identical behaviour, and both honestly report L0 - neither backend is\n"
                "    deployed, so authorization reports ungradable rather than a tick."
            ),
            show=14,
        ),
        Step(
            segment=3,
            title="The conformance suite that decides between them",
            command=[python, "-m", "pytest", "tests/conformance"],
            expect=("passed",),
            beat=(
                "An argument is a claim; a filter is a constraint. The suite asserts\n"
                "    both reach the same outcome AND records that the mechanisms differ."
            ),
            show=3,
        ),
    ]


def use_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def width() -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, 96)


def bar(done: int, total: int, size: int = 18) -> str:
    filled = round(size * done / total) if total else 0
    return FILLED * filled + EMPTY * (size - filled)


def shown_command(step: Step) -> str:
    """A command a viewer can read: the interpreter path is noise on a projector."""
    parts = [str(c) for c in step.command]
    if parts and parts[0].endswith(("python.exe", "python", "python3")):
        parts[0] = "python"
    if parts[:3] == ["python", "-m", "judgeguard.cli"]:
        parts = ["judgeguard"] + parts[3:]
    rendered = " ".join(parts)
    room = width() - 6
    return rendered if len(rendered) <= room else rendered[: room - 3] + "..."


CLEAR_LINE = "\033[2K"


def run_step(step: Step, style: Style, quiet: bool) -> Step:
    started = time.perf_counter()
    # Marks the subprocess as running under the demo. The test that exercises this
    # driver skips when it sees it, which is the second guard against the preflight
    # step recursing into the suite that launches it.
    environment = {**os.environ, "JUDGEGUARD_DEMO": "1"}
    completed = subprocess.run(
        step.command,
        cwd=step.cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    step.seconds = time.perf_counter() - started
    output = (completed.stdout or "") + (completed.stderr or "")

    if step.expect_exit is not None and completed.returncode != step.expect_exit:
        step.problems.append(
            f"exit {completed.returncode}, expected {step.expect_exit}"
        )
    for needle in step.expect:
        if needle not in output:
            step.problems.append(f"missing from output: {needle!r}")
    step.status = FAIL if step.problems else PASS

    if not quiet:
        lines = [l for l in output.splitlines() if l.strip()]
        for line in lines[: step.show]:
            # Not truncated: the detail at the end of a verdict line is usually the
            # point of the step, and a terminal wraps better than a demo loses it.
            print("    " + style.dim(line))
        if len(lines) > step.show:
            print("    " + style.dim(f"... {len(lines) - step.show} more lines"))
    return step


def main() -> int:
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pause", action="store_true", help="wait between segments")
    parser.add_argument("--segment", type=int, default=None, help="run just one")
    parser.add_argument("--check", action="store_true",
                        help="verify every claim, minimal output, no pauses")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    arguments = parser.parse_args()

    style = Style(
        not arguments.no_color
        and sys.stdout.isatty()
        and not os.environ.get("NO_COLOR")
    )
    steps = build_steps(arguments.python)
    if arguments.segment is not None:
        steps = [s for s in steps if s.segment == arguments.segment]
        if not steps:
            raise SystemExit(f"no segment {arguments.segment}; known: {sorted(SEGMENTS)}")

    line = "\u2550" * width()
    print(style.cyan(line))
    print(style.bold(" judgeguard \u00b7 Foundry evaluation for the IDA harness"))
    print(style.dim(f" {len(steps)} steps \u00b7 runs offline \u00b7 every claim is checked"))
    print(style.cyan(line))

    seen_segment = None
    for index, step in enumerate(steps, start=1):
        if step.segment != seen_segment:
            seen_segment = step.segment
            if arguments.pause and index > 1:
                input(style.dim("\n  [Enter] for the next segment "))
            label = f" SEGMENT {step.segment} \u00b7 {SEGMENTS[step.segment]} "
            print("\n" + style.bold(style.cyan("\u250c" + label + "\u2500" * max(0, width() - len(label) - 1))))

        print(f"\n  {style.bold(f'step {index}/{len(steps)}')}  {step.title}")
        print("  " + style.dim("$ " + shown_command(step)))
        if style.enabled:
            print("  " + style.yellow(f"{GLYPH[RUNNING]} running"), end="\r", flush=True)

        run_step(step, style, quiet=arguments.check)

        if style.enabled:
            print(CLEAR_LINE, end="")
        mark = style.green(GLYPH[PASS]) if step.status == PASS else style.red(GLYPH[FAIL])
        done = sum(1 for s in steps[:index] if s.status != RUNNING)
        print(
            f"  {mark} {step.status:<7} {step.seconds:5.1f}s   "
            + style.dim(f"{bar(done, len(steps))} {done}/{len(steps)}")
        )
        for problem in step.problems:
            print("    " + style.red(f"{GLYPH[FAIL]} {problem}"))
        if step.beat and not arguments.check:
            print("    " + style.cyan("\u2192 " + step.beat))

    failed = [s for s in steps if s.status == FAIL]
    print("\n" + style.cyan(line))
    if failed:
        print(style.red(f" {len(failed)} of {len(steps)} steps did not match expectations"))
        for step in failed:
            print(style.red(f"   {GLYPH[FAIL]} step: {step.title}"))
            for problem in step.problems:
                print(style.dim(f"       {problem}"))
        print(style.dim(" Fix these before demoing. The runbook quotes this output."))
    else:
        print(style.green(f" {len(steps)}/{len(steps)} steps verified. Safe to demo."))
    print(style.cyan(line))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
