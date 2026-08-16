# Writing an adapter

An adapter is one class with one method. If it satisfies the contract, the conformance
suite and every check work against it unchanged.

```python
from judgeguard.contract import Identity, Passage, RetrievalResult
from judgeguard.transcript import L1


class MyRetriever:
    name = "my-retriever"
    evidence_level = L1

    def retrieve(self, query, *, identity, top_k=5) -> RetrievalResult:
        rows = my_backend.search(
            query,
            top=top_k,
            acl_filter=sorted(identity.clearances),   # enforce server side
        )
        return RetrievalResult(
            provider=self.name,
            passages=tuple(
                Passage(
                    id=r.id,
                    text=r.content,
                    source=r.source,
                    score=r.score,
                    acl=frozenset(r.acl),
                )
                for r in rows
            ),
            latency_ms=rows.elapsed_ms,
        )
```

## Declare your evidence level honestly

This is the only part people get wrong, and it is the part that matters.

| Declare | When |
|---|---|
| `L0` | results are canned, or the ACL filter is not really applied |
| `L1` | retrieval really runs and the filter is really enforced |
| `L2` | a full agent run under a real model produced the transcript |

Declaring L1 when you are at L0 does not make the checks pass — it makes them pass
*dishonestly*, which is worse than the `ungradable` you were avoiding.

## Errors go in the result, never in an exception

```python
return RetrievalResult(provider=self.name, error=f"{type(exc).__name__}: {exc}")
```

The transcript records the failure and the checks grade what happened. Swallowing the
error and returning empty passages produces a run that looks like a legitimate refusal.

## Run the conformance suite

```python
# tests/conformance/test_my_adapter.py
import pytest
from judgeguard.corpus import Corpus


@pytest.fixture
def adapter():
    return MyRetriever()
```

Then run `pytest tests/conformance`. Two adapters that both pass this suite unchanged
can be compared with `judgeguard bakeoff`, and a difference in the report is a
difference in retrieval quality rather than a difference in behaviour.
