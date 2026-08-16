"""Provider-neutral retrieval and generation contract.

Every adapter implements `Retriever`. The conformance suite in `tests/conformance`
runs unchanged against all of them, which is what makes a provider swap a
comparison rather than a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Identity:
    """The caller a retrieval is performed on behalf of."""

    principal: str
    clearances: frozenset[str] = field(default_factory=frozenset)

    def may_read(self, acl: frozenset[str]) -> bool:
        # An empty ACL means public. Otherwise the identity needs at least one grant.
        return not acl or bool(acl & self.clearances)


@dataclass(frozen=True)
class Passage:
    id: str
    text: str
    source: str
    score: float = 0.0
    acl: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RetrievalResult:
    provider: str
    passages: tuple[Passage, ...] = ()
    latency_ms: float = 0.0
    error: str | None = None


@runtime_checkable
class Retriever(Protocol):
    """A retrieval backend.

    `evidence_level` is the ceiling this adapter can support, not an aspiration:
    an adapter returning canned passages must declare L0 so checks that need real
    world state report `ungradable` instead of a misleading pass.
    """

    name: str
    evidence_level: str

    def retrieve(
        self, query: str, *, identity: Identity, top_k: int = 5
    ) -> RetrievalResult: ...


@runtime_checkable
class Candidate(Protocol):
    """The thing under test: turns retrieved passages into an answer."""

    id: str

    def answer(self, query: str, passages: tuple[Passage, ...]) -> str: ...
