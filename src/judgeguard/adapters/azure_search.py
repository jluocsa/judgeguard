"""Azure AI Search adapter with query-time metadata filtering.

Install the extra to use it:  pip install "judgeguard[search]"

The filter is built from the identity's clearances and applied server side, which
is the control the conformance suite exists to compare against an in-store filter.

Not yet implemented here: the knowledge-base MCP variant that binds
`knowledge_base_retrieve` instead of the search client. That path is on a preview
api-version; it belongs in its own adapter once the version is pinned, rather than
guessed at inside this one.
"""

from __future__ import annotations

import time

from ..contract import Identity, Passage, RetrievalResult
from ..transcript import L1

ACL_FIELD = "acl"


class AzureSearchRetriever:
    name = "azure-search"
    evidence_level = L1

    def __init__(self, endpoint: str, index: str, credential=None, acl_field: str = ACL_FIELD):
        try:
            from azure.identity import DefaultAzureCredential
            from azure.search.documents import SearchClient
        except ImportError as exc:  # fail loud, with the fix
            raise ImportError(
                'AzureSearchRetriever needs the search extra: pip install "judgeguard[search]"'
            ) from exc

        self._acl_field = acl_field
        self._client = SearchClient(
            endpoint=endpoint,
            index_name=index,
            credential=credential or DefaultAzureCredential(),
        )

    def _filter(self, identity: Identity) -> str | None:
        if not identity.clearances:
            return f"{self._acl_field}/any() eq false"
        grants = " or ".join(
            f"c eq '{c}'" for c in sorted(identity.clearances) if "'" not in c
        )
        return f"{self._acl_field}/any(c: {grants}) or not {self._acl_field}/any()"

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult:
        started = time.perf_counter()
        try:
            results = self._client.search(
                search_text=query,
                filter=self._filter(identity),
                top=top_k,
                query_type="semantic",
            )
            passages = tuple(
                Passage(
                    id=str(r["id"]),
                    text=r.get("content", ""),
                    source=r.get("source", str(r["id"])),
                    score=float(r.get("@search.score", 0.0)),
                    acl=frozenset(r.get(self._acl_field) or ()),
                )
                for r in results
            )
        except Exception as exc:  # surfaced in the transcript, never swallowed
            return RetrievalResult(
                provider=self.name,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        return RetrievalResult(
            provider=self.name,
            passages=passages,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
