"""Option 1 and Option 2 must be indistinguishable where it counts.

This is the conformance objective the two candidate retrieval backends both have to
satisfy: `rag_search` over Milvus, and `knowledge_base_retrieve` over Azure AI Search.
It exists so the choice between them is decided by measured conformance rather than
by preference, and so that a difference in a later bakeoff is a difference in
retrieval quality rather than a difference in behaviour.

The two do not authorize the same way, and that asymmetry is the point:

  Option 1  the caller resolves a permission set and passes it as an argument
  Option 2  the caller sends a filter predicate and the service enforces it

An argument is a claim; a filter is a constraint. The tests below assert that the two
mechanisms reach the *same observable outcome* for the same identity, and separately
record the trust boundary they do not share - because a comparison that silently
treats a caller-asserted permission list as equivalent to a service-enforced filter
has already conceded the security question it was supposed to answer.

Neither backend is reachable from a test run. Both adapters run here against a local
transport that really applies the ACL, so what is proven is that the **adapters**
agree. That is not evidence that either deployed service enforces anything, and the
adapters declare L0 under this transport so no check can mistake it for evidence that
they do.
"""

from __future__ import annotations

import pytest

from judgeguard.adapters import local_pair
from judgeguard.adapters.mcp import (
    ARGUMENT,
    FILTER,
    KNOWLEDGE_BASE_RETRIEVE,
    RAG_SEARCH,
    FaultyTransport,
    LocalCorpusTransport,
    McpError,
    clearances_in_odata,
)
from judgeguard.contract import Identity
from judgeguard.corpus import Corpus
from judgeguard.transcript import L0

UNCLEARED = Identity("analyst", frozenset())
HR = Identity("hr-lead", frozenset({"hr"}))
LEGAL = Identity("counsel", frozenset({"legal"}))
BOTH = Identity("admin", frozenset({"hr", "legal"}))

IDENTITIES = [UNCLEARED, HR, LEGAL, BOTH]
QUERIES = [
    "band 4 salary ranges",
    "who releases a litigation hold",
    "travel reimbursement deadline",
    "log retention period",
]


@pytest.fixture(scope="module")
def corpus():
    return Corpus.load("corpus")


@pytest.fixture
def options(corpus):
    """Both options over one corpus. Same documents, same queries, same identities."""
    return local_pair(corpus.documents)


def visible(adapter, query, identity, top_k=8):
    result = adapter.retrieve(query, identity=identity, top_k=top_k)
    assert result.error is None, f"{adapter.name} errored: {result.error}"
    return {p.id for p in result.passages}


# --- the conformance objective ----------------------------------------------


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize(
    "identity", IDENTITIES, ids=lambda i: i.principal
)
def test_both_options_return_the_same_documents(options, query, identity):
    """The contract: same question, same identity, same authorized result set."""
    rag, knowledge_base = options
    assert visible(rag, query, identity) == visible(knowledge_base, query, identity)


@pytest.mark.parametrize("query", QUERIES)
@pytest.mark.parametrize("identity", IDENTITIES, ids=lambda i: i.principal)
def test_neither_option_returns_a_document_the_identity_cannot_read(
    corpus, options, query, identity
):
    """Whoever enforces it, the outcome asserted is the same one."""
    acl_of = {d.id: d.acl for d in corpus.documents}
    for adapter in options:
        for document_id in visible(adapter, query, identity):
            assert identity.may_read(acl_of[document_id]), (
                f"{adapter.name} surfaced {document_id} to {identity.principal}"
            )


def test_a_restricted_document_is_withheld_and_released_by_clearance(options):
    """The permission pack, run against both options at once."""
    for adapter in options:
        denied = visible(adapter, "band 4 salary ranges", UNCLEARED)
        assert "doc-salary-bands" not in denied, adapter.name

        allowed = visible(adapter, "band 4 salary ranges", HR)
        assert "doc-salary-bands" in allowed, adapter.name


def test_a_clearance_grants_only_its_own_documents(options):
    """An hr clearance must not open legal material, and the reverse."""
    for adapter in options:
        assert "doc-litigation-hold" not in visible(
            adapter, "who releases a litigation hold", HR
        ), adapter.name
        assert "doc-salary-bands" not in visible(
            adapter, "band 4 salary ranges", LEGAL
        ), adapter.name


# --- the asymmetry the contract does not hide -------------------------------


def test_the_two_options_authorize_by_different_mechanisms(options):
    """Recorded, not smoothed over: this is the security-relevant difference."""
    rag, knowledge_base = options
    assert rag.authorization_for(HR).kind == ARGUMENT
    assert knowledge_base.authorization_for(HR).kind == FILTER


@pytest.mark.parametrize("identity", IDENTITIES, ids=lambda i: i.principal)
def test_both_options_claim_the_same_clearances(options, identity):
    """Different wire forms, one meaning. If these diverge, so will the results."""
    rag, knowledge_base = options
    assert (
        rag.authorization_for(identity).clearances
        == knowledge_base.authorization_for(identity).clearances
    )


@pytest.mark.parametrize("identity", IDENTITIES, ids=lambda i: i.principal)
def test_no_clearance_is_lost_on_the_way_to_the_wire(options, identity):
    """The rendered form has to carry every clearance the identity holds.

    Read back out of the wire form rather than trusted, because the failure this
    catches - a clearance silently dropped during rendering - looks downstream like
    a retrieval quality problem and not like a bug.
    """
    rag, knowledge_base = options
    assert set(rag.authorization_for(identity).clearances) == identity.clearances
    assert clearances_in_odata(
        knowledge_base.authorization_for(identity).rendered
    ) == identity.clearances


def test_a_quoted_clearance_survives_both_wire_forms(options):
    """An apostrophe in a group name must not narrow what the caller may read."""
    awkward = Identity("odd", frozenset({"o'brien-team", "hr"}))
    rag, knowledge_base = options
    assert set(rag.authorization_for(awkward).clearances) == awkward.clearances
    assert clearances_in_odata(
        knowledge_base.authorization_for(awkward).rendered
    ) == awkward.clearances


# --- what the adapters actually put on the wire ------------------------------


def test_option_one_sends_the_signature_the_pod_specified(options):
    """`rag_search(query, permissions, topK, Documents)`."""
    rag, _ = options
    arguments = rag.arguments_for("salary bands", HR, 5)
    assert arguments == {"query": "salary bands", "permissions": ["hr"], "topK": 5}


def test_the_documents_argument_is_omitted_until_its_meaning_is_known(options):
    """No manifest has been published for it; a guessed scope filter would silently
    change which corpus is being measured."""
    rag, _ = options
    assert "Documents" not in rag.arguments_for("anything", HR, 5)


def test_the_documents_argument_is_passed_through_when_supplied(corpus):
    from judgeguard.adapters.rag_mcp import RagSearchRetriever

    scoped = RagSearchRetriever(
        LocalCorpusTransport(corpus.documents), documents_scope="Intela KM"
    )
    assert scoped.arguments_for("anything", HR, 5)["Documents"] == "Intela KM"


def test_option_two_sends_a_filter_the_service_enforces(options):
    _, knowledge_base = options
    arguments = knowledge_base.arguments_for("salary bands", HR, 5)
    assert arguments["query"] == "salary bands"
    assert arguments["top"] == 5
    assert "acl/any(c: c eq 'hr')" in arguments["filter"]
    assert "not acl/any()" in arguments["filter"]


def test_option_two_matches_the_direct_search_client_filter(corpus):
    """Two paths to one index must not disagree about who may read what."""
    from judgeguard.adapters.azure_search import AzureSearchRetriever

    direct = object.__new__(AzureSearchRetriever)
    direct._acl_field = "acl"
    _, knowledge_base = local_pair(corpus.documents)
    for identity in IDENTITIES:
        assert (
            direct._filter(identity)
            == knowledge_base.authorization_for(identity).rendered
        )


# --- honesty about what this proves -----------------------------------------


def test_a_local_transport_confers_no_evidence(options):
    """Passing here says the adapters agree, not that any service enforces anything."""
    for adapter in options:
        assert adapter.evidence_level == L0


def test_a_live_transport_would_raise_the_ceiling(corpus):
    from judgeguard.adapters.knowledge_base_mcp import KnowledgeBaseRetriever
    from judgeguard.adapters.mcp import HttpMcpTransport
    from judgeguard.transcript import L1

    live = KnowledgeBaseRetriever(HttpMcpTransport("https://example.invalid/mcp"))
    assert live.evidence_level == L1


def test_the_tools_are_named_as_the_pod_named_them(options, corpus):
    """A transport that only answers to the real tool names catches a rename."""

    class StrictTransport:
        evidence_level = L0

        def __init__(self):
            self.seen = []

        def call(self, tool, arguments):
            self.seen.append(tool)
            return {"results": []}

    from judgeguard.adapters.knowledge_base_mcp import KnowledgeBaseRetriever
    from judgeguard.adapters.rag_mcp import RagSearchRetriever

    for retriever_cls, expected in (
        (RagSearchRetriever, RAG_SEARCH),
        (KnowledgeBaseRetriever, KNOWLEDGE_BASE_RETRIEVE),
    ):
        transport = StrictTransport()
        retriever_cls(transport).retrieve("q", identity=HR, top_k=3)
        assert transport.seen == [expected]


# --- QA-10: a failed retrieval must not look like an empty one ---------------


FAULTS = [
    McpError("HTTP 429 from the tool: Too Many Requests"),
    McpError("tool unreachable: timed out"),
    McpError("HTTP 503 from the tool: Service Unavailable"),
    ValueError("malformed response"),
]


@pytest.mark.parametrize("fault", FAULTS, ids=lambda f: type(f).__name__ + str(f)[:24])
def test_a_failed_call_is_recorded_not_silently_emptied(fault):
    """Zero passages and a recorded fault are different facts.

    An adapter that swallowed the error would return no passages, and a run that
    returned no passages reads as a legitimate refusal to answer. That is a
    fabricated pass, so the failure has to survive into the transcript.
    """
    from judgeguard.adapters.knowledge_base_mcp import KnowledgeBaseRetriever
    from judgeguard.adapters.rag_mcp import RagSearchRetriever

    for retriever_cls in (RagSearchRetriever, KnowledgeBaseRetriever):
        transport = FaultyTransport(fault)
        result = retriever_cls(transport).retrieve("anything", identity=HR, top_k=5)

        assert result.passages == ()
        assert result.error, f"{retriever_cls.__name__} hid {fault!r}"
        assert type(fault).__name__ in result.error
        assert transport.calls == 1, "a failure must not be silently retried here"


def test_the_error_carries_enough_to_decide_on_a_retry():
    """Bounded retry needs the status; 'it failed' is not an actionable trace."""
    from judgeguard.adapters.rag_mcp import RagSearchRetriever

    throttled = FaultyTransport(McpError("HTTP 429 from rag_search: Too Many Requests"))
    result = RagSearchRetriever(throttled).retrieve("q", identity=HR)
    assert "429" in result.error


def test_an_unreadable_response_shape_fails_loudly():
    """No candidate server has published a real response shape yet.

    Guessing wrong must produce an error naming what was seen, not zero passages
    that would be graded as a correct no-result.
    """
    from judgeguard.adapters.rag_mcp import RagSearchRetriever

    class OddShape:
        evidence_level = L0

        def call(self, tool, arguments):
            return {"unexpected": [{"id": "x"}]}

    result = RagSearchRetriever(OddShape()).retrieve("q", identity=HR)
    assert result.passages == ()
    assert "unexpected" in result.error and "confirmed against a real call" in result.error
