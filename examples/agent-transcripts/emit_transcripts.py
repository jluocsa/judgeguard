"""Emit judgeguard transcripts from an agent that owns its own tool loop.

This is the contract the IDA harness has to satisfy to be graded. It is deliberately
small: a transcript is a dataclass with ten fields, five of them required, and everything
judgeguard does
downstream - both lanes, evidence levels, baselines, agreement, the Foundry dataset -
reads from it and nothing else.

Run it to produce a transcript file, then grade it:

    python emit_transcripts.py --out .transcripts/run.jsonl
    judgeguard grade --corpus ../../corpus/qa-pod --transcripts .transcripts/run.jsonl

The agent here is a stand-in. It retries, declines, and routes elsewhere, because
those are the behaviours a single `retrieve() then answer()` call cannot express and
the reason ingest exists at all. Replace `answer_one_case` with a call into the real
harness and the rest of this file stays as it is.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from judgeguard.corpus import Corpus
from judgeguard.transcript import L2, ToolCall, Transcript, write_jsonl

RETRIEVE = "retrieve"
ROUTE = "route_to_capability"

# What this stand-in can reach. A question outside it must produce a no-result
# rather than an invented answer.
INDEXED = {
    "engagement letter": "qa-doc-engagement-letter-v3",
    "notice": "qa-doc-engagement-letter-v3",
    "fees": "qa-doc-engagement-letter-v3",
    "cancel": "qa-doc-engagement-letter-v3",
    "proposal": "qa-doc-proposal-boilerplate",
    "independence": "qa-doc-independence-policy",
    "certification": "qa-doc-certifications",
}

RESTRICTED = {"qa-doc-partner-comp": "comp", "qa-doc-pricing-framework": "pricing"}


def lookup(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({doc for term, doc in INDEXED.items() if term in lowered})


def answer_one_case(case, documents) -> Transcript:
    """Stand in for one turn of the real harness.

    The shape is what matters, not the intelligence: several tool calls, a decision
    not to call anything, or a call to a different capability entirely - all recorded
    as they happened rather than normalised into one retrieval.
    """
    by_id = {d.id: d for d in documents}
    calls: list[ToolCall] = []
    passages: list[dict] = []

    # A wrong-capability request is routed, and Q&A stays inactive.
    if "create a new client record" in case.query.lower():
        calls.append(
            ToolCall(name=ROUTE, arguments={"capability": "crud"}, result="routed")
        )
        return _transcript(
            case,
            calls,
            passages,
            "That is a record-creation request. Routing it to the CRUD capability; "
            "the knowledge base is not involved.",
        )

    # An ambiguous request is clarified before anything is retrieved.
    if case.expected_behavior == "clarification":
        return _transcript(case, calls, passages, _clarify(case))

    history = " ".join(case.prior_turns) + " " + case.query
    hits = lookup(history)
    calls.append(
        ToolCall(
            name=RETRIEVE,
            arguments={"query": case.query, "principal": case.identity.principal},
            result=hits,
        )
    )

    # Nothing found: reformulate once, then stop rather than guess.
    if not hits:
        calls.append(
            ToolCall(
                name=RETRIEVE,
                arguments={"query": case.query, "reformulated": True},
                result=[],
            )
        )
        return _transcript(
            case,
            calls,
            passages,
            "I found nothing on that in the indexed sources and will not guess. The "
            "library covers engagement letters, proposal language, independence and "
            "certifications.",
        )

    authorized = []
    for doc_id in hits:
        document = by_id.get(doc_id)
        if document is None:
            continue
        clearance = RESTRICTED.get(doc_id)
        if clearance and clearance not in case.identity.clearances:
            continue  # filtered before it can reach the answer
        authorized.append(document)

    if not authorized:
        return _transcript(
            case,
            calls,
            passages,
            "I cannot share that material. It is restricted, and this account does "
            "not hold the required clearance.",
        )

    passages = [
        {
            "id": d.id,
            "source": d.source,
            "score": 1.0,
            "acl": sorted(d.acl),
            "text": d.text,
        }
        for d in authorized
    ]
    answer = " ".join(f"{d.text} [S:{d.id}]" for d in authorized)
    return _transcript(case, calls, passages, answer)


def _clarify(case) -> str:
    return (
        f"Which part of '{case.query}' do you need? I can narrow to the cancellation "
        "terms, the fee arrangement, or the scope-change process."
    )


def _transcript(case, calls, passages, answer) -> Transcript:
    return Transcript(
        case_id=case.id,
        query=case.query,
        principal=case.identity.principal,
        provider="ida-harness-stub",
        # Declared by the emitter, and taken on trust. Claim L2 only when a real
        # model produced the answer: judgeguard grades against whatever is declared,
        # and a false claim buys checks that read world state which does not exist.
        evidence_level=L2,
        tool_calls=calls,
        passages=passages,
        answer=answer,
        meta={"variant": case.variant, "candidate": "ida-harness-stub"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="../../corpus/qa-pod")
    parser.add_argument("--out", default=".transcripts/run.jsonl")
    arguments = parser.parse_args()

    corpus = Corpus.load(arguments.corpus)
    transcripts = [answer_one_case(case, corpus.documents) for case in corpus.cases]
    write_jsonl(Path(arguments.out), transcripts)

    print(f"{len(transcripts)} transcripts -> {arguments.out}")
    print(f"declared evidence: {L2}")
    print("\nGrade them:")
    print(f"  judgeguard grade --corpus {arguments.corpus} --transcripts {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
