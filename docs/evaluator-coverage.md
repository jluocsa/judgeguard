# Evaluator coverage

Which Azure AI Foundry evaluator covers which judgeguard dimension, and — the part
that actually decides anything — what each one needs before it can run.

Verified by introspecting the installed `azure-ai-evaluation` package: constructor
signatures and prompty input declarations, not documentation.

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
| `TaskAdherenceEvaluator` | task_adherence | model config | system_message, query, response, tool_calls |
| `ResponseCompletenessEvaluator` | task_completion | model config | response, ground_truth |
| `DocumentRetrievalEvaluator` | retrieval_ranking | **nothing** | retrieval_ground_truth, retrieved_documents |
| `IndirectAttackEvaluator` | injection_exposure | project connection | query, response |

## The finding that matters

**Seven of the nine need only a bare model config** — an endpoint, a deployment name
and a key. Not a Foundry project, not a workspace, not a hub.

That is the difference between "point the judge at the service" being a configuration
change and being a procurement conversation, and it is invisible from any capability
list. One evaluator computes locally with no model at all. Only `IndirectAttackEvaluator`
and the safety evaluators need a real project connection and a credential.

If you are deciding whether to adopt a managed evaluation service, this table is the
comparison, not the feature list.

```python
from judgeguard.scorers.foundry import coverage

coverage.runnable_with(model_config=True, project=False)   # 8 of 9
coverage.runnable_with(model_config=False, project=False)  # 1 of 9
```

## They map onto existing dimensions

No new metrics have to be invented. The agent evaluators — intent resolution,
tool-call accuracy, task adherence, task completion — line up with dimensions any
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

## Status

The coverage map, the row conversion and the results merge are implemented and tested
offline on every commit. The live service call in `FoundryScorer` has **not** been
executed against a real endpoint — the `tool_calls` payload shape in particular should
be confirmed on a first real run before anyone relies on `tool_call_accuracy`.
