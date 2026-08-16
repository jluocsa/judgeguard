# Using judgeguard with Microsoft Agent Framework

[Agent Framework](https://github.com/microsoft/agent-framework) builds the agent and
scores it. judgeguard decides whether it ships.

```bash
pip install judgeguard agent-framework-core
```

```python
from judgeguard.bridges import transcript_from_agent_response
from judgeguard.corpus import Corpus
from judgeguard.ingest import grade
from judgeguard.gate import exit_code

corpus = Corpus.load("corpus/qa-pod")

transcripts = []
for case in corpus.cases:
    result = await agent.run(case.query)          # your Agent Framework agent
    transcripts.append(transcript_from_agent_response(result, case))

run = grade(corpus, transcripts)
raise SystemExit(exit_code(run.all_checks))       # 0, or 1 if a check failed
```

That is the whole integration. The agent is not re-run and nothing about how it ran is
inferred - `AgentResponse` already holds the tool calls, their results and the final
answer, so the bridge is a translation.

## Which tool does which job

They do not overlap, and it is worth being precise about why.

| | Agent Framework | judgeguard |
|---|---|---|
| Question | how good was the answer | is this allowed to ship |
| Output | scores | an exit code |
| Method | LLM judges | assertions about world state |
| On disagreement | reports a lower number | fails the build |

**Use Agent Framework's evaluation for the judge lane.** `evaluate_agent()` runs the
agent, converts it and evaluates in one call; `evaluate_traces()` grades runs that
already happened, from OTel traces or response ids, with no changes to agent code; and
its evaluator catalog is larger than the one judgeguard maps - it adds
`task_navigation_efficiency`, `coherence`, `fluency`, `similarity` and the safety
evaluators.

judgeguard does not compete with any of that and should not. What it adds is a lane
Agent Framework does not have: deterministic checks that can fail a build, evidence
levels, an independence guard, and agreement statistics for the judges themselves.

## Why a judge cannot be the gate

Three of the eight checks judgeguard ships assert things no judge can:

| Check | Asserts |
|---|---|
| `authorized_sources` | no passage outside the caller's clearance was returned |
| `leakage` | no forbidden material reached the answer by any route |
| `injection_resistance` | an instruction planted in a retrieved document was not obeyed |

These are statements about world state, not about text quality. A judge asked whether an
answer leaked restricted material returns a number between 1 and 5, and there is no
threshold on that number that means *no material leaked*.

There is a sharper reason, measured rather than argued. On a real completed Foundry run
of an Agent Framework agent, every disagreement between the judges and a deterministic
oracle was the agent **behaving correctly** - a refusal it was right to make, a
clarification it was right to ask. Optimising against those judges would train the agent
to be more compliant, which is to say less safe. See
[`examples/csa-workbench`](../examples/csa-workbench).

## The bridge

```python
transcript_from_agent_response(
    response,                     # agent_framework.AgentResponse
    case,                         # judgeguard Case
    passages=(),                  # retrieved passages, if your harness surfaces them
    evidence_level=L2,            # claim honestly
    provider="agent-framework",
)
```

Tool calls are paired with their results **by `call_id`, not by position**, so
interleaved or out-of-order results still land on the right call. A retry survives as two
calls. A result with no matching call is reported as `<unmatched result>` rather than
dropped, because a trace with a hole in it should not grade as though it were whole.

A failed call keeps its error. That matters more than it looks: an adapter that swallowed
a timeout would return no result, and a run that returned nothing reads as a legitimate
refusal to answer. `tests/test_agent_framework_bridge.py` pins all of this against the
real framework types.

### Two things the bridge will not guess

**Passages.** What counts as a retrieved passage is a property of your retrieval tool's
response shape. Inferring it would silently decide what the authorization checks read, so
pass them explicitly or accept that those checks report what they can and no more.

```python
transcript_from_agent_response(result, case, passages=[
    {"id": doc.id, "source": doc.source, "text": doc.text, "acl": sorted(doc.acl)}
])
```

**Evidence level.** It defaults to `L2` because an `AgentResponse` is the output of a
real run, but judgeguard cannot verify that your tools were real. If they were mocked,
say `L0` - overstating it buys checks graded against world state that does not exist, and
the level is printed on every report precisely so a reader can challenge it.

## Both lanes from one run

Nothing has to be executed twice. The same transcripts feed the gate and the Foundry
dataset:

```bash
judgeguard grade        --corpus corpus/qa-pod --transcripts run.jsonl   # the gate
judgeguard emit-dataset --corpus corpus/qa-pod --transcripts run.jsonl --out .foundry
```

Every emitted row carries `gate_verdict` and `gate_pass`, so a reviewer opening the
Foundry dashboard sees on one line that a judge scored a turn well and the gate rejected
it. That disagreement is the most informative thing in a run, and it is invisible when
the verdict lives in a separate report.

## One wire format, two implementations

Foundry's agent evaluators read a conversation of typed content blocks. A bare string
does not fail - it degrades, and it degrades downward, so nobody investigates.

Agent Framework solves this in `AgentEvalConverter`. judgeguard solves it in
`rows.to_messages`, because the deterministic lane carries no runtime dependencies and
cannot import a framework to emit a dictionary. The two produce identical output, and
that is asserted rather than assumed:

```bash
pip install -e ".[dev,parity]"
pytest tests/test_message_shape_parity.py
```

If that test fails after an upgrade, **Agent Framework is the authority** - update
judgeguard to match it.

## Status

The bridge is tested against `agent-framework-core` on every commit, constructed from
real framework types rather than dictionaries imitating them. It has **not** been run
against a live agent with a model behind it; nothing in that path needs credentials, but
saying it has been exercised end to end would be more than has happened.
