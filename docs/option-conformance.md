# Option conformance

Two candidate retrieval backends, one contract, one suite that decides between them on
measured behaviour rather than on preference.

| | Option 1 | Option 2 |
|---|---|---|
| Tool | `rag_search(query, permissions, topK, Documents)` | `knowledge_base_retrieve` |
| Store | Milvus / Zilliz + MongoDB | Azure AI Search knowledge base |
| Authorization | permission set resolved by the caller, passed as an argument | query-time metadata filter, enforced by the service |
| Ranking | the application, plus optional Cohere rerank | semantic ranker |
| Adapter | [`rag_mcp.py`](../src/judgeguard/adapters/rag_mcp.py) | [`knowledge_base_mcp.py`](../src/judgeguard/adapters/knowledge_base_mcp.py) |

```bash
judgeguard bakeoff --a rag-search-local --b knowledge-base-local
pytest tests/conformance
```

## The difference that is not a preference

Most of the differences between these two are trade-offs: who owns ranking, who pays
for the index, how much custom loop code survives. Reasonable people can disagree, and
a bakeoff of answer quality is a fair way to settle it.

One difference is not like the others. **Option 1 passes a permission set as an
argument; Option 2 sends a filter the service enforces.**

An argument is a claim. A filter is a constraint. If the caller resolves the wrong
permission set — a stale cache, a mis-mapped group, a skipped call to the KM
Permissions API — Option 1 returns a confident, well-formed, correctly-cited answer
built on material the user may not read, and nothing in the response distinguishes it
from a correct one. Option 2 cannot fail that way, because the caller never gets to
assert what it may see.

That is a different trust boundary, not a different implementation. A comparison that
scores both on answer quality and declares a winner has quietly assumed the two are
equivalent on the question that matters most.

So the suite asserts both halves separately:

- **The outcome must be identical.** Same question, same identity, same authorized
  document set — whichever mechanism produced it.
- **The mechanism is recorded, not smoothed over.** `AuthorizationConstraint.kind` is
  `argument` for Option 1 and `filter` for Option 2, and a test pins that.

## What the suite checks

```python
from judgeguard.adapters import local_pair

rag, knowledge_base = local_pair(corpus.documents)
rag.authorization_for(identity)             # kind="argument", rendered="['hr']"
knowledge_base.authorization_for(identity)  # kind="filter",   rendered="acl/any(c: c eq 'hr') or not acl/any()"
```

| Assertion | Why |
|---|---|
| Both return the same documents for the same identity | The contract. Without it a quality comparison is meaningless |
| Neither returns a document the identity cannot read | The outcome, independent of who enforced it |
| Both claim the same clearances | Different wire forms, one meaning |
| No clearance is lost on the way to the wire | Read back out of the rendered filter, not trusted |
| A quoted clearance survives both forms | An apostrophe in a group name must not narrow access |
| Option 2 matches the direct `SearchClient` filter | Two paths to one index must not disagree |
| A failed call is recorded, not silently emptied | QA-10 |
| An unreadable response shape fails loudly | No server has published one yet |

## Why a failure must not look like an empty result

An adapter that swallowed a timeout would return zero passages. A run that returns zero
passages reads as a legitimate refusal to answer, and `expected_behavior: no_result`
would grade it as a **pass**.

That is a fabricated green build caused by an outage. Both adapters therefore put the
fault in `RetrievalResult.error` and the conformance suite asserts it survives, for
throttling, timeouts, hard failures and malformed responses. The error text keeps the
status code, because "it failed" is not enough to decide whether a retry is
appropriate.

## What this does not prove

Neither backend is reachable from a test run. The Option 1 MCP wrapper is still to be
added or completed, and no manifest or real request/response has been produced for it.

Both adapters therefore run against `LocalCorpusTransport`, which really applies the
ACL over a local corpus. What passes is that **the adapters agree**. That is not
evidence that Milvus or Azure AI Search enforces anything, and the adapters declare
**L0** under that transport so no check can mistake it for evidence that they do:

```console
$ judgeguard bakeoff --a rag-search-local --b knowledge-base-local
--- rag-search ---
⚠ EVIDENCE  L0  tools mocked, results canned - wiring evidence only
○ UNGRADED  27/45 checks could not run at L0: authorized_sources,
            injection_resistance, leakage
```

The authorization checks report `ungradable`, which is the correct answer to "does
Option 1 enforce permissions correctly" when Option 1 is not deployed. Point either
adapter at a live transport and the same checks start grading.

Two things are unverified and both are open items on the pod rather than gaps here:

- **The `Documents` argument.** Its semantics were never stated, so it is omitted
  unless explicitly supplied. Guessing at a scope filter is how an evaluation quietly
  measures the wrong corpus.
- **The response shape.** Neither server has published one. `passages_from` tries the
  documented shapes and reports what it could not read rather than returning zero
  passages.

## Pointing them at something real

```bash
# Option 1
export JUDGEGUARD_RAG_MCP_URL=https://.../mcp
export JUDGEGUARD_RAG_MCP_TOKEN=...
judgeguard gate --provider rag-search --corpus corpus/qa-pod

# Option 2
export AZURE_SEARCH_ENDPOINT=https://....search.windows.net
export AZURE_SEARCH_KB_NAME=tax-knowledge
judgeguard gate --provider knowledge-base --corpus corpus/qa-pod
```

Option 2 authenticates with a bearer token for `https://search.azure.com/.default` and
targets

```
{AZURE_SEARCH_ENDPOINT}/knowledgebases/{AZURE_SEARCH_KB_NAME}/mcp?api-version=2025-11-01-preview
```

The api-version is pinned in code rather than defaulted, because a retrieval contract
that changes under an unpinned preview version is not a contract.
