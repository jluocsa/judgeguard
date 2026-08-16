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
# Offered by the Foundry Evaluations service with no local SDK class at all. It can
# never be constructed in-process, so it is excluded from `runnable_with` and
# reachable only through an upload.
SERVICE_ONLY = "service-only"

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
    # The Foundry Evaluations service name, where one exists. The service catalog
    # and the SDK catalog are not the same list: the service exposes
    # builtin.task_completion with no SDK class, and the SDK's private tool
    # evaluators are first-class service evaluators.
    service: str | None = None
    # Which row field feeds each evaluator input when uploading to the service.
    # Agent evaluators read a conversation, RAG evaluators read strings, and the
    # field names collide - so the mapping is explicit rather than inferred.
    mapping: tuple[tuple[str, str], ...] = ()

    def data_mapping(self) -> dict[str, str]:
        """Evaluator input -> row field. Identity unless overridden."""
        overrides = dict(self.mapping)
        return {field: overrides.get(field, field) for field in self.inputs}


# Agent evaluators read the conversation, not two strings.
AGENT_SHAPE = (("query", "query_messages"), ("response", "response_messages"))


COVERAGE: tuple[EvaluatorSpec, ...] = (
    EvaluatorSpec(
        "GroundednessEvaluator",
        "groundedness",
        MODEL_CONFIG,
        ("query", "response", "context"),
        service="builtin.groundedness",
    ),
    EvaluatorSpec(
        "RelevanceEvaluator",
        "relevance",
        MODEL_CONFIG,
        ("query", "response"),
        service="builtin.relevance",
    ),
    EvaluatorSpec(
        "RetrievalEvaluator",
        "retrieval",
        MODEL_CONFIG,
        ("query", "context"),
        service="builtin.retrieval",
    ),
    EvaluatorSpec(
        "IntentResolutionEvaluator",
        "intent_resolution",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
        service="builtin.intent_resolution",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "ToolCallAccuracyEvaluator",
        "tool_call_accuracy",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
        service="builtin.tool_call_accuracy",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "TaskAdherenceEvaluator",
        "task_adherence",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
        service="builtin.task_adherence",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "ResponseCompletenessEvaluator",
        "response_completeness",
        MODEL_CONFIG,
        ("response", "ground_truth"),
        requires_nonempty=("ground_truth",),
        service="builtin.response_completeness",
    ),
    EvaluatorSpec(
        "DocumentRetrievalEvaluator",
        "retrieval_ranking",
        COMPUTABLE,
        ("retrieval_ground_truth", "retrieved_documents"),
        requires_nonempty=("retrieval_ground_truth",),
        service="builtin.document_retrieval",
    ),
    EvaluatorSpec(
        "IndirectAttackEvaluator",
        "injection_exposure",
        AZURE_AI_PROJECT,
        ("query", "response"),
    ),
    # --- experimental, private in the SDK; opt in with include_experimental -----
    # All four are first-class evaluators on the Foundry service. Only the local
    # SDK classes are private, which is why they are opt-in here and still
    # uploadable by name.
    EvaluatorSpec(
        "_ToolSelectionEvaluator",
        "tool_selection",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_selection._tool_selection",
        service="builtin.tool_selection",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "_ToolInputAccuracyEvaluator",
        "tool_input_accuracy",
        MODEL_CONFIG,
        ("query", "response", "tool_calls", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_input_accuracy._tool_input_accuracy",
        service="builtin.tool_input_accuracy",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "_ToolOutputUtilizationEvaluator",
        "tool_output_utilization",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_output_utilization._tool_output_utilization",
        service="builtin.tool_output_utilization",
        mapping=AGENT_SHAPE,
    ),
    EvaluatorSpec(
        "_ToolCallSuccessEvaluator",
        "tool_call_success",
        MODEL_CONFIG,
        ("response", "tool_definitions"),
        stability=EXPERIMENTAL,
        module=f"{_TOOL_EVALUATORS}._tool_call_success._tool_call_success",
        service="builtin.tool_call_success",
        mapping=AGENT_SHAPE,
    ),
    # --- service-only: no SDK class exists ------------------------------------
    # Task completion and response completeness are two different service
    # evaluators. The SDK ships only ResponseCompletenessEvaluator, so this one
    # cannot be run locally at any version - naming it here is the difference
    # between a known gap and a silently missing dimension.
    EvaluatorSpec(
        "builtin.task_completion",
        "task_completion",
        MODEL_CONFIG,
        ("query", "response", "tool_definitions"),
        stability=SERVICE_ONLY,
        service="builtin.task_completion",
        mapping=AGENT_SHAPE,
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


def service_specs(*, stable_only: bool = False) -> tuple[EvaluatorSpec, ...]:
    """Evaluators that can be requested from the Foundry Evaluations service.

    Experimental evaluators are included by default here, unlike the local scorer.
    The four tool evaluators are private only as SDK *classes*; as service
    evaluators they are ordinary names on the wire, so the reason to withhold them
    locally does not apply to an upload.
    """
    return tuple(
        spec
        for spec in COVERAGE
        if spec.service and not (stable_only and spec.stability != STABLE)
    )


def testing_criteria(judge_deployment: str, *, stable_only: bool = False) -> list[dict]:
    """The service payload: one criterion per evaluator, each with its own mapping.

    The mapping is the part that matters. Agent evaluators are pointed at the
    message-shaped fields and RAG evaluators at the string-shaped ones, because
    `query` and `response` mean different things to the two families and a single
    row carries both.
    """
    return [
        {
            "type": "azure_ai_evaluator",
            "name": spec.dimension,
            "evaluator_name": spec.service,
            "data_mapping": {
                field: f"{{{{item.{source}}}}}"
                for field, source in spec.data_mapping().items()
            },
            "initialization_parameters": {"deployment_name": judge_deployment},
        }
        for spec in service_specs(stable_only=stable_only)
    ]


def runnable_with(
    *, model_config: bool, project: bool, include_experimental: bool = False
) -> tuple[EvaluatorSpec, ...]:
    """What can actually run in-process given the credentials on hand.

    Experimental evaluators are excluded unless asked for. They are private classes
    in the SDK, so a run that silently depended on them would break on an upgrade
    with no change on this side. Service-only evaluators are always excluded: there
    is no class to construct.
    """
    available = {COMPUTABLE}
    if model_config:
        available.add(MODEL_CONFIG)
    if project:
        available.add(AZURE_AI_PROJECT)
    allowed = {STABLE} | ({EXPERIMENTAL} if include_experimental else set())
    return tuple(
        spec
        for spec in COVERAGE
        if spec.requires in available and spec.stability in allowed
    )
