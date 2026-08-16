# Evaluator coverage

Which Azure AI Foundry evaluator covers which judgeguard dimension, and — the part
that actually decides anything — what each one needs before it can run.

Verified by introspecting the installed `azure-ai-evaluation` package (1.18.3):
constructor signatures, declared singleton inputs and prompty input declarations, not
documentation.

```console
$ judgeguard coverage
```

| Evaluator | Dimension | Requires | Inputs |
|---|---|---|---|
| `GroundednessEvaluator` | groundedness | model config | query, response, context |
| `RelevanceEvaluator` | relevance | model config | query, response |
| `RetrievalEvaluator` | retrieval | model config | query, context |
| `IntentResolutionEvaluator` | intent_resolution | model config | query, response, tool_definitions |
| `ToolCallAccuracyEvaluator` | tool_call_accuracy | model config | query, response, tool_calls, tool_definitions |
| `TaskAdherenceEvaluator` | task_adherence | model config | query, response, tool_definitions |
| `ResponseCompletenessEvaluator` | response_completeness | model config | response, ground_truth |
| `DocumentRetrievalEvaluator` | retrieval_ranking | **nothing** | retrieval_ground_truth, retrieved_documents |
| `IndirectAttackEvaluator` | injection_exposure | project connection | query, response |

Four more are shipped, but not as public API:

| Evaluator | Dimension | Requires | Exported | Inputs |
|---|---|---|---|---|
| `_ToolSelectionEvaluator` | tool_selection | model config | no | query, response, tool_calls, tool_definitions |
| `_ToolInputAccuracyEvaluator` | tool_input_accuracy | model config | no | query, response, tool_calls, tool_definitions |
| `_ToolOutputUtilizationEvaluator` | tool_output_utilization | model config | yes | query, response, tool_definitions |
| `_ToolCallSuccessEvaluator` | tool_call_success | model config | yes | response, tool_definitions |

## The finding that matters

**Seven of the nine stable evaluators need only a bare model config** — an endpoint, a
deployment name and a key. Not a Foundry project, not a workspace, not a hub.

That is the difference between "point the judge at the service" being a configuration
change and being a procurement conversation, and it is invisible from any capability
list. One evaluator computes locally with no model at all. Only `IndirectAttackEvaluator`
and the safety evaluators need a real project connection and a credential.

If you are deciding whether to adopt a managed evaluation service, this table is the
comparison, not the feature list.

```python
from judgeguard.scorers.foundry import coverage

coverage.runnable_with(model_config=True, project=False)   # 8 of 9 stable
coverage.runnable_with(model_config=False, project=False)  # 1 of 9 stable
coverage.runnable_with(model_config=True, project=True, include_experimental=True)
```

## The four tool evaluators are experimental, and that is load-bearing

A plan that lists tool selection, tool input accuracy, tool output utilization and tool
call success as available evaluators is listing four classes that the SDK prefixes with
an underscore and marks experimental on construction. Two of the four are not exported
from the package namespace at all and can only be reached by importing their private
module path.

judgeguard maps them, because pretending they do not exist is not useful. It excludes
them unless `include_experimental=True`, because a private class can be renamed in a
patch release and a run that silently depended on one would change its score with no
change on this side. `FoundryScorer` resolves them through the module path recorded on
the spec and fails with the installed SDK version named, so the breakage is legible.

**There is no `TaskCompletionEvaluator` in 1.18.3.** Task completion and response
completeness are not two shipped evaluators; `ResponseCompletenessEvaluator` is the one
that exists, and judgeguard names its dimension `response_completeness` after it rather
than implying coverage it does not have.

## If you are building on Microsoft Agent Framework

Use its evaluation support for the judge lane. It is more ergonomic than anything here
and it is maintained by the people who own the wire format:

| Agent Framework | What it does |
|---|---|
| `evaluate_agent()` | runs the agent, converts, evaluates - one call |
| `AgentEvalConverter` | the typed message conversion Foundry evaluators need |
| `evaluate_traces()` | grades runs that already happened, from OTel traces or response ids |

Its evaluator catalog is also larger than the table above: it adds
`task_navigation_efficiency`, `coherence`, `fluency`, `similarity` and the safety
evaluators.

judgeguard does not compete with that and should not. What it adds is the other lane -
deterministic checks that can fail a build, evidence levels, the independence guard, and
agreement statistics. **Agent Framework answers "how good was the answer". judgeguard
answers "is this allowed to ship".** The two compose: grade with Agent Framework, gate
with judgeguard.

`rows.to_messages` exists only because the deterministic lane carries no runtime
dependencies and so cannot import a framework to emit a dictionary. Its output is
asserted equal to `AgentEvalConverter`'s in
[`test_message_shape_parity.py`](../tests/test_message_shape_parity.py), which runs
whenever `agent-framework-core` is installed. If that test fails after an upgrade, the
framework is the authority.

## Reference answers are not document identifiers
`ResponseCompletenessEvaluator` scores a response against `ground_truth`, and
`ground_truth` is reference **text**. A corpus case supplies it through
`expected_answer`. `expected_sources` is a different field answering a different
question — which documents retrieval should have reached — and it feeds
`retrieval_ground_truth`, the labelled input to `DocumentRetrievalEvaluator`.

Handing document identifiers to a reference-scored evaluator returns a confident number
describing how well an answer resembles a list of ids. A case that declares no
reference is reported as ungradable on those dimensions rather than scored, and
`estimate` does not bill for the call, because an absent reference is a gap in the
corpus and scoring it zero would blame the candidate for it.

## They map onto existing dimensions

No new metrics have to be invented. The agent evaluators — intent resolution,
tool-call accuracy, task adherence, response completeness — line up with dimensions any
agent eval already cares about, which means adopting the service is a change of
scoring backend rather than a change of what you measure.

## What the service does not supply

Worth stating plainly, because the comparison is usually made on the wrong basis. A
managed evaluation lane saves you building a judge harness, a row format and a score
store, and it gives you judge reasoning and trend storage without new infrastructure.

It does **not**:

- **supply the deterministic lane.** Every evaluator above is a judge or a metric.
  Authorization, leakage and injection resistance are outcome assertions about world
  state and stay in code permanently.
- **fix mocked tools.** At L0 there is no permission decision and no retrieved passage
  for any evaluator to read, and the score you get back will look exactly like the one
  you would get from a real run.
- **write your corpus.** A lane with nothing to run measures nothing.

## Why none of them gate

Every Foundry evaluator lands in the advisory lane, including
`DocumentRetrievalEvaluator`, which is computable and therefore deterministic.

That is a deliberate call. Deterministic is not the same as *assertable*: NDCG is a
quality measurement with a tunable threshold, not a statement about whether the system
did the right thing. Wiring it to an exit code reintroduces exactly the threshold
argument the two-lane split exists to end.

If you want a retrieval-ranking outcome to gate, write the assertion explicitly as a
check in `lanes/checks/` where it is visible, versioned and reviewable — rather than
inheriting a gate from a metric's default threshold.

## Usage

```bash
pip install "judgeguard[foundry]"

export AZURE_OPENAI_ENDPOINT=https://...
export JUDGEGUARD_JUDGE_DEPLOYMENT=gpt-4o-judge
export JUDGEGUARD_CANDIDATE_DEPLOYMENT=gpt-4o-candidate   # must differ

judgeguard gate --scorer foundry
```

The independence guard applies here too. Point both variables at the same deployment
and judgeguard refuses to start, whichever scoring backend is selected.

## What will it cost

```bash
judgeguard estimate --price-in 2.50 --price-out 10.00
```

The projection is built from a real (free) retrieval run, so the context and answer
sizes are actual rather than assumed. Two things it surfaces that are hard to see
otherwise:

- **Template overhead dominates short cases.** Measured against 1.18.3, the rubrics
  run from ~1,460 tokens (`groundedness_without_query`) to ~4,260 (`retrieval`). On the
  bundled 9-case corpus that is **89% of all input tokens**. Trimming your corpus saves
  far less than dropping a dimension you do not use.
- **Not everything is token-billed.** `IndirectAttackEvaluator` is charged per service
  call, and `DocumentRetrievalEvaluator` costs nothing at all.

`estimate.measure_overhead()` re-derives the per-evaluator figures from whatever SDK
version is installed, so the constants can be refreshed rather than trusted.

## Status

The coverage map, the row conversion and the results merge are implemented and tested
offline on every commit, including a test that every evaluator the map claims is still
present in the installed SDK.

The live service call in `FoundryScorer` has **not** returned a real score yet. One
thing is already known about it: the SDK logs *"Conversation history could not be
parsed; falling back to raw input. Evaluator accuracy will degrade"* when handed
judgeguard's plain-string `query` and `response`. The agent evaluators want
message-shaped input, so that conversion has to be built before `tool_call_accuracy`
or `task_adherence` can be relied on. A degraded score that still returns a number is
exactly the failure mode this repository exists to make visible, so it is recorded here
rather than discovered later.
