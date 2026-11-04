# Variant experiments on a LOCKED method — the copy, control, and measure procedure

How to answer "what if I entered with a stop instead of a limit / a different buffer /
different TTL" **without touching the locked files and without inventing a number**.

The workflow generalises to any parameter or order-type variant. The measured stop-vs-limit
result is at the bottom — read that before offering to test it again.

## 1. Duplicate, never edit

The locked files' sha256 and lock hash cover every module global. So:

```bash
sha256sum xauusd_method_LOCKED_H4.py xauusd_method_LOCKED.py > <scratch>/locked_before.txt
cp xauusd_method_LOCKED_H4.py xauusd_STOP_variant_H4.py
cp xauusd_method_LOCKED.py    xauusd_STOP_variant_H1.py
```

Name the copy by what it tests, and keep it out of the bundle and out of the git repo — it is
an experiment, not part of the frozen system.

## 2. Change exactly ONE line, and prove that is all you changed

`diff locked copy | grep '^[<>]'` and read every changed line out loud to the user. On these
files the whole order-type difference is one guard in `run()`:

```python
# locked (limit): fills on the setup bar itself
if pos is None and pending is not None:
# experiment (stop): the setup bar's close is still BEFORE the entry price,
# so a stop can only fill from the following bar
if pos is None and pending is not None and i > pending["bar"]:
```

Everything else — levels, buffer, cap, SL ratio, TTL, cooldown, exit resolution — must stay
byte-identical, or the comparison is meaningless.

## 3. Re-verify the ORIGINALS before and after

```bash
python xauusd_method_LOCKED_H4.py --verify     # PASS / 346 trades
python xauusd_method_LOCKED.py    --verify     # PASS / 165 trades
diff locked_before.txt locked_after.txt        # must print nothing
```

Run this **before** the experiment as the baseline and **after** as the proof. Say which one is
which — "hash unchanged" is the answer to "did you touch my locked method?".

## 4. Control run, then experiment run, then compare the FILES

```bash
python xauusd_method_LOCKED_H4.py --csv <data> --out <scratch>/ctl.csv
python xauusd_STOP_variant_H4.py  --csv <data> --out <scratch>/stop.csv
sha256sum <scratch>/ctl.csv <scratch>/stop.csv
```

Identical output hashes mean *nothing changed*, and that is a finding — but only after you
explain the mechanism. Two traps when reading these exported CSVs:

- The export is single-column and semicolon-delimited: `Pair;Action;Tanggal Entry;…`.
  `df.entry` raises `AttributeError`. Compare with `df.equals()` on the whole frame instead
  of reaching for columns.
- `import module; inspect.getsource(module.run)` proves the guard actually loaded — do this
  before concluding "the change had no effect", otherwise you are testing the old code.

## 5. Measure the mechanism, do not narrate it

When two variants tie, count the setups that explain it rather than asserting why. The probe
that settled limit-vs-stop on H4 (691 breakout setups on `XAUUSD240.csv` from 2025-05-01):

```
entry already touched by the breakout bar's own range : 679  (98%)
first touched only by the next bar                   :  10
touching neither bar (never filled)                  :   2
```

So price closes past `level ± $3` on almost every breakout bar; a limit fills immediately and a
stop fills at the same price. Report the breakdown, not an opinion.

## Measured result — limit vs stop, both methods

| | trades | WR | PF | net | maxDD |
|---|---|---|---|---|---|
| H4 limit (locked) | 346 | 58.7% | 2.38 | $3,510.48 | −$108 |
| H4 stop (experiment) | 346 | 58.7% | 2.38 | $3,510.48 | −$108 |
| H1 limit (locked) | 165 | 56.4% | 2.15 | $1,480.24 | −$102 |
| H1 stop (experiment) | 165 | 56.4% | 2.15 | $1,480.24 | −$102 |

**Zero trades differ.** The exported CSVs are byte-identical. Do not re-run this expecting a
difference, and do not suggest switching order type as an improvement.

The one caveat to volunteer: on the 679 immediate fills, a real STP order fills at the next
bar's open when price gaps past entry, which bar-data backtests cannot capture — so the live
stop variant can be slightly worse than the tie suggests. Limit is not worse in any scenario
tested.

## Where the real levers are

Same-method parameters that DO move the numbers (sweep them, one at a time, duplicated the
same way): **entry buffer** ($3), **TP cap** ($30), **SL ratio** (0.6), **TTL** (2 bars).
Order type is not one of them.
