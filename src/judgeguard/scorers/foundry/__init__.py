"""Foundry scorer backend.

`coverage` and `rows` import no SDK, so the map and the row conversion stay
testable offline. Only `FoundryScorer` needs azure-ai-evaluation, and it is
imported lazily.
"""

from . import coverage, rows
from .coverage import (
    ALL_INPUTS,
    AZURE_AI_PROJECT,
    BY_DIMENSION,
    BY_EVALUATOR,
    COMPUTABLE,
    COVERAGE,
    MODEL_CONFIG,
    EvaluatorSpec,
    runnable_with,
    specs_for,
)

__all__ = [
    "ALL_INPUTS",
    "AZURE_AI_PROJECT",
    "BY_DIMENSION",
    "BY_EVALUATOR",
    "COMPUTABLE",
    "COVERAGE",
    "MODEL_CONFIG",
    "EvaluatorSpec",
    "FoundryScorer",
    "coverage",
    "rows",
    "runnable_with",
    "specs_for",
]


def __getattr__(name):
    if name == "FoundryScorer":
        from .scorer import FoundryScorer

        return FoundryScorer
    raise AttributeError(name)
