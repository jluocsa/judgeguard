"""Which Foundry evaluator covers which judgeguard dimension, and what each needs.

Verified against azure-ai-evaluation by introspecting the installed package: the
constructor signatures, the declared singleton inputs and the prompty input
declarations, not documentation.

The `requires` column is the useful one. It is the difference between "point the
judge somewhere else" being a configuration change and being a procurement
conversation, and it is not obvious from the evaluator list:

  computable        no model, no credential, no cost
  model_config      a bare model config - endpoint, key, deployment
  azure_ai_project  a Foundry project connection and a credential

The `stability` column is the one that decides whether you can build on it. Four of
the tool evaluators are shipped only as underscore-prefixed classes marked
experimental by the SDK itself, and two of those four are not exported from the
package namespace at all. They are listed here because pretending they do not exist
is not useful, and they are opt-in because a private class can be renamed in a patch
release.

There is no TaskCompletionEvaluator in azure-ai-evaluation 1.18.3. Task completion
and response completeness are treated as one evaluator by the SDK, so a plan that
names both is naming one shipped evaluator and one gap.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPUTABLE = "computable"
MODEL_CONFIG = "model_config"
AZURE_AI_PROJECT = "azure_ai_project"

STABLE = "stable"
EXPERIMENTAL = "experimental"

_TOOL_EVALUATORS = "azure.ai.evaluation._evaluators"


@dataclass(frozen=True)
class EvaluatorSpec:
    evaluator: str
    dimension: str
    requires: str
    inputs: tuple[str, ...]
    # Inputs that must be present *and* non-empty for the score to mean anything.
    # An evaluator handed an empty reference still returns a number; that number
    # describes the empty reference, not the response.
    requires_nonempty: tuple[str, ...] = ()
    stability: str = STABLE
    # Set when the class is not exported from the package namespace and has to be
    # imported from its own module.
    module: str | None = None


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
        ("query", "response", "tool_definitions"),
    ),
    EvaluatorSpec(
        "ResponseCompletenessEvaluator",
        "response_completeness",
        MODEL_CONFIG,
        ("response", "ground_truth"),
        requires_nonempty=("ground_truth",),
    ),
    EvaluatorSpec(
        "DocumentRetrievalEvaluator",
        "retrieval_ranking",
        COMPUTABLE,
        ("retrieval_ground_truth", "retrieved_documents"),
        requires_nonempty=("retrieval_ground_truth",),
    ),
    EvaluatorSpec(
        "IndirectAttackEvaluator",
        "injection_exposure",
        AZURE_AI_PROJECT,
        ("query", "response"),
    ),
    # --- experimental, private in the SDK; opt in with include_experimental -----
    EvaluatorSpec(
        "_ToolSelectionEvaluator",
        "tool_selection",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_selection._tool_selection",
    ),
    EvaluatorSpec(
        "_ToolInputAccuracyEvaluator",
        "tool_input_accuracy",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_input_accuracy._tool_input_accuracy",
    ),
    EvaluatorSpec(
        "_ToolOutputUtilizationEvaluator",
        "tool_output_utilization",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_output_utilization._tool_output_utilization",
    ),
    EvaluatorSpec(
        "_ToolCallSuccessEvaluator",
        "tool_call_success",
        MODEL_CONFIG,
        ("response", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_call_success._tool_call_success",
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


def stable() -> tuple[EvaluatorSpec, ...]:
    return tuple(spec for spec in COVERAGE if spec.stability == STABLE)


def experimental() -> tuple[EvaluatorSpec, ...]:
    return tuple(spec for spec in COVERAGE if spec.stability == EXPERIMENTAL)


def runnable_with(
    *, model_config: bool, project: bool, include_experimental: bool = False
) -> tuple[EvaluatorSpec, ...]:
    """What can actually run given the credentials on hand.

    Experimental evaluators are excluded unless asked for. They are private classes
    in the SDK, so a run that silently depended on them would break on an upgrade
    with no change on this side.
    """
    available = {COMPUTABLE}
    if model_config:
        available.add(MODEL_CONFIG)
    if project:
        available.add(AZURE_AI_PROJECT)
    return tuple(
        spec
        for spec in COVERAGE
        if spec.requires in available
        and (include_experimental or spec.stability == STABLE)
    )
