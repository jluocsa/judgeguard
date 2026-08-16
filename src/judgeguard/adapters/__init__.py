from .bm25 import Bm25Retriever
from .canned import CannedRetriever

__all__ = ["Bm25Retriever", "CannedRetriever", "build"]

_OFFLINE = {"bm25": Bm25Retriever, "canned": CannedRetriever}


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
    raise RuntimeError(f"unknown adapter {name!r}; known: bm25, canned, azure-search")
