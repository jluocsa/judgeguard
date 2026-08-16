"""Invariant 2: a model may not evaluate itself without being marked."""

from __future__ import annotations

import pytest

from judgeguard.independence import JudgeIndependenceError, assert_independent


def test_distinct_deployments_are_independent():
    assert assert_independent("gpt-candidate", "gpt-judge") is False


def test_shared_deployment_refuses_to_start():
    with pytest.raises(JudgeIndependenceError) as excinfo:
        assert_independent("gpt-4o@eastus", "gpt-4o@eastus")
    message = str(excinfo.value)
    assert "cannot independently evaluate itself" in message
    assert "JUDGEGUARD_JUDGE_DEPLOYMENT" in message


def test_override_is_possible_but_marks_the_scores():
    assert assert_independent("same", "same", allow_self=True) is True
