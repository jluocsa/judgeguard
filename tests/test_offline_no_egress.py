"""Invariant 3: the deterministic lane makes no network calls.

`uvx judgeguard gate` has to reach a report on a clean machine with no key and no
connectivity, or nobody ever sees the report.
"""

from __future__ import annotations

import socket

import pytest

from judgeguard.adapters import Bm25Retriever
from judgeguard.candidates import TemplateCandidate
from judgeguard.corpus import Corpus
from judgeguard.runner import run


@pytest.fixture
def no_egress(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the deterministic lane attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_offline_run_produces_a_verdict(no_egress):
    corpus = Corpus.load("corpus")
    result = run(corpus, Bm25Retriever(corpus.documents), TemplateCandidate())
    assert result.outcomes
    assert result.all_checks


def test_package_imports_no_sdk():
    import sys

    import judgeguard  # noqa: F401

    forbidden = {"openai", "azure.identity", "azure.search.documents"}
    assert not forbidden & set(sys.modules)
