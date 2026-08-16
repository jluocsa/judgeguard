"""The Foundry scorer: a Judge backed by azure-ai-evaluation.

It is a `Judge`, which means everything it produces lands in the advisory lane and
cannot reach an exit code. Swapping the scoring platform does not change what gates
the build - that is the whole point of the split.

  pip install "judgeguard[foundry]"
"""

from __future__ import annotations

import os
from typing import Any

from ...corpus import Case
from ...independence import assert_independent
from ...transcript import Transcript
from . import coverage, rows


class FoundryScorer:
    """Runs Foundry evaluators over judgeguard transcripts."""

    def __init__(
        self,
        *,
        model_config: dict[str, Any] | None = None,
        azure_ai_project: str | None = None,
        credential=None,
        dimensions: tuple[str, ...] | None = None,
        candidate_deployment: str | None = None,
        allow_self_judge: bool = False,
        include_experimental: bool = False,
    ):
        try:
            import azure.ai.evaluation as evaluation
        except ImportError as exc:
            raise ImportError(
                'FoundryScorer needs the foundry extra: pip install "judgeguard[foundry]"'
            ) from exc

        self._model_config = model_config or _model_config_from_env()
        self._project = azure_ai_project
        self._credential = credential

        judge_deployment = (self._model_config or {}).get("azure_deployment", "unknown")
        candidate = candidate_deployment or os.environ.get(
            "JUDGEGUARD_CANDIDATE_DEPLOYMENT", ""
        )
        self.self_judged = (
            assert_independent(candidate, judge_deployment, allow_self=allow_self_judge)
            if candidate
            else False
        )
        self.id = f"foundry:{judge_deployment}"

        available = coverage.runnable_with(
            model_config=bool(self._model_config),
            project=bool(self._project),
            include_experimental=include_experimental,
        )
        if dimensions:
            available = tuple(s for s in available if s.dimension in dimensions)
        self.specs = available
        # Dimensions this run could not grade, and why. Accumulated across cases so
        # a gap in the corpus is visible after the run rather than only per case.
        self.skipped: dict[str, str] = {}
        self._evaluators = {
            spec.dimension: self._build(evaluation, spec) for spec in available
        }

    def _build(self, evaluation, spec: coverage.EvaluatorSpec):
        cls = self._resolve(evaluation, spec)
        if spec.requires == coverage.COMPUTABLE:
            return cls()
        if spec.requires == coverage.AZURE_AI_PROJECT:
            return cls(credential=self._credential, azure_ai_project=self._project)
        return cls(self._model_config)

    @staticmethod
    def _resolve(evaluation, spec: coverage.EvaluatorSpec):
        """Private evaluators are not all exported, so fall back to their module.

        The failure is raised with the version that lacks the class, because an
        experimental class disappearing on upgrade is the expected way this breaks.
        """
        cls = getattr(evaluation, spec.evaluator, None)
        if cls is not None:
            return cls
        if spec.module:
            import importlib

            module = importlib.import_module(spec.module)
            cls = getattr(module, spec.evaluator, None)
            if cls is not None:
                return cls
        raise AttributeError(
            f"{spec.evaluator} is not in the installed azure-ai-evaluation "
            f"({_installed_version()}); it backs the {spec.dimension} dimension"
        )

    def score(self, transcript: Transcript, case: Case):
        row = rows.to_eval_row(transcript, case)
        results: dict[str, Any] = {}
        for spec in self.specs:
            reason = rows.ungradable_reason(spec, row)
            if reason:
                # Not scored rather than scored zero: an absent reference is a gap
                # in the corpus, and reporting it as a low score would blame the
                # candidate for it.
                self.skipped[spec.dimension] = reason
                continue
            evaluator = self._evaluators[spec.dimension]
            try:
                results[spec.dimension] = evaluator(**rows.inputs_for(spec, row))
            except Exception as exc:  # a failed evaluator is reported, never hidden
                results[spec.dimension] = {
                    "score": 0.0,
                    "reason": f"{spec.evaluator} failed: {type(exc).__name__}: {exc}",
                }
        return rows.from_eval_results(
            results, row, self.id, self_judged=self.self_judged
        )


def _installed_version() -> str:
    try:
        from azure.ai.evaluation import _version

        return _version.VERSION
    except Exception:
        return "unknown version"


def _model_config_from_env() -> dict[str, Any] | None:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("JUDGEGUARD_JUDGE_DEPLOYMENT")
    if not endpoint or not deployment:
        return None
    config = {
        "azure_endpoint": endpoint,
        "azure_deployment": deployment,
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    if key:
        config["api_key"] = key
    return config
