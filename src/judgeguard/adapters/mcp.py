"""The MCP seam both candidate retrieval backends sit behind.

Two options are on the table, and both are MCP tools bound to the same `qa` skill:

  Option 1  `rag_search(query, permissions, topK, Documents)`  - Milvus/Zilliz
  Option 2  `knowledge_base_retrieve(...)`                     - Azure AI Search

They differ in many ways that do not matter to an evaluation harness - ranking
ownership, hybrid search, who pays for the index - and in exactly one that does:
**where the authorization decision is made.**

Option 1 resolves a permission set through the KM Permissions API and passes it to
the tool as an argument, so the *caller* asserts what it may see. Option 2 sends a
query-time metadata filter and the *service* decides. That is not a preference
question, it is a different trust boundary, and a comparison that scores answer
quality without pinning it is comparing two systems that are not equivalent.

`AuthorizationConstraint` is the provider-neutral form of that decision. It lets the
conformance suite assert that both options deny the same documents for the same
identity without knowing which mechanism produced the denial - which is the whole
point of having a contract rather than two integrations.

Transports are injected because neither service is reachable from a test run. The
Option 1 MCP wrapper is still to be built or completed, and no manifest or real
request/response has been produced for it. `LocalCorpusTransport` implements the
store side of both tools over a local corpus and declares **L0**, so adapter
behaviour is verifiable today without any adapter claiming evidence it does not have.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from itertools import count
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from ..contract import Identity, Passage
from ..corpus import Document
from ..transcript import L0, L1

RAG_SEARCH = "rag_search"
KNOWLEDGE_BASE_RETRIEVE = "knowledge_base_retrieve"

# Where the authorization decision is made.
ARGUMENT = "argument"  # the caller asserts its permissions; the store trusts them
FILTER = "filter"  # the caller sends a predicate; the service enforces it

JSONRPC = "2.0"


class McpError(RuntimeError):
    """A tool call the server rejected, or a response that was not usable."""


@dataclass(frozen=True)
class AuthorizationConstraint:
    """How an adapter tells its backend which documents the caller may read.

    `rendered` is what actually goes on the wire and is provider-specific.
    `clearances` is the provider-neutral claim, and it is what conformance compares:
    two backends that authorize the same set must deny the same documents, however
    differently they spell it.
    """

    kind: str
    clearances: tuple[str, ...]
    rendered: str

    def permits(self, acl: Iterable[str]) -> bool:
        # An empty ACL means public, matching Identity.may_read.
        acl = frozenset(acl)
        return not acl or bool(acl & frozenset(self.clearances))


def constraint_from(identity: Identity, kind: str, rendered: str) -> AuthorizationConstraint:
    return AuthorizationConstraint(
        kind=kind, clearances=tuple(sorted(identity.clearances)), rendered=rendered
    )


@runtime_checkable
class McpTransport(Protocol):
    """Carries one tool call. The adapter owns the arguments, not the plumbing."""

    evidence_level: str

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class HttpMcpTransport:
    """JSON-RPC 2.0 `tools/call` over HTTP, on the standard library only.

    judgeguard's deterministic lane must stay installable with no dependencies, so
    this uses `urllib` rather than pulling in an HTTP client for one POST.

    Not yet executed against a live MCP server. The request shape is JSON-RPC as
    specified; the response *content* shape differs per server and is handled
    tolerantly in `passages_from`, which reports what it could not read rather than
    returning an empty result that would look like a legitimate refusal.
    """

    evidence_level = L1

    def __init__(
        self,
        url: str,
        *,
        token_provider: Callable[[], str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self._token_provider = token_provider
        self._headers = dict(headers or {})
        self._timeout = timeout
        self._ids = count(1)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from urllib import error, request

        payload = {
            "jsonrpc": JSONRPC,
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._headers,
        }
        if self._token_provider:
            headers["Authorization"] = f"Bearer {self._token_provider()}"

        post = request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), headers=headers
        )
        try:
            with request.urlopen(post, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:  # keep the status; it drives retry decisions
            raise McpError(f"HTTP {exc.code} from {tool}: {exc.reason}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise McpError(f"{tool} unreachable: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise McpError(f"{tool} returned a non-JSON body: {exc}") from exc

        if isinstance(body, dict) and body.get("error"):
            detail = body["error"]
            raise McpError(f"{tool} returned an error: {detail}")
        return body.get("result", {}) if isinstance(body, dict) else {}


class LocalCorpusTransport:
    """The store side of both tools, over a local corpus, with the ACL really applied.

    This exists so the *adapters* can be verified offline: whether each one sends an
    authorization constraint that denies the right documents is a property of the
    adapter, and it is checkable without a subscription.

    It declares **L0** because it is not the real store. A passing conformance run
    against this transport says the adapter is correct, not that Milvus or Azure AI
    Search enforces anything. Those are different claims and conflating them is the
    failure this repository exists to prevent.
    """

    evidence_level = L0

    def __init__(self, documents: tuple[Document, ...]):
        self._documents = documents

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == RAG_SEARCH:
            clearances = frozenset(arguments.get("permissions") or ())
            top_k = int(arguments.get("topK") or 5)
            query = str(arguments.get("query", ""))
        elif tool == KNOWLEDGE_BASE_RETRIEVE:
            clearances = clearances_in_odata(str(arguments.get("filter") or ""))
            top_k = int(arguments.get("top") or 5)
            query = str(arguments.get("query", ""))
        else:
            raise McpError(f"no such tool {tool!r}")

        terms = {t for t in re.findall(r"\w+", query.lower())}
        hits = []
        for document in self._documents:
            if document.acl and not (document.acl & clearances):
                continue
            overlap = len(terms & set(re.findall(r"\w+", document.text.lower())))
            if overlap:
                hits.append((overlap, document))
        hits.sort(key=lambda pair: (-pair[0], pair[1].id))
        return {
            "results": [
                {
                    "id": document.id,
                    "content": document.text,
                    "source": document.source,
                    "score": float(overlap),
                    "acl": sorted(document.acl),
                }
                for overlap, document in hits[:top_k]
            ]
        }


class FaultyTransport:
    """A transport that fails the way a real MCP server fails.

    QA-10 asks what happens on timeout, throttle or hard failure, and the answer has
    to be legible: a failure must land in `RetrievalResult.error`, not come back as
    an empty passage list. Zero passages and a recorded fault are the same object to
    a check that only counts results, and the first one would be graded as a
    correct refusal to answer.
    """

    def __init__(self, error: Exception, *, evidence_level: str = L0):
        self.error = error
        self.evidence_level = evidence_level
        self.calls = 0

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise self.error


ODATA_LITERAL = re.compile(r"c eq '((?:[^']|'')*)'")


def clearances_in_odata(expression: str) -> frozenset[str]:
    """Read back the clearances an OData ACL filter grants.

    Used by the local transport so the rendered filter is exercised end to end
    rather than trusted: a clearance dropped or mis-escaped during rendering shows
    up as a document the adapter failed to authorize.
    """
    return frozenset(
        literal.replace("''", "'") for literal in ODATA_LITERAL.findall(expression)
    )


# Keys seen across MCP retrieval servers. Neither candidate server has published a
# real response yet, so the reader tries the documented shapes and says plainly when
# it recognises none, rather than returning zero passages - which a check would
# otherwise grade as a correct refusal to answer.
RESULT_KEYS = ("results", "documents", "passages", "chunks", "value")
TEXT_KEYS = ("content", "text", "chunk", "snippet")
SOURCE_KEYS = ("source", "url", "uri", "path", "filepath")
ID_KEYS = ("id", "documentId", "document_id", "key", "chunk_id")
SCORE_KEYS = ("score", "@search.score", "relevance", "rerankerScore")


def rows_in(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the result list out of an MCP tool result, unwrapping text content."""
    for key in RESULT_KEYS:
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    # MCP servers commonly return a text block holding a JSON document.
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or "text" not in block:
                continue
            try:
                decoded = json.loads(block["text"])
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, list):
                return [row for row in decoded if isinstance(row, dict)]
            if isinstance(decoded, dict):
                return rows_in(decoded)
    raise McpError(
        f"no result list in the tool response; saw keys {sorted(result)}. "
        "The response shape has to be confirmed against a real call."
    )


def passages_from(result: dict[str, Any], *, acl_field: str = "acl") -> tuple[Passage, ...]:
    passages = []
    for index, row in enumerate(rows_in(result)):
        identifier = _first(row, ID_KEYS) or f"row-{index}"
        text = _first(row, TEXT_KEYS) or ""
        passages.append(
            Passage(
                id=str(identifier),
                text=str(text),
                source=str(_first(row, SOURCE_KEYS) or identifier),
                score=float(_first(row, SCORE_KEYS) or 0.0),
                acl=frozenset(row.get(acl_field) or ()),
            )
        )
    return tuple(passages)


def _first(row: dict[str, Any], keys: tuple[str, ...]):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
