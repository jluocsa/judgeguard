# Two lanes

A deterministic assertion and a judge score are different kinds of claim. Putting them
in one column, with one threshold, destroys both.

## The lanes

| | Deterministic lane | Judge lane |
|---|---|---|
| Produces | `CheckResult` — pass / fail / ungradable | `JudgeScore` — a number and written reasoning |
| Repeatable | yes | no |
| Gates CI | **yes, exclusively** | **never** |
| Answers | did the system do the thing | was the answer any good |

## Why judges must not gate

A judge score varies run to run on identical input. Wire it to an exit code and you
get a build that fails on sampling noise. Teams respond the way anyone would: they
raise the threshold until it stops firing, and then it is decoration. A gate that
never fires is worse than no gate, because it occupies the slot where a real one would
have gone.

The failure mode is not that judges are bad. It is that a non-deterministic signal
cannot carry a binary decision without either producing false failures or being tuned
into uselessness.

## Why the split makes judges more useful, not less

Once a judge stops gating, three things become possible that were not before.

- **Agreement becomes countable.** With a verdict beside every score, you can measure
  how often the judge agrees with ground truth instead of asserting that it does.
- **Judges can be swapped.** Changing judge model is a reporting change, not a release
  risk, so you can actually evaluate your evaluator.
- **Scores can be granular.** A number nobody has to defend as a gate can be a 0-10
  with reasoning, rather than a threshold argument.

## How the split is enforced

Not by convention. `gate.exit_code()` takes `CheckResult` and raises `TypeError` on
anything else. There is no flag, no configuration key and no override that lets a
`JudgeScore` reach it, and `tests/test_judge_cannot_gate.py` asserts this every run.

A rule that lives in a code review is a rule that survives until the week everyone is
busy. This one is in the type signature.

## What still belongs in code

A judged lane grades transcripts, so it can only grade what reached one. Authorization,
leakage and injection resistance are outcome assertions about world state — they stay
in the deterministic lane permanently, and no evaluation platform changes that.
