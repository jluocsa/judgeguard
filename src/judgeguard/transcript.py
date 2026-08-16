"""The gate-3 row: the full record of one case, not just its score.

A score is a number you cannot re-examine. A transcript is the prompt, every tool
call with its arguments, every tool result, the final answer and the deterministic
verdict beside them. Everything else in judgeguard reads from this.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

L0 = "L0"
L1 = "L1"
L2 = "L2"

EVIDENCE_LEVELS = (L0, L1, L2)

EVIDENCE_LEVEL_MEANING = {
    L0: "tools mocked, results canned - wiring evidence only",
    L1: "retrieval real, generation mocked",
    L2: "full agent run under a real model",
}


def min_evidence_level(levels: Iterable[str]) -> str:
    seen = [lvl for lvl in levels if lvl in EVIDENCE_LEVELS]
    if not seen:
        return L0
    return min(seen, key=EVIDENCE_LEVELS.index)


def meets(actual: str, required: str) -> bool:
    return EVIDENCE_LEVELS.index(actual) >= EVIDENCE_LEVELS.index(required)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None


@dataclass
class Transcript:
    case_id: str
    query: str
    principal: str
    provider: str
    evidence_level: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    passages: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    latency_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Transcript":
        calls = [ToolCall(**c) for c in raw.get("tool_calls", [])]
        return cls(**{**raw, "tool_calls": calls})


def write_jsonl(path: Path, transcripts: Iterable[Transcript]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for transcript in transcripts:
            handle.write(json.dumps(transcript.to_dict(), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterator[Transcript]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield Transcript.from_dict(json.loads(line))
