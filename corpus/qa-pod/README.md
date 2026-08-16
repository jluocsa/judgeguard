# Q&A pod case pack

The Q&A capability pod's case matrix (QA-01 to QA-11), expressed in judgeguard's
corpus schema so it can be run rather than reviewed.

```bash
judgeguard gate --corpus corpus/qa-pod
judgeguard bakeoff --corpus corpus/qa-pod --a rag-search-local --b knowledge-base-local
```

The documents are **synthetic** and CC0, written for this pack. Nothing in them comes
from any real client, engagement or library.

## What happened when the matrix was made executable

The matrix was written as a scenario table, which is the right shape for agreeing
scope and the wrong shape for gating a build. Turning it into cases surfaced three
things worth more than the pack itself.

**Two cases declare two acceptable outcomes.** QA-02 expects the system to "infer
likely knowledge intent **or** ask a useful clarification"; QA-04 expects it to
"abstain **or** reformulate". A case that accepts either of two outcomes cannot be
deterministically graded — whichever happens, it passed. Both are encoded here as the
stricter branch, and both need splitting into two cases before they can gate.

**Three expectations need evidence an L1 run does not produce.** A refusal is a
property of the generated answer, and a clarification is the *absence* of a retrieval
that this harness performs unconditionally. They report `ungradable`, which is the
honest result: the alternative is a green check that means nothing.

**Two cases need harness capabilities that do not exist,** so they are not in the pack
at all. A case whose distinguishing condition cannot be produced would pass vacuously,
and a vacuous pass is worse than an acknowledged gap.

## The mapping

| Case | Scenario | Expressed as | Graded today |
|---|---|---|---|
| QA-01 | Direct answer, one authoritative source | `expected_sources`, `expected_answer`, `expected_behavior: answer` | **Yes** — `expected_sources` + `expected_behavior` |
| QA-02 | Terse prompt (`engagement letter`) | `variant: keyword`, `expected_behavior: clarification`, `forbidden_tools` | Partly — tool scope gates; the clarification is ungradable |
| QA-03 | Source content not loaded | `expected_sources: []`, `expected_behavior: no_result` | **Yes** |
| QA-04 | No relevant result available | `expected_sources: []`, `expected_behavior: no_result` | **Yes** — but see the disjunction above |
| QA-05 | Ambiguous request | `expected_behavior: clarification` | No — ungradable at L1 |
| QA-06 | Wrong-capability request | `forbidden_tools: [retrieve]`, `expected_behavior: no_result` | **Yes, and it fails.** See below |
| QA-07 | Multi-turn follow-up | `prior_turns` | Partly — the context is carried, the runner is single-turn |
| QA-08 | Conflicting authorized sources | two `expected_sources` | **Yes** — retrieval of both sides; surfacing the conflict is judged |
| QA-09 | Unauthorized best match | `forbidden_sources`, `expected_behavior: refusal` | **Yes** — `leakage` + `authorized_sources`; the refusal wording is ungradable |
| QA-10 | MCP timeout, throttle, hard failure | *not a case* | Covered by `tests/conformance/test_option_equivalence.py` |
| QA-11 | Skill-enabled versus skill-disabled | *not a case* | A run configuration: `judgeguard bakeoff` |

## QA-06 fails, and that is the report

`judgeguard gate --corpus corpus/qa-pod` exits 1. One case fails, on two checks:

```
QA-06  expected_behavior: expected no result, but 4 passage(s) were returned
QA-06  tool_scope: called tool(s) this case forbids: ['retrieve']
```

A record-creation request should be routed elsewhere and leave the Q&A capability
inactive. This harness retrieves unconditionally, so it cannot. The pack is not
broken; the capability under test does not satisfy the case, and the pack says so.
It turns green when a routing layer exists — which is exactly what a gate is for.

## What the deterministic evidence column became

The matrix's "deterministic evidence" column maps onto checks, and the "judged
dimensions" column onto the advisory lane. They never cross:

| Matrix column | Lane | Can block a build |
|---|---|---|
| Deterministic evidence | `lanes/checks/` | Yes |
| Judged dimensions | Foundry evaluators | Never |

QA-09's row reads "Safety gate: any leakage fails". That is correct, and it is the
reason it is asserted in code rather than scored: a judge asked whether an answer
leaked restricted material returns a number between 1 and 5, and there is no
threshold on that number that means "no material leaked".

## A finding about the retriever, not the cases

QA-03 and QA-04 are phrased as keyword queries here rather than full sentences. That
is not stylistic. The bundled BM25 retriever has no stopword list and no relevance
floor, so a natural-language question about an unindexed topic still matches `the`,
`is` and `for`, returns passages, and cannot produce a no-result outcome at all.

Both candidate backends score and threshold, so both should behave differently — and
that difference is now measurable rather than assumed, which is the point of running
the same pack against both.

## Case format

Beyond the base schema in [../README.md](../README.md), this pack uses:

| Field | Meaning |
|---|---|
| `expected_behavior` | `answer`, `no_result`, `refusal` or `clarification` |
| `expected_tools` | tools that must be called |
| `forbidden_tools` | tools that must not be — the wrong-capability assertion |
| `prior_turns` | earlier turns a follow-up depends on |

`expected_behavior` is validated on load. An unknown value raises rather than
silently disabling the check, because a case whose expectation never runs is
indistinguishable from a case that passes.
