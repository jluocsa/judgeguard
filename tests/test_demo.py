"""The demo has to be true on the day, so it checks itself.

Every step in `examples/demo.py` declares an expected exit code and the strings that
have to appear. This test runs the whole thing in --check mode, which means a change
that alters a verdict, a count or an evidence level fails here rather than in front of
an audience.

It is slow by the standards of the rest of the suite - it runs the demo end to end -
and that is the trade being made deliberately.

The demo's own preflight step runs pytest, so without a guard this test and that step
would call each other forever. Two things prevent it: the step deselects this file,
and the demo exports JUDGEGUARD_DEMO so anything it launches can tell.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo.py"

pytestmark = pytest.mark.skipif(
    os.environ.get("JUDGEGUARD_DEMO") == "1",
    reason="already running inside the demo; recursing would not terminate",
)


def run_demo(*arguments: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DEMO), "--no-color", "--python", sys.executable, *arguments],
        cwd=DEMO.parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def demo_run():
    if not DEMO.exists():
        pytest.skip("the demo driver is not present")
    return run_demo("--check")


def test_every_demo_step_matches_its_claim(demo_run):
    assert demo_run.returncode == 0, (
        "a demo step no longer produces what the runbook quotes:\n"
        + demo_run.stdout[-3000:]
    )
    assert "steps verified. Safe to demo." in demo_run.stdout


def test_the_driver_reports_a_broken_step_rather_than_hiding_it(tmp_path):
    """The guarantee is only worth having if a mismatch actually fails."""
    source = DEMO.read_text(encoding="utf-8").replace(
        'expect=("rag-search", "knowledge-base", "L0"),',
        'expect=("a string no run will ever print",),',
        1,
    )
    broken = tmp_path / "demo.py"
    broken.write_text(source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(broken), "--check", "--no-color",
         "--segment", "3", "--python", sys.executable],
        cwd=DEMO.parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    assert result.returncode == 1
    assert "did not match expectations" in result.stdout


def test_a_single_segment_can_be_rehearsed():
    result = run_demo("--check", "--segment", "3")
    assert result.returncode == 0
    assert "Option 1 versus Option 2" in result.stdout
    assert "SEGMENT 1" not in result.stdout


def test_an_unknown_segment_is_refused():
    result = run_demo("--segment", "9", timeout=120)
    assert result.returncode != 0
    assert "no segment 9" in result.stdout + result.stderr
