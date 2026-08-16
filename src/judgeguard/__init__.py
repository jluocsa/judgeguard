from .baseline import Delta, compare, load, save, snapshot
from .candidates import TemplateCandidate
from .contract import Candidate, Identity, Passage, RetrievalResult, Retriever
from .corpus import Case, Corpus, Document
from .gate import EXIT_OK, EXIT_PRECONDITION_FAILED, EXIT_VERDICT_FAILED, exit_code
from .independence import JudgeIndependenceError, assert_independent
from .runner import CaseOutcome, RunResult, run
from .transcript import L0, L1, L2, ToolCall, Transcript

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "Case",
    "CaseOutcome",
    "Corpus",
    "Delta",
    "Document",
    "EXIT_OK",
    "EXIT_PRECONDITION_FAILED",
    "EXIT_VERDICT_FAILED",
    "Identity",
    "JudgeIndependenceError",
    "L0",
    "L1",
    "L2",
    "Passage",
    "RetrievalResult",
    "Retriever",
    "RunResult",
    "TemplateCandidate",
    "ToolCall",
    "Transcript",
    "__version__",
    "assert_independent",
    "compare",
    "exit_code",
    "load",
    "run",
    "save",
    "snapshot",
]
