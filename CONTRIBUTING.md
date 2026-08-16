# Contributing

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest
```

## The three invariants

Changes that weaken any of these will not be merged, regardless of what they enable.

1. **The judge lane cannot set the exit code.** `gate.exit_code()` accepts
   `CheckResult` only. No flag relaxes it. — `tests/test_judge_cannot_gate.py`
2. **A model may not silently evaluate itself.** Sharing a deployment refuses to
   start; the override marks every score `SELF`. — `tests/test_independence_guard.py`
3. **The deterministic lane makes no network calls and needs no key.** A clean
   checkout must reach a report offline. — `tests/test_offline_no_egress.py`

If a feature seems to require breaking one, open an issue before writing code. The
answer is usually a different design, occasionally a new invariant, and never a
quiet exception.

## Adding a check

Checks live in `src/judgeguard/lanes/checks/`. Each declares the evidence level it
needs:

```python
@check("my_check", L1)
def my_check(transcript, case) -> CheckResult:
    ...
```

Declaring a level you do not need makes the check silently skip. Declaring one lower
than you need makes it pass on evidence it cannot actually read, which is the failure
mode this whole project exists to prevent. Pick carefully.

## Adding an adapter

See [docs/writing-adapters.md](docs/writing-adapters.md). Every adapter must pass
`tests/conformance` unchanged.

## Corpus contributions

Only content that can be redistributed. Every document carries a `license` field, and
`corpus/README.md` records provenance. No customer data, no scraped content behind
terms that forbid it, and no material whose rights you have not checked.
