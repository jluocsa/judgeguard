"""Which Foundry evaluator covers which judgeguard dimension, and what each needs.

Verified against azure-ai-evaluation by introspecting the installed package: the
constructor signatures and the prompty input declarations, not documentation.

The `requires` column is the useful one. It is the difference between "point the
judge somewhere else" being a configuration change and being a procurement
conversation, and it is not obvious from the evaluator list:

  computable        no model, no credential, no cost
  model_config      a bare model config - endpoint, key, deployment
  azure_ai_project  a Foundry project connection and a credential
"""

from __future__ import annotations

from dataclasses import dataclass

COMPUTABLE = "computable"
MODEL_CONFIG = "model_config"
AZURE_AI_PROJECT = "azure_ai_project"


@dataclass(frozen=True)
class EvaluatorSpec:
    evaluator: str
    dimension: str
    requires: str
    inputs: tuple[str, ...]


COVERAGE: tuple[EvaluatorSpec, ...] = (
    EvaluatorSpec(
        "GroundednessEvaluator",
        "groundedness",
        MODEL_CONFIG,
        ("query", "response", "context"),
    ),
    EvaluatorSpec(
        "RelevanceEvaluator", "relevance", MODEL_CONFIG, ("query", "response")
    ),
    EvaluatorSpec(
        "RetrievalEvaluator", "retrieval", MODEL_CONFIG, ("query", "context")
    ),
    EvaluatorSpec(
        "IntentResolutionEvaluator",
        "intent_resolution",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
    ),
    EvaluatorSpec(
        "ToolCallAccuracyEvaluator",
        "tool_call_accuracy",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
    ),
    EvaluatorSpec(
        "TaskAdherenceEvaluator",
        "task_adherence",
        MODEL_CONFIG,
        ("system_message", "query", "response", "tool_calls"),
    ),
    EvaluatorSpec(
        "ResponseCompletenessEvaluator",
        "task_completion",
        MODEL_CONFIG,
        ("response", "ground_truth"),
    ),
    EvaluatorSpec(
        "DocumentRetrievalEvaluator",
        "retrieval_ranking",
        COMPUTABLE,
        ("retrieval_ground_truth", "retrieved_documents"),
    ),
    EvaluatorSpec(
        "IndirectAttackEvaluator",
        "injection_exposure",
        AZURE_AI_PROJECT,
        ("query", "response"),
    ),
)

BY_DIMENSION = {spec.dimension: spec for spec in COVERAGE}
BY_EVALUATOR = {spec.evaluator: spec for spec in COVERAGE}

# Every input any evaluator above can consume. `rows.to_eval_row` emits this union
# once per case, and each evaluator is handed the subset it declares.
ALL_INPUTS: tuple[str, ...] = tuple(
    sorted({field for spec in COVERAGE for field in spec.inputs})
)


def specs_for(requires: str) -> tuple[EvaluatorSpec, ...]:
    return tuple(spec for spec in COVERAGE if spec.requires == requires)


def runnable_with(*, model_config: bool, project: bool) -> tuple[EvaluatorSpec, ...]:
    """What can actually run given the credentials on hand."""
    available = {COMPUTABLE}
    if model_config:
        available.add(MODEL_CONFIG)
    if project:
        available.add(AZURE_AI_PROJECT)
    return tuple(spec for spec in COVERAGE if spec.requires in available)
