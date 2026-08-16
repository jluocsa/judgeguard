"""Token and cost projection for a judged run.

The estimate is built from a real retrieval run rather than from the corpus alone,
because the fields that dominate an evaluator's input - the retrieved context and
the answer - do not exist until something retrieves. That run is free: it uses the
offline adapter and the templated candidate, so estimating costs nothing.

No prices are shipped. Model pricing changes, varies by region and tier, and a stale
number baked into a tool is worse than no number. Supply rates to get a cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corpus import Corpus
from .scorers.foundry import coverage
from .scorers.foundry.rows import inputs_for, to_eval_row, ungradable_reason

CHARS_PER_TOKEN = 4.0

# Measured from the shipped prompty templates in azure-ai-evaluation 1.18.3.
# `measure_overhead()` re-derives these from whatever version is installed.
MEASURED_AGAINST = "azure-ai-evaluation 1.18.3"
PROMPT_OVERHEAD_TOKENS = {
    "groundedness": 1680,
    "relevance": 2164,
    "retrieval": 4257,
    "intent_resolution": 2253,
    "tool_call_accuracy": 2787,
    "task_adherence": 1967,
    "response_completeness": 1883,
    "tool_selection": 2121,
    "tool_input_accuracy": 904,
    "tool_output_utilization": 2242,
    "tool_call_success": 2550,
    "retrieval_ranking": 0,
    "injection_exposure": 0,
}

OUTPUT_TOKENS_PER_CALL = 250

TOKENS = "tokens"
SERVICE = "service"
FREE = "free"


def count_tokens(text: str) -> tuple[int, str]:
    """Exact when tiktoken is present, a documented approximation otherwise."""
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text)), "tiktoken"
    except Exception:
        return int(len(text) / CHARS_PER_TOKEN), f"~{CHARS_PER_TOKEN:g} chars/token"


@dataclass(frozen=True)
class LineItem:
    dimension: str
    evaluator: str
    metered: str
    calls: int
    input_tokens: int
    output_tokens: int
    overhead_tokens: int = 0


@dataclass(frozen=True)
class Estimate:
    backend: str
    cases: int
    repeat: int
    method: str
    items: tuple[LineItem, ...]
    price_in: float | None = None
    price_out: float | None = None

    @property
    def input_tokens(self) -> int:
        return sum(i.input_tokens for i in self.items)

    @property
    def output_tokens(self) -> int:
        return sum(i.output_tokens for i in self.items)

    @property
    def calls(self) -> int:
        return sum(i.calls for i in self.items if i.metered != FREE)

    @property
    def overhead_tokens(self) -> int:
        return sum(i.overhead_tokens for i in self.items)

    @property
    def overhead_share(self) -> float | None:
        """Fraction of input tokens that is evaluator rubric rather than your data."""
        if not self.input_tokens:
            return None
        return round(self.overhead_tokens / self.input_tokens, 3)

    @property
    def cost(self) -> float | None:
        """Rates are per million tokens. None when no rates were supplied."""
        if self.price_in is None or self.price_out is None:
            return None
        return round(
            self.input_tokens / 1_000_000 * self.price_in
            + self.output_tokens / 1_000_000 * self.price_out,
            4,
        )

    @property
    def service_metered(self) -> tuple[LineItem, ...]:
        return tuple(i for i in self.items if i.metered == SERVICE)


def estimate_run(
    corpus: Corpus,
    *,
    backend: str = "foundry",
    model_config: bool = True,
    project: bool = False,
    include_experimental: bool = False,
    repeat: int = 1,
    price_in: float | None = None,
    price_out: float | None = None,
    variant: str | None = None,
) -> Estimate:
    from .adapters import Bm25Retriever
    from .candidates import TemplateCandidate
    from .runner import run

    if backend in ("offline", "stub", "none"):
        cases = len(corpus.filter(variant=variant))
        return Estimate(backend, cases, repeat, "no model calls", ())

    result = run(
        corpus, Bm25Retriever(corpus.documents), TemplateCandidate(), variant=variant
    )
    specs = coverage.runnable_with(
        model_config=model_config,
        project=project,
        include_experimental=include_experimental,
    )

    method = ""
    # [input tokens, output tokens, overhead tokens, calls]
    totals: dict[str, list[int]] = {spec.dimension: [0, 0, 0, 0] for spec in specs}
    for outcome in result.outcomes:
        row = to_eval_row(outcome.transcript, outcome.case)
        for spec in specs:
            if ungradable_reason(spec, row):
                continue  # the scorer will not call it, so the estimate must not bill it
            totals[spec.dimension][3] += 1
            if spec.requires in (coverage.COMPUTABLE, coverage.AZURE_AI_PROJECT):
                continue
            payload = inputs_for(spec, row)
            counted, method = count_tokens(_flatten(payload))
            overhead = PROMPT_OVERHEAD_TOKENS.get(spec.dimension, 0)
            totals[spec.dimension][0] += counted + overhead
            totals[spec.dimension][1] += OUTPUT_TOKENS_PER_CALL
            totals[spec.dimension][2] += overhead

    cases = len(result.outcomes)
    items = tuple(
        LineItem(
            dimension=spec.dimension,
            evaluator=spec.evaluator,
            metered=_metering(spec),
            calls=totals[spec.dimension][3] * repeat,
            input_tokens=totals[spec.dimension][0] * repeat,
            output_tokens=totals[spec.dimension][1] * repeat,
            overhead_tokens=totals[spec.dimension][2] * repeat,
        )
        for spec in specs
    )
    return Estimate(
        backend=backend,
        cases=cases,
        repeat=repeat,
        method=method or "no token-metered evaluators",
        items=items,
        price_in=price_in,
        price_out=price_out,
    )


def measure_overhead() -> dict[str, int]:
    """Re-derive prompt overhead from the installed SDK's prompty templates."""
    from pathlib import Path

    import azure.ai.evaluation as evaluation

    root = Path(evaluation.__file__).parent
    filenames = {
        "groundedness": "groundedness_with_query.prompty",
        "relevance": "relevance.prompty",
        "retrieval": "retrieval.prompty",
        "intent_resolution": "intent_resolution.prompty",
        "tool_call_accuracy": "tool_call_accuracy.prompty",
        "task_adherence": "task_adherence.prompty",
        "response_completeness": "response_completeness.prompty",
        "tool_selection": "tool_selection.prompty",
        "tool_input_accuracy": "tool_input_accuracy.prompty",
        "tool_output_utilization": "tool_output_utilization.prompty",
        "tool_call_success": "tool_call_success.prompty",
    }
    measured = {}
    for dimension, filename in filenames.items():
        found = next(root.rglob(filename), None)
        if found:
            measured[dimension] = count_tokens(found.read_text(encoding="utf-8"))[0]
    return measured


def _metering(spec: coverage.EvaluatorSpec) -> str:
    if spec.requires == coverage.COMPUTABLE:
        return FREE
    if spec.requires == coverage.AZURE_AI_PROJECT:
        return SERVICE
    return TOKENS


def _flatten(payload: dict) -> str:
    return "\n".join(str(value) for value in payload.values())
