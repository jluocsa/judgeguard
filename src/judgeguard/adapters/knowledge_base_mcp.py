"""Option 2: Azure AI Search / Foundry IQ knowledge base, behind an MCP tool.

    User question -> qa skill -> knowledge_base_retrieve -> Azure AI Search

The knowledge-base MCP endpoint is

    {AZURE_SEARCH_ENDPOINT}/knowledgebases/{AZURE_SEARCH_KB_NAME}/mcp
        ?api-version=2025-11-01-preview

authenticated with a bearer token for `https://search.azure.com/.default`, exposing
one tool: `knowledge_base_retrieve`.

This is the adapter `azure_search.py` deliberately did not become. That module talks
to `SearchClient` directly; this one binds the MCP tool the `qa` skill would actually
call, which is a different integration with a different failure surface even though
both end at the same index.

The difference from Option 1 that matters: authorization is a **query-time metadata
filter** the service enforces, not a permission list the caller asserts. That is the
stronger boundary - a caller cannot over-claim - and it is the thing the pod said had
to be validated before adoption. `authorization_for` renders that filter, and the
conformance suite reads the clearances back out of it, so a clearance dropped or
mis-escaped during rendering fails as a document the adapter did not authorize rather
than passing as a quiet under-retrieval.

The api-version is a preview. It is pinned here rather than defaulted silently,
because a retrieval contract that changes under an unpinned preview version is not a
contract.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from ..contract import Identity, RetrievalResult
from .azure_search import ACL_FIELD, _escape_odata
from .mcp import (
    FILTER,
    KNOWLEDGE_BASE_RETRIEVE,
    AuthorizationConstraint,
    McpTransport,
    constraint_from,
    elapsed_ms,
    passages_from,
)

API_VERSION = "2025-11-01-preview"
SEARCH_SCOPE = "https://search.azure.com/.default"
DEFAULT_KB_NAME = "tax-knowledge"


def endpoint_url(endpoint: str, knowledge_base: str, api_version: str = API_VERSION) -> str:
    return (
        f"{endpoint.rstrip('/')}/knowledgebases/{knowledge_base}"
        f"/mcp?api-version={api_version}"
    )


class KnowledgeBaseRetriever:
    """Binds `knowledge_base_retrieve` through an MCP transport."""

    name = "knowledge-base"

    def __init__(
        self,
        transport: McpTransport,
        *,
        acl_field: str = ACL_FIELD,
        knowledge_base: str | None = None,
    ):
        self._transport = transport
        self._acl_field = acl_field
        self._knowledge_base = knowledge_base
        self.evidence_level = transport.evidence_level

    def authorization_for(self, identity: Identity) -> AuthorizationConstraint:
        """The metadata filter the service will enforce for this identity.

        Identical in meaning to `AzureSearchRetriever._filter`, and deliberately so:
        if the direct-client path and the MCP path disagree about who may read what,
        one of them is wrong, and the conformance suite is where that surfaces.
        """
        unrestricted = f"not {self._acl_field}/any()"
        if not identity.clearances:
            rendered = unrestricted
        else:
            grants = " or ".join(
                f"c eq '{_escape_odata(c)}'" for c in sorted(identity.clearances)
            )
            rendered = f"{self._acl_field}/any(c: {grants}) or {unrestricted}"
        return constraint_from(identity, FILTER, rendered)

    def arguments_for(
        self, query: str, identity: Identity, top_k: int
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "query": query,
            "filter": self.authorization_for(identity).rendered,
            "top": top_k,
        }
        if self._knowledge_base:
            arguments["knowledgeBase"] = self._knowledge_base
        return arguments

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult:
        started = time.perf_counter()
        try:
            result = self._transport.call(
                KNOWLEDGE_BASE_RETRIEVE, self.arguments_for(query, identity, top_k)
            )
            passages = passages_from(result, acl_field=self._acl_field)
        except Exception as exc:  # surfaced in the transcript, never swallowed
            return RetrievalResult(
                provider=self.name,
                latency_ms=elapsed_ms(started),
                error=f"{type(exc).__name__}: {exc}",
            )
        return RetrievalResult(
            provider=self.name,
            passages=passages[:top_k],
            latency_ms=elapsed_ms(started),
        )


def default_token_provider() -> Callable[[], str]:
    """A managed-identity token for the search plane, fetched per call.

    Per call rather than once, because a long evaluation run outlives a token and a
    run that dies halfway through authorization looks like a retrieval regression.
    """
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise ImportError(
            'knowledge-base needs the search extra: pip install "judgeguard[search]"'
        ) from exc

    credential = DefaultAzureCredential()
    return lambda: credential.get_token(SEARCH_SCOPE).token


def from_env(documents=None) -> KnowledgeBaseRetriever:
    """Build from the environment, or say exactly what is missing."""
    from .mcp import HttpMcpTransport

    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "knowledge-base needs AZURE_SEARCH_ENDPOINT (and optionally "
            "AZURE_SEARCH_KB_NAME, default 'tax-knowledge'). Use the "
            "'knowledge-base-local' adapter to exercise the contract offline at L0."
        )
    knowledge_base = os.environ.get("AZURE_SEARCH_KB_NAME", DEFAULT_KB_NAME)
    key = os.environ.get("AZURE_SEARCH_KEY")
    token_provider = (lambda: key) if key else default_token_provider()
    transport = HttpMcpTransport(
        endpoint_url(endpoint, knowledge_base), token_provider=token_provider
    )
    return KnowledgeBaseRetriever(transport)
