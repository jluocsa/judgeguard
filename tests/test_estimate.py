"""Cost projection: built from a real run, priced only when rates are supplied."""

from __future__ import annotations

import pytest

from judgeguard.corpus import Corpus
from judgeguard.estimate import (
    FREE,
    OUTPUT_TOKENS_PER_CALL,
    PROMPT_OVERHEAD_TOKENS,
    SERVICE,
    TOKENS,
    count_tokens,
    estimate_run,
)
from judgeguard.scorers.foundry import coverage


@pytest.fixture(scope="module")
def corpus():
    return Corpus.load("corpus")


def test_tokens_are_counted_by_a_named_method():
    count, method = count_tokens("a reasonably ordinary sentence of prose")
    assert count > 0
    assert method


def test_offline_backend_costs_nothing(corpus):
    projection = estimate_run(corpus, backend="offline")
    assert projection.items == ()
    assert projection.input_tokens == 0
    assert projection.cost is None


def test_no_price_table_is_shipped(corpus):
    """A stale baked-in rate is worse than no rate. Cost is None without inputs."""
    assert estimate_run(corpus, backend="foundry").cost is None


def test_cost_appears_only_with_both_rates(corpus):
    assert estimate_run(corpus, price_in=1.0).cost is None
    assert estimate_run(corpus, price_out=1.0).cost is None

    priced = estimate_run(corpus, price_in=2.5, price_out=10.0)
    expected = round(
        priced.input_tokens / 1_000_000 * 2.5 + priced.output_tokens / 1_000_000 * 10.0,
        4,
    )
    assert priced.cost == expected


def test_repeat_scales_linearly(corpus):
    once = estimate_run(corpus, repeat=1)
    thrice = estimate_run(corpus, repeat=3)
    assert thrice.input_tokens == once.input_tokens * 3
    assert thrice.output_tokens == once.output_tokens * 3
    assert thrice.calls == once.calls * 3


def test_computable_evaluators_are_free(corpus):
    projection = estimate_run(corpus)
    free = [i for i in projection.items if i.metered == FREE]
    assert free
    assert all(i.input_tokens == 0 and i.output_tokens == 0 for i in free)


def test_project_evaluators_are_excluded_unless_requested(corpus):
    without = estimate_run(corpus, project=False)
    assert not any(i.metered == SERVICE for i in without.items)

    with_project = estimate_run(corpus, project=True)
    assert any(i.metered == SERVICE for i in with_project.items)


def test_service_metered_items_carry_no_token_cost(corpus):
    projection = estimate_run(corpus, project=True)
    for item in projection.service_metered:
        assert item.input_tokens == 0, "per-call billing must not be priced per token"


def test_output_tokens_follow_the_call_count(corpus):
    projection = estimate_run(corpus)
    for item in projection.items:
        if item.metered == TOKENS:
            assert item.output_tokens == item.calls * OUTPUT_TOKENS_PER_CALL


def test_overhead_is_tracked_and_dominates_short_cases(corpus):
    projection = estimate_run(corpus)
    assert projection.overhead_tokens > 0
    assert 0 < projection.overhead_share <= 1
    # The finding worth surfacing: for short Q&A you mostly pay for the rubric.
    assert projection.overhead_share > 0.5


def test_every_token_metered_dimension_has_a_measured_overhead():
    """Only what can run in-process is priced, so only that needs a constant.

    A service-only evaluator ships no local prompty. Requiring an overhead figure
    for it would mean inventing one, and a fabricated constant is worse than an
    absent dimension - `estimate_run` never bills for it either, because it prices
    `runnable_with`.
    """
    local = coverage.runnable_with(
        model_config=True, project=False, include_experimental=True
    )
    metered = [s for s in local if s.requires == coverage.MODEL_CONFIG]
    assert metered
    for spec in metered:
        assert spec.dimension in PROMPT_OVERHEAD_TOKENS, (
            f"{spec.dimension} has no measured prompt overhead, so its estimate "
            "would silently understate cost"
        )
        assert PROMPT_OVERHEAD_TOKENS[spec.dimension] > 0


def test_a_service_only_evaluator_is_never_priced_locally():
    service_only = [
        s for s in coverage.COVERAGE if s.stability == coverage.SERVICE_ONLY
    ]
    assert service_only, "the map records at least one service-only evaluator"
    local = coverage.runnable_with(
        model_config=True, project=True, include_experimental=True
    )
    assert not (set(service_only) & set(local))


def test_variant_filter_reduces_the_estimate(corpus):
    everything = estimate_run(corpus)
    keyword_only = estimate_run(corpus, variant="keyword")
    assert 0 < keyword_only.input_tokens < everything.input_tokens
