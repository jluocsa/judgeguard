# Foundry eval for the IDA harness Q&A capability

The full pipeline, on the Q&A case pack, with the thirteen evaluators the Q&A pod
specified. Runs end to end offline as far as the upload; the upload itself needs a
Foundry project.

```bash
pip install -e ../..

judgeguard gate --corpus ../../corpus/qa-pod                     # 1. the gate
judgeguard emit-dataset --corpus ../../corpus/qa-pod --out .foundry   # 2. the rows
python foundry_eval.py --dry-run                                 # 3. what would be sent
python foundry_eval.py                                           # 4. score it
```

## Why this exists

There is an easy demo and a correct one. The easy one shows a finished eval run and
talks about the dashboard. The correct one shows where a Foundry row *comes from*, and
that is the part a team actually has to build.

It is also the reason the CSA Workbench example next door is not this demo. That one
grades an Engagement CRUD agent with eight agent evaluators and no RAG evaluators at
all. Q&A needs thirteen, and the five RAG ones are the half that matters most.

## The thirteen, and what each is for

| Evaluator | Family | Reference needed |
|---|---|---|
| `builtin.retrieval` | RAG | no |
| `builtin.groundedness` | RAG | no |
| `builtin.relevance` | RAG | no |
| `builtin.response_completeness` | RAG | **yes** |
| `builtin.document_retrieval` | RAG | **yes** |
| `builtin.intent_resolution` | agent | no |
| `builtin.tool_call_accuracy` | agent | no |
| `builtin.tool_selection` | agent | no |
| `builtin.tool_input_accuracy` | agent | no |
| `builtin.tool_output_utilization` | agent | no |
| `builtin.tool_call_success` | agent | no |
| `builtin.task_adherence` | agent | no |
| `builtin.task_completion` | agent | no |

Eleven of thirteen are **reference-free**, which is the single most useful fact here:
a first run needs no labelled corpus. `corpus/qa-pod` carries `expected_answer` on every
case anyway, so `response_completeness` works too.

## The bug this demo exists to avoid

`query` and `response` mean **different things** to the two families, and a row has to
carry both shapes.

| Family | reads `query` as | reads `response` as |
|---|---|---|
| RAG | a string | a string |
| agent | the conversation history | the agent's messages, with tool calls as typed blocks |

Hand an agent evaluator a bare string and it does not fail. It falls back to raw input,
logs *"Evaluator accuracy will degrade"*, and returns a number anyway.

Worse, on a terse follow-up it gives up entirely. This is from a real recorded run of a
different agent, on the turn whose user text was `"Open it."`:

```
intent_resolution   skipped   "the CONVERSATION_HISTORY content is not actually provided"
tool_selection      skipped   "the CONVERSATION content is not actually provided"
```

Four more evaluators scored that turn as a failure. The agent had done nothing wrong —
the judges could not see the previous turns, so `"it"` had no referent. **A payload
problem that reads downstream as an agent problem**, and it deflates rather than
inflates, so nobody goes looking.

`judgeguard emit-dataset` emits both shapes on every row and the criteria point each
evaluator at the right one:

```
groundedness         builtin.groundedness        query, response, context
intent_resolution    builtin.intent_resolution   query_messages, response_messages, tool_definitions
```

`Case.prior_turns` is what makes the history reconstructable, which is why a multi-turn
case has to declare it. QA-07 asks *"and what about the fees"*, and its `query_messages`
carries the question before it.

**Known limitation:** `prior_turns` records the user's earlier turns only, so the
reconstructed history has no assistant replies in it. That is strictly better than a
bare string — the referent is present — but it is not a full transcript. A harness that
emits its own transcripts should supply the assistant turns too.

## The gate rides with the rows

Every emitted row carries `gate_verdict` and `gate_pass`.

```json
{"item_id": "QA-06", "gate_verdict": "fail", "gate_pass": false, ...}
```

This is worth copying wherever the eval ends up. A reviewer opening the dashboard sees,
on one line, that a judge scored a turn well and the deterministic gate rejected it. That
disagreement is the most informative thing in the run, and it is invisible if the verdict
lives in a different report.

`judgeguard gate` decided the exit code before any of this ran. Uploading cannot change
it.

## What the run reports today

```
9 rows -> .foundry/dataset.jsonl
13 evaluators requested, L1 evidence
    retrieval_ranking: 6/9 rows carry no reference to grade
gate verdict, already decided: 8/9 passed
```

Two things in that output are the demo.

**`L1 evidence`** — retrieval is real, generation is not. So groundedness and relevance
are being asked about a templated answer, and they will report on the template. Foundry
cannot fix that, and neither can judgeguard; only a real generation step can. Printing
the level is what stops a green dashboard being mistaken for one.

**`6/9 rows carry no reference to grade`** — six Q&A cases expect no documents, because
the correct behaviour is to decline or report no result. There is no ranking to score, so
those rows are not sent and not billed. A skipped evaluation is not a zero.

The one failing case is `QA-06`: a wrong-capability request that should leave Q&A
inactive. The harness retrieves unconditionally, so it cannot. That is a real finding
about the system under test, and it is the gate doing its job.

## Judge independence

`foundry_eval.py` refuses to start when the judge deployment equals the deployment under
test:

```bash
export FOUNDRY_PROJECT_ENDPOINT=https://...
export FOUNDRY_JUDGE_DEPLOYMENT=gpt-4o-judge
export JUDGEGUARD_CANDIDATE_DEPLOYMENT=gpt-4o-candidate   # must differ
```

judgeguard enforces the same rule for its in-process scorer. It has to hold on the upload
path too, or the guarantee is only as good as which route someone happened to take.

## What has and has not been executed

Read this before demoing live.

| | Status |
|---|---|
| `judgeguard gate` on the pack | run, repeatedly |
| `judgeguard emit-dataset` | run; the committed `.foundry/` output is from a real run |
| `foundry_eval.py --dry-run` | run |
| `foundry_eval.py` upload | **never executed against a Foundry project** |

The upload flow is modelled line by line on `scripts/foundry_eval.py` in
[CSA Workbench](https://github.com/DanGiannone1/csa-workbench) — the same two-step
`evals.create` then `evals.runs.create` against the OpenAI-compatible client, the same
`DataSourceConfigCustom` item schema, the same polling loop. That script demonstrably
works against a real project. This one has only been checked for argument handling and
failure ordering.

**So rehearse the upload before the demo, or run it in `--dry-run`.** The `item_schema`
here declares judgeguard's row fields rather than CSA Workbench's, and a schema mismatch
is the most likely thing to surface on a first real run.

## What this demo does not show

It grades **retrieval**, not the IDA harness. The evidence level says so — `L1`, real
retrieval and mocked generation. The answer is templated, so `groundedness` and
`relevance` are scoring a template rather than a model.

Grading the harness itself needs the harness to emit transcripts and judgeguard to ingest
them. That path is prototyped in [`../csa-workbench`](../csa-workbench) but is not yet a
shipped command, and until it is, no demo can honestly claim to evaluate the IDA harness
end to end.

The corpus is also synthetic. `corpus/qa-pod` encodes the pod's QA-01…QA-09 case shapes
over invented documents, not IDA's real knowledge base.

## Where the pattern came from

The upload flow follows `scripts/foundry_eval.py` in
[CSA Workbench](https://github.com/DanGiannone1/csa-workbench), which is the only version
of this known to work end to end against a real project. The difference is that the
criteria are generated from judgeguard's coverage map rather than hand-maintained, so an
evaluator cannot quietly be pointed at the wrong field.

## Demo running order

| | Segment | Time | Runs offline |
|---|---|---|---|
| 1 | Why two lanes — `../csa-workbench`, real data, the correct-refusal finding | 10 min | yes |
| 2 | **This** — the pipeline, the thirteen evaluators, the payload trap | 20 min | yes, up to upload |
| 3 | Option 1 vs Option 2 — `judgeguard bakeoff` on the same pack | 10 min | yes |

Segment 1 earns the two-lane argument with evidence. Segment 2 is the how-to. Segment 3
is the decision the pod actually has to make.
