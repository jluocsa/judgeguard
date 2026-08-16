# Grading an agent that owns its own tool loop

The contract the IDA harness has to satisfy, and the command that grades it.

```bash
pip install -e ../..

python emit_transcripts.py                                    # the agent runs itself
judgeguard grade --corpus ../../corpus/qa-pod \
                 --transcripts .transcripts/run.jsonl         # judgeguard grades it
```

## Why the runner is not enough

`judgeguard gate` drives a retriever and then a candidate. That is the right shape for
comparing two retrieval backends and the wrong shape for an agent, because an agent
decides *whether* to retrieve, retries when the evidence is thin, declines when it is not
authorized, and routes elsewhere when the question is not its job. None of that survives
being flattened into `retrieve() then answer()` — and all of it is what the evaluation
exists to inspect.

So the agent runs itself and writes transcripts, and judgeguard reads them. Both lanes,
evidence levels, baselines, agreement statistics and the Foundry dataset then work
unchanged, because every one of them already reads the transcript and nothing else.

## The contract

Nine fields. `case_id` has to match a case in the corpus; the rest describe what happened.

```json
{"case_id": "QA-01",
 "query": "what notice period does the current engagement letter require to cancel",
 "principal": "consultant",
 "provider": "ida-harness",
 "evidence_level": "L2",
 "tool_calls": [{"name": "retrieve",
                 "arguments": {"query": "...", "principal": "consultant"},
                 "result": ["qa-doc-engagement-letter-v3"],
                 "error": null}],
 "passages": [{"id": "qa-doc-engagement-letter-v3",
               "source": "library/engagement-letter@v3",
               "score": 1.0, "acl": [], "text": "..."}],
 "answer": "...",
 "latency_ms": 0.0,
 "meta": {"variant": "natural", "candidate": "ida-harness"}}
```

Record every tool call in the order it happened, with its arguments and its result, and
put failures in `error` rather than dropping them. A call whose failure was swallowed is
indistinguishable from a call that returned nothing, and the second one grades as a
legitimate no-result.

## Evidence level is declared by you, and taken on trust

This is the one thing judgeguard cannot verify. An emitter that claims `L2` for a run
whose tools were mocked gets checks graded against world state that does not exist.

Claim honestly:

| Declare | When |
|---|---|
| `L0` | results are canned, or the ACL filter is not really applied |
| `L1` | retrieval really ran and the filter was really enforced |
| `L2` | a real model produced the answer |

The level is printed on every report, so a reader can challenge it. Nothing else in the
system can.

## What L2 buys, concretely

Run the same corpus both ways.

```console
$ judgeguard gate --corpus corpus/qa-pod                 # L1, judgeguard retrieves
✗ VERDICT   1 failed, 8 passed
○ UNGRADED  3/72 checks could not run at L1: expected_behavior
    QA-06  expected_behavior: expected no result, but 4 passage(s) were returned
    QA-06  tool_scope: called tool(s) this case forbids: ['retrieve']

$ judgeguard grade --transcripts .transcripts/run.jsonl  # L2, the agent chose
✗ VERDICT   1 failed, 8 passed
○ UNGRADED  1/72 checks could not run at L2: expected_behavior
    QA-08  expected_sources: expected source(s) not retrieved: ['qa-doc-engagement-letter-v2']
```

Same verdict count, **different findings**, and that is the point.

- **QA-06 passes at L2.** A wrong-capability request should leave Q&A inactive. The
  runner retrieves unconditionally so it cannot; the agent routed to CRUD instead, and
  `tool_scope` can see that it did.
- **QA-08 fails at L2.** Two conflicting versions of the engagement letter are indexed
  and a correct answer surfaces both. The agent returned only the current one. That is a
  real defect the L1 run could not reach.
- **Ungradable falls from 3 to 1.** A clarification is the *absence* of a retrieval. The
  runner always retrieves, so at L1 there is no decision to grade; a real agent records
  the choice it made, so at L2 there is.

The one that stays ungradable is the refusal, and deliberately. Whether the wording
declines is a judge question. Whether the restricted material reached the caller is not —
and `leakage` and `authorized_sources` already assert exactly that, and do gate. A phrase
match here would look like a third assertion and be a string compare.

## Partial runs fail loudly

```console
$ judgeguard grade --transcripts partial.jsonl
✗ TranscriptMismatch: 2 case(s) have no transcript: ['QA-08', 'QA-09']
  A partial run reported as a full one is not evidence about the suite.
  Pass --allow-partial to grade the subset, and read the result as a subset.
```

A transcript naming a case the corpus does not declare is always an error. Grading nine
of eleven cases and reporting the verdict as though the suite had run is how a partial
run gets read as a complete one.

## Then send it to Foundry

`emit-dataset` takes transcripts too, so the same run feeds the advisory lane:

```bash
judgeguard emit-dataset --corpus ../../corpus/qa-pod \
                        --transcripts .transcripts/run.jsonl \
                        --out .foundry
```

The rows carry the agent's real tool calls, its `L2` evidence level, and the gate verdict
that was already decided. See [`../qa-foundry-eval`](../qa-foundry-eval) for the upload.

## Wiring the real harness

Replace `answer_one_case` in [emit_transcripts.py](emit_transcripts.py) with a call into
the harness and keep everything else. The stand-in exists to exercise the shapes — a
retry, a decline, a route — not to be a good agent.

Two things to get right on the way in:

1. **Emit one transcript per case**, with `case_id` matching the corpus.
2. **Record the failures.** `error` on the tool call, not an empty result.
