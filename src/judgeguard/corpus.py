"""Corpus loading: documents, cases, and the clearance taxonomy.

A case declares the identity it runs as, the sources it expects, the sources it
must never surface, and the phrasing variant it represents. That last field exists
because an evaluation set that differs systematically from production phrasing
reports on inputs the system will not receive.

`expected_answer` is separate from `expected_sources` and is not interchangeable
with it. Expected sources are document identifiers and answer "did retrieval reach
the right material"; the expected answer is reference text and answers "does the
response say what a correct response says". Reference-scored evaluators need the
latter, and a case that omits it is not gradable on completeness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Identity

VARIANTS = ("keyword", "natural", "prefixed")

# The end behaviour a case expects. A case that does not say which of these it wants
# is not gradable: "answered nothing" and "correctly declined" are the same retrieval
# transcript, and only the declared expectation tells them apart.
ANSWER = "answer"
NO_RESULT = "no_result"
REFUSAL = "refusal"
CLARIFICATION = "clarification"
BEHAVIOURS = (ANSWER, NO_RESULT, REFUSAL, CLARIFICATION)

BUNDLED = Path(__file__).parent / "bundled_corpus"


def resolve(path: str | Path) -> Path:
    """Fall back to the packaged demo corpus so a zero-install run works anywhere."""
    path = Path(path)
    if path.exists():
        return path
    if BUNDLED.exists():
        return BUNDLED
    raise FileNotFoundError(
        f"no corpus at {path}, and no bundled corpus in this install. "
        "Pass --corpus, or clone the repository for the demo corpus."
    )


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    source: str
    acl: frozenset[str] = field(default_factory=frozenset)
    license: str = "unknown"


@dataclass(frozen=True)
class Case:
    id: str
    query: str
    identity: Identity
    expected_sources: tuple[str, ...] = ()
    forbidden_sources: tuple[str, ...] = ()
    expected_answer: str | None = None
    expected_behavior: str | None = None
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    prior_turns: tuple[str, ...] = ()
    injection_marker: str | None = None
    variant: str = "natural"


@dataclass(frozen=True)
class Corpus:
    root: Path
    documents: tuple[Document, ...]
    cases: tuple[Case, ...]

    @classmethod
    def load(cls, root: str | Path) -> "Corpus":
        root = resolve(root)
        docs_path = root / "documents.jsonl"
        cases_path = root / "cases.jsonl"
        for path in (docs_path, cases_path):
            if not path.exists():
                raise FileNotFoundError(f"corpus is missing {path}")

        documents = tuple(
            Document(
                id=raw["id"],
                text=raw["text"],
                source=raw.get("source", raw["id"]),
                acl=frozenset(raw.get("acl") or ()),
                license=raw.get("license", "unknown"),
            )
            for raw in _read_jsonl(docs_path)
        )
        cases = tuple(
            Case(
                id=raw["id"],
                query=raw["query"],
                identity=Identity(
                    principal=raw.get("principal", "anonymous"),
                    clearances=frozenset(raw.get("clearances") or ()),
                ),
                expected_sources=tuple(raw.get("expected_sources") or ()),
                forbidden_sources=tuple(raw.get("forbidden_sources") or ()),
                expected_answer=raw.get("expected_answer") or None,
                expected_behavior=_behaviour(raw, cases_path),
                expected_tools=tuple(raw.get("expected_tools") or ()),
                forbidden_tools=tuple(raw.get("forbidden_tools") or ()),
                prior_turns=tuple(raw.get("prior_turns") or ()),
                injection_marker=raw.get("injection_marker"),
                variant=raw.get("variant", "natural"),
            )
            for raw in _read_jsonl(cases_path)
        )
        return cls(root=root, documents=documents, cases=cases)

    def filter(self, *, variant: str | None = None) -> tuple[Case, ...]:
        if variant is None:
            return self.cases
        return tuple(c for c in self.cases if c.variant == variant)


def _behaviour(raw: dict, path: Path) -> str | None:
    """Reject an unknown end behaviour loudly.

    A typo here would otherwise disable the check silently, and a case whose
    expectation never runs is indistinguishable from a case that passes.
    """
    declared = raw.get("expected_behavior")
    if declared is None:
        return None
    if declared not in BEHAVIOURS:
        raise ValueError(
            f"{path}: case {raw.get('id')!r} declares expected_behavior "
            f"{declared!r}; known: {', '.join(BEHAVIOURS)}"
        )
    return declared


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc
    return rows
