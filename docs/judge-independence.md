# Judge independence

judgeguard refuses to start when the judge deployment and the candidate deployment are
the same.

```console
$ judgeguard gate
✗ judge deployment == candidate deployment (gpt-4o@eastus)
  A judge cannot independently evaluate itself.
  Set JUDGEGUARD_JUDGE_DEPLOYMENT, or pass --allow-self-judge to override
  (scores will be marked SELF and excluded from agreement statistics).
```

## Why refuse rather than warn

Models prefer their own output. A judge scoring its own generations is not measuring
quality, it is measuring similarity to what it would have written — and the resulting
number is indistinguishable in a report from one produced by an independent check.

A warning gets scrolled past. The number survives into a slide, and by then nobody
remembers it was self-scored. Refusing to start is the only intervention that reliably
happens before the number exists.

## The override

`--allow-self-judge` exists, because sometimes one deployment is all you have and a
noisy signal beats none. When used:

- every score is marked `SELF`
- `SELF` scores are excluded from agreement statistics
- the marking is in the transcript, so it survives export

The point is not to prevent self-judging. It is to prevent self-judging that is
invisible three steps downstream.

## Configuration

| Variable | Purpose |
|---|---|
| `JUDGEGUARD_CANDIDATE_DEPLOYMENT` | the model under test |
| `JUDGEGUARD_JUDGE_DEPLOYMENT` | the model doing the scoring |

`judgeguard doctor` checks these before a run costs anything.

## If you can only change one thing

Change this one. Pointing the judge at a different deployment is a single
configuration field. It is almost always the highest-value change available in an
evaluation setup, and it costs a quota request rather than a project.
