"""What the command line promises must be true of the command line.

Two failures motivated this file. An error message told the operator to pass a flag
that was never registered, so the documented escape hatch did not exist. And the
report used glyphs a legacy console could not encode, so `gate` died while printing
and returned the precondition code - a run that had reached a verdict reported that
it never got that far.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from judgeguard.cli import build_parser
from judgeguard.gate import EXIT_PRECONDITION_FAILED
from judgeguard.independence import JudgeIndependenceError, assert_independent


def _advertised_flags(message: str) -> list[str]:
    return [word.strip(" ,.()") for word in message.split() if word.startswith("--")]


def test_every_flag_the_independence_error_advertises_is_accepted():
    """The override named in the error has to be the override the parser takes."""
    with pytest.raises(JudgeIndependenceError) as excinfo:
        assert_independent("gpt-4o@eastus", "gpt-4o@eastus")

    flags = _advertised_flags(str(excinfo.value))
    assert flags, "the independence error must name its override"
    for flag in flags:
        build_parser().parse_args(["gate", flag])


def test_allow_self_judge_reaches_the_run():
    assert build_parser().parse_args(["gate", "--allow-self-judge"]).allow_self_judge
    assert build_parser().parse_args(["gate"]).allow_self_judge is False


@pytest.mark.parametrize("command", ["run", "gate", "bakeoff", "label", "agree"])
def test_every_judged_command_offers_the_override(command):
    assert hasattr(build_parser().parse_args([command]), "allow_self_judge")


@pytest.mark.parametrize("command", ["run", "gate", "estimate"])
def test_the_experimental_opt_in_is_reachable_from_the_command_line(command):
    """A mapped evaluator nobody can select is a half-built feature."""
    assert build_parser().parse_args([command, "--with-experimental"]).with_experimental
    assert build_parser().parse_args([command]).with_experimental is False


def test_the_offline_stub_accepts_judge_options_and_ignores_them():
    from judgeguard.scorers import build

    judge = build("offline", allow_self_judge=True, include_experimental=True)
    assert judge.id == "offline-stub"

    with pytest.raises(RuntimeError, match="takes no options"):
        build("offline", not_a_real_option=1)


def test_a_legacy_console_encoding_cannot_change_the_exit_code(tmp_path):
    """cp1252 cannot encode a tick. That must cost a glyph, never the verdict."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "judgeguard.cli", "gate", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
        env=env,
    )
    assert "UnicodeEncodeError" not in result.stderr
    assert "Traceback" not in result.stderr
    assert "VERDICT" in result.stdout, "the run must still report a verdict"
    assert result.returncode != EXIT_PRECONDITION_FAILED, (
        "a run that reached a verdict must not report a failed precondition"
    )


def test_utf8_output_is_used_when_the_environment_states_no_preference(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    result = subprocess.run(
        [sys.executable, "-m", "judgeguard.cli", "gate", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert "VERDICT" in result.stdout
    assert "\u2713" in result.stdout or "\u2717" in result.stdout
