# Using judgeguard on CSA Workbench

Grade a finished [CSA Workbench](https://github.com/DanGiannone1/csa-workbench) Foundry
run with judgeguard, without rerunning the agent and without replacing anything.

```bash
pip install -e ../..      # judgeguard, from this checkout
python ingest.py
```

Runs offline. No Azure, no credentials, no agent execution.

## What this is not

It is not a replacement for `harness.py`. CSA Workbench's layer-3 oracle diffs the whole
Engagement store, enforces the role-rank rules, waives assertions a declining run cannot
exercise, and reports three contract keys `UNVERIFIED` rather than passing them. For that
domain it is **better than judgeguard's generic checks**, and this example treats its
verdict as ground truth rather than second-guessing it.

That repo's example lane already states judgeguard's three invariants in its own words —
deterministic oracle that judges cannot overturn, a judge deployment that must differ
from the model under test, and unobservable contract keys reported rather than passed.
Two projects reaching the same design independently is the reason these compose cleanly.

## What it adds

The question a completed run cannot answer about itself: **are those judges worth
anything?** The run reports `8/11` and `10/11` per evaluator, which look like quality
measurements. Whether they track the deterministic oracle is a separate question, and it
is measurable.

It is also a working prototype of **transcript ingest**. judgeguard's `run()` drives a
retriever and a candidate, so it cannot grade an agent that owns its own tool loop.
Reading a finished run into judgeguard's own types is the way in, and the two lanes and
agreement statistics then work unchanged. This is the design that `judgeguard grade
--transcripts` should ship.

## The output

```
deterministic gate: 11/11 passed

agreement with the deterministic oracle, per evaluator
  evaluator                   n   agree      kappa  skipped
  intent_resolution          10   100%        n/a  1
  task_adherence             11    91%        n/a  -
  task_completion            11    73%        n/a  -
  tool_call_accuracy         10    80%        n/a  1
  ...
```

## Four findings, and one number that must not be printed

### 1. kappa is not reportable for this run

The gate passed every turn. When one rater uses a single category, agreement happens
exactly when the other rater agrees, so observed and expected agreement are identically
equal and **kappa is forced to 0.000** — whether the judge failed one turn or nine.

```
gate all-pass, judge fails 1/11 -> observed 0.909  expected 0.909  kappa 0.0
gate all-pass, judge fails 3/11 -> observed 0.727  expected 0.727  kappa 0.0
gate all-pass, judge fails 5/11 -> observed 0.545  expected 0.545  kappa 0.0
```

Printing `0.00` and calling the judges worthless would be reporting arithmetic about the
gate's variance as a fact about the judge — the exact error this repository exists to
prevent. The example prints `n/a` and explains why.

To get a discriminating number, compare against a rater that varies: a run containing
real gate failures, or human labels via `judgeguard label` then `judgeguard agree`.

### 2. The disagreements cluster, and the pattern is the finding

Three turns were passed by the oracle and failed by judges. They are not spread evenly.

| Turn | What it is | Judges that failed it |
|---|---|---|
| `ACME-8-vague-create` | vague request, agent asked for clarification | task_adherence, task_completion |
| `ACME-4-boundary` | unauthorized action, agent refused | task_completion, tool_call_accuracy, tool_selection, tool_output_utilization |
| `ACME-5/open` | `"Open it."` — terse referential turn | task_completion, tool_call_accuracy, tool_input_accuracy, tool_output_utilization |

Two shapes, two different causes:

- **Declining was correct.** The agent refused an action the caller was not authorized to
  take, and asked a clarification instead of guessing. It was penalised for behaving
  well. Judges scoring correct refusals poorly is a known systematic failure, and it is
  the single strongest argument for why a judge score must never reach an exit code.
- **The judge could not see prior turns.** `"Open it."` cannot be graded without the
  conversation that gives *it* a referent. Several evaluators said so and skipped.

The second is a **payload problem, not an agent problem** — and it does not inflate
scores, it silently deflates them.

### 3. The eight scores cannot be averaged

Two evaluators are scored 1–5 (`intent_resolution`, `tool_call_accuracy`); six are 0/1.
Thresholds vary too — 0, 1 and 3 all appear.

A mean across them is not on any scale. This matters because **judgeguard's own default
`judge_labels` would do exactly that**: it averages every score and thresholds the mean
at 3.0, which on this data would classify almost everything as unacceptable and produce a
confident, meaningless number. The example uses each evaluator's own `passed` flag and
compares each to the gate separately.

A default that is wrong for real data is worth knowing about in the tool that ships it.

### 4. A skipped evaluation is not a zero

Seven evaluations were skipped by the service — *"No tool calls found in response"*,
*"the CONVERSATION content is not actually provided"*. They are excluded rather than
scored. Averaging a skip in as `0` manufactures a judgement nobody made, and it would
land hardest on exactly the declining turns that were already being penalised.

## How the ingest maps

| CSA Workbench | judgeguard | Consequence |
|---|---|---|
| `harness_pass` | `CheckResult` | keeps its ability to gate |
| each evaluator score | `JudgeScore` | can never gate |
| one dataset row | `CaseOutcome` | two lanes, side by side |
| the run | `RunResult` | `agreement`, `report`, baselines all work |

That mapping is chosen once, in code, rather than argued about per release.

Evidence level is recorded as **L2** — a real agent run under a real model produced these
transcripts, which is the level CSA Workbench reaches and judgeguard's own bundled corpus
does not.

## Data provenance

`sample-run.json` is derived from the committed sample run in the CSA Workbench repo at
`examples/agent-framework-lane/.foundry/results/`. It carries only what the analysis
needs — item id, `harness_pass`, truncated query, and per-evaluator score, verdict,
status and truncated reason. The underlying content is that repo's invented demo fixture;
it contains no customer data.

Point at your own run with `--results`:

```bash
python ingest.py --results ../../../csa-workbench/examples/agent-framework-lane/.foundry/results/<run>.json
```

## What to do with this

The highest-value follow-up is not more analysis. It is that `harness.py` returns exit 1
correctly and **nothing in CI runs it** — `verify:ci` runs pytest, an evidence test that
asserts on `globals.css` and `package.json`, and a readiness lint. A correct gate that no
pull request can trip. Wiring it in is a few lines and needs no judgeguard at all.
