"""Candidates: the thing under test.

`TemplateCandidate` composes an answer from retrieved passages with no model call,
which is what makes an L1 run possible offline. It is deliberately naive - it has
no defence against instructions embedded in retrieved text, so the injection pack
fails against it on a clean checkout. That failure is the demo.
"""

from __future__ import annotations

from .contract import Passage

SNIPPET = 240


class TemplateCandidate:
    id = "template"

    def answer(self, query: str, passages: tuple[Passage, ...]) -> str:
        if not passages:
            return "No authorized source was found for this question."
        parts = [f"Answering: {query}", ""]
        for passage in passages:
            parts.append(f"{passage.text[:SNIPPET].strip()} [S:{passage.id}]")
        return "\n".join(parts)
