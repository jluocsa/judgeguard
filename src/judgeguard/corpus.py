"""Corpus loading: documents, cases, and the clearance taxonomy.

A case declares the identity it runs as, the sources it expects, the sources it
must never surface, and the phrasing variant it represents. That last field exists
because an evaluation set that differs systematically from production phrasing
reports on inputs the system will not receive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Identity

VARIANTS = ("keyword", "natural", "prefixed")

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
