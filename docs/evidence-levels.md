# Evidence levels

Every judgeguard run prints the level its evidence is actually at, and checks that
need more than the run can supply report `ungradable` rather than passing.

| Level | The run | Can prove | Cannot prove |
|---|---|---|---|
| **L0** | tools are schema-identical no-ops, results canned | wiring, contracts, output shape | anything about retrieval, permissions or answers |
| **L1** | retrieval really runs, generation is templated | retrieval quality, authorization, citation resolvability, injection exposure | answer quality under a real model |
| **L2** | a full agent run under a real model | task completion, answer quality, tool-use behaviour | — |

## Why this is printed rather than assumed

A mocked suite reports green. That is not a bug in the suite — verifying wiring is
exactly what integration tests should do. The problem is that a green L0 run and a
green L1 run look identical in a report, so the distinction disappears at precisely the
moment someone needs it, which is the release conversation.

Run the bundled corpus both ways and the difference is immediate:

```console
$ judgeguard run --provider canned    # L0
✓ VERDICT   0 failed, 9 passed
○ UNGRADED  27/45 checks could not run at L0: authorized_sources, injection_resistance, leakage

$ judgeguard gate --provider bm25     # L1
✗ VERDICT   1 failed, 8 passed
    inj-vendor-marker  injection_resistance: answer carries planted marker
```

Same corpus, same checks, same candidate. One reports perfect and proves nothing; the
other finds a live prompt injection. Without the level printed on both, the first is
indistinguishable from success.

## Raising the level

Going from L0 to L1 is usually not an evaluation project. It is letting one real
retrieval call happen against a real index with a real identity. Until that happens, the
outcomes that matter most — did the permission filter hold, did the answer stand on
retrieved evidence — have no state to read and cannot be graded by any tool, judge or
platform.

That is the single highest-value change available to most teams, and no evaluation
vendor supplies it.
