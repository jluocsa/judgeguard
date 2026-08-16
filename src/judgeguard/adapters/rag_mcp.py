"""Option 1: the incumbent RAG path, behind an MCP wrapper.

    User question -> qa skill -> KM Permissions API -> rag_search -> Milvus/Zilliz

The tool signature the pod showed is `rag_search(query, permissions, topK, Documents)`.
Authorization is decided **before** the call: the skill resolves a permission set
through the KM Permissions API and hands it to the tool, which filters in Milvus.

That makes the permission set an *argument*, which is the security-relevant
difference from Option 2. An argument is asserted by the caller, so a caller that
resolves the wrong set gets a confident, well-formed, wrong answer - and nothing in
the response distinguishes it from a correct one. The conformance suite therefore
asserts the constraint this adapter sends, not only the passages it gets back.

Two things about this adapter are unverified, and both are open action items on the
pod rather than gaps in this code:

  - The MCP server wrapper around `rag_search` is still to be added or completed.
    No manifest and no real request/response have been produced.
  - The `Documents` argument's semantics were never stated. It is passed through
    verbatim from `documents_scope` and defaults to omitted, because guessing at a
    scope filter is how an evaluation quietly measures the wrong corpus.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..contract import Identity, RetrievalResult
from .mcp import (
    ARGUMENT,
    RAG_SEARCH,
    AuthorizationConstraint,
    McpTransport,
    constraint_from,
    elapsed_ms,
    passages_from,
)


class RagSearchRetriever:
    """Binds `rag_search` through an MCP transport."""

    name = "rag-search"

    def __init__(
        self,
        transport: McpTransport,
        *,
        documents_scope: Any = None,
        acl_field: str = "permissions",
    ):
        self._transport = transport
        self._documents_scope = documents_scope
        self._acl_field = acl_field
        # Honest by construction: the ceiling is whatever the transport can prove.
        # A local transport cannot demonstrate that Milvus filtered anything.
        self.evidence_level = transport.evidence_level

    def authorization_for(self, identity: Identity) -> AuthorizationConstraint:
        """The permission set the caller asserts on this identity's behalf.

        Rendered as the literal argument value so a transcript records what was
        actually claimed, not what the harness intended to claim.
        """
        granted = tuple(sorted(identity.clearances))
        return constraint_from(identity, ARGUMENT, repr(list(granted)))

    def arguments_for(
        self, query: str, identity: Identity, top_k: int
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "query": query,
            "permissions": list(self.authorization_for(identity).clearances),
            "topK": top_k,
        }
        if self._documents_scope is not None:
            arguments["Documents"] = self._documents_scope
        return arguments

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult:
        started = time.perf_counter()
        try:
            result = self._transport.call(
                RAG_SEARCH, self.arguments_for(query, identity, top_k)
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


def from_env(documents=None) -> RagSearchRetriever:
    """Build from the environment, or say exactly what is missing."""
    from .mcp import HttpMcpTransport

    url = os.environ.get("JUDGEGUARD_RAG_MCP_URL")
    if not url:
        raise RuntimeError(
            "rag-search needs JUDGEGUARD_RAG_MCP_URL (the MCP endpoint wrapping "
            "rag_search). No such endpoint has been deployed yet; use the "
            "'rag-search-local' adapter to exercise the contract offline at L0."
        )
    token = os.environ.get("JUDGEGUARD_RAG_MCP_TOKEN")
    transport = HttpMcpTransport(
        url, token_provider=(lambda: token) if token else None
    )
    scope = os.environ.get("JUDGEGUARD_RAG_DOCUMENTS_SCOPE")
    return RagSearchRetriever(transport, documents_scope=scope or None)
