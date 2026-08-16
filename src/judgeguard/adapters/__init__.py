"""Retrieval adapters. One class, one method, one contract.

Five are registered. Two are offline reference implementations, one talks to Azure AI
Search directly, and two bind the MCP tools the Q&A pod is choosing between:

  bm25                  in-memory BM25, ACL filtered before scoring        L1
  canned                fixed results, no filter at all                    L0
  azure-search          SearchClient, query-time metadata filter           L1
  rag-search            Option 1, `rag_search` over MCP                    transport
  knowledge-base        Option 2, `knowledge_base_retrieve` over MCP       transport

The last two take their evidence level from their transport, because an adapter
pointed at a local double has not demonstrated that a real store enforced anything.
Their `-local` variants exist so the contract can be exercised today: the Option 1
MCP wrapper is not deployed, which would otherwise make the comparison unrunnable and
leave the choice to be made on preference.
"""

from .bm25 import Bm25Retriever
from .canned import CannedRetriever

__all__ = [
    "Bm25Retriever",
    "CannedRetriever",
    "KnowledgeBaseRetriever",
    "RagSearchRetriever",
    "build",
    "local_pair",
]

_OFFLINE = {"bm25": Bm25Retriever, "canned": CannedRetriever}


def __getattr__(name):
    """Keep the MCP adapters importable by name without importing them eagerly."""
    if name == "RagSearchRetriever":
        from .rag_mcp import RagSearchRetriever

        return RagSearchRetriever
    if name == "KnowledgeBaseRetriever":
        from .knowledge_base_mcp import KnowledgeBaseRetriever

        return KnowledgeBaseRetriever
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def local_pair(documents):
    """Both MCP options over one local corpus, for a like-for-like comparison.

    This is the pair the conformance suite runs. Neither is evidence about a deployed
    service; both are evidence about whether the adapters agree on who may read what,
    which is the question that has to be settled before any live comparison means
    anything.
    """
    from .knowledge_base_mcp import KnowledgeBaseRetriever
    from .mcp import LocalCorpusTransport
    from .rag_mcp import RagSearchRetriever

    return (
        RagSearchRetriever(LocalCorpusTransport(documents)),
        KnowledgeBaseRetriever(LocalCorpusTransport(documents)),
    )


def build(name: str, documents):
    """Adapters needing credentials are imported lazily so the offline lane stays clean."""
    if name in _OFFLINE:
        return _OFFLINE[name](documents)
    if name == "azure-search":
        import os

        from .azure_search import AzureSearchRetriever

        endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
        index = os.environ.get("AZURE_SEARCH_INDEX")
        if not endpoint or not index:
            raise RuntimeError(
                "azure-search needs AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_INDEX"
            )
        return AzureSearchRetriever(endpoint=endpoint, index=index)
    if name == "rag-search":
        from .rag_mcp import from_env

        return from_env(documents)
    if name == "knowledge-base":
        from .knowledge_base_mcp import from_env

        return from_env(documents)
    if name in ("rag-search-local", "knowledge-base-local"):
        rag, knowledge_base = local_pair(documents)
        return rag if name == "rag-search-local" else knowledge_base
    raise RuntimeError(
        f"unknown adapter {name!r}; known: bm25, canned, azure-search, rag-search, "
        "knowledge-base, rag-search-local, knowledge-base-local"
    )
