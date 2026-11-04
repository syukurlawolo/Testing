# Rule questions — "what happens if X and Y at once?"

The user reasons from a mental model of the market, not from the engine, so his hypotheticals
routinely describe two things that cannot co-occur. Answer each one by (a) checking the engine
for the real rule, then (b) running a tiny synthetic-bar simulation, then (c) naming the false
premise — in that order. Reasoning it out in prose is how wrong answers get shipped.

## The engine facts these questions turn on

From `run()` in `xauusd_method_LOCKED_H4.py` (identical in the H1 file):

- **One slot only.** Each bar runs, in this order: exit check on `pos` → fill/expiry on
  `pending` → look for a new breakout. The breakout search is gated by
  `pos is None and pending is None`, so while either exists no new signal can be born.
- **One-bar cooldown after an exit.** `i - last_exit_i > cooldown` with `cooldown=0` means the
  exit bar itself cannot produce a new signal. Two signals on the same bar are impossible.
- **Confirmed by CLOSE, not by touch.** Only a bar that *closes* beyond the level counts;
  a wick through a level that closes back is invisible to the method.
- **Both SL and TP inside one bar resolves to SL** (`if sl_hit and tp_hit → "SL"`). Bars do
  not record which came first, so the conservative branch wins. Do not describe this as
  "whichever happened first".

## Worked example — "level A broken up, then level B also crossed in the same 4h candle"

With the live level grid this is two levels on the SAME side of price, so the second one is not
a reversal — it is the continuation. The first signal's TP is derived from the next level ahead
and capped at $30, so it is banked **before** price ever reaches the second level:

```
break up 3931.48  -> BUY  entry 3934.48  TP 3964.48  SL 3916.48
synthetic bars: lilin1 breakout / lilin2 fill / lilin3 high >= TP
  lilin 1: SINYAL BUY 3934.48 TP 3964.48 SL 3916.48
  lilin 2: order Buy 3934.48 TERISI
  lilin 3: Buy 3934.48 -> TP
```

One signal, finished. A NEW signal in the opposite direction requires price to come back and
**close** through the level from the other side — two separate closes, i.e. at least two bars.

Sanity check that costs one query: count breakouts of level A whose own bar already reaches
level B (`d[(d.pc <= A) & (d.c > A)]` then `.h >= B`). On the H4 history it was **0 of 3** —
the case he imagines essentially never happens on real data.

## How to run the simulation

Re-implement only the four engine rules above (~25 lines) over hand-written `(high, low, close)`
tuples, then print one line per bar. Keep the SL-before-TP tie-break and the cooldown-1 rule in
the toy version or the output will disagree with the locked engine. Show the user the printed
lines verbatim — a table of conclusions invites a re-ask, the trace does not.

## Answering shape

- Lead with whether the scenario can happen at all. "Kedua angka itu di atas harga, jadi itu
  bukan dua sinyal — itu satu perjalanan."
- Then the trace, then the rule in one line per case (a small table: situation → result).
- Then the edge case he did not ask about but must know: the SL/TP tie-break, and that one
  position blocks every new signal.
- Never claim "the robot would take both" — it holds one slot and enforces a cooldown. If a
  hypothetical truly needs two positions, say plainly that it is a DIFFERENT method and has not
  been backtested (same rule as the two-way OCO plan).

## Simulating a rival STYLE ("coba gaya trading buy/sell stop dua arah")

A request to test a different trading style is a measurement job, never an edit job. The locked
file is the benchmark; the rival is a scratch reimplementation. Sequence that produced a
defensible answer:

1. **Read `run()` and copy its semantics verbatim** into the simulator: SL-before-TP tie-break,
   fill checked from the bar AFTER the planning bar, `i - last_exit > cooldown` gating, distance
   capped at `CAP_USD`, `dist > 1.0` minimum, TTL in bars. Do not tidy them up "more fairly" —
   the rival must differ only in the one rule under test, or the comparison measures nothing.
2. **Prove the simulator on mode A first.** Mode A (one slot) must reproduce the locked trade
   count, WR, PF, net and maxDD exactly. Print that match as line one of the findings; until it
   matches, no later number is attributable.
3. **Name the variants precisely, and keep them as separate modes** — they produce different
   money from the same bars:
   - *A* one slot, one direction per breakout (the locked method).
   - *B* both stops placed at every H4 close, **loser cancelled** when one fills (true OCO).
   - *B2* both stops placed, **loser stays live**; if it later fills, close the existing position
     at that opposite entry and book a `FLIP` leg so the cost is visible instead of silently
     netted into the winners.
4. **Loop a list of start dates**, not one: the locked start, ~3 later ones, and the user's
   current week. One window cannot separate an edge from a regime, and the short recent window is
   the one he actually trades.
5. **Report the verdict as scale when that is what the numbers say.** More trades, more net, but
   proportionally larger drawdown, lower win rate and near-identical net/DD means the same edge at
   a bigger size — tell him to equalise lot size and re-check before believing it is better. Then
   state what the variant did in the specific days he cares about; being worse in his current
   window is the decisive fact, not the long-run total.
6. **Close with the lock proof**: sha256 of both `*_LOCKED*.py` before and after, printed as
   IDENTIK, plus the statement that nothing was written to disk.
7. **A simulation the user calls "hanya simulasi" leaves no ENGINE artefacts — but the moment he
   says "ditemplate backtesting seperti biasa", the CSV is mandatory and part of the answer.**
   The two requests look alike and are not: "jangan disimpan" means do not touch `trading/`, the
   locked files, or the bundle — it does not mean withhold the deliverable. Read which one he
   asked for before deciding whether a file exists at the end.
8. **A template-format CSV is a format contract, reproduce it exactly**: separator `;`, CRLF line
   endings, dates `DD-Mmm-YY HH:MM`, and the exact header
   `Pair;Action;Tanggal Entry;Tanggal Exit;Entry;TP;SL;Keterangan` with `Keterangan` holding the
   outcome (`TP` / `SL` / `FLIP`). Write it OUTSIDE `trading/` (a `Documents/OTHER/...` folder plus
   a copy in `Downloads` he can open), then READ IT BACK with `csv`/pandas and re-derive the counts
   from the file itself. The row count, TP/SL split and win rate in the reply must come from the
   written file, not from the in-memory dict the run produced.
8. **Test the rival against the move that made him ask.** He does not request a style change out of
   curiosity; he asks because the live window went against him, so a variant that only wins over
   the full period is not an answer. Recomputed on the recent window, the two-way style lost 2–3×
   what the locked method lost on the same bars — lead with that, then give the long-run total.
   "Lebih besar, bukan lebih baik" is the verdict whenever net and drawdown rise together and
   net/DD stays flat.

Answering shape he reacted well to: one table of the three variants over the full period, a
smaller table across start dates, then "kenapa lebih banyak trade tapi win rate turun", then a
verdict paragraph that refuses to call the bigger number better without equalising risk.

## Two-way hedge: the win rate is real but the PnL is not withdrawable

When both stops stay live (hedge mode), the trade file and the money stop being the same thing.
Before writing the file or the table, run this audit and put its result in the answer:

1. **Count concurrent opposite pairs.** Sort the trade list by entry time and pair each BUY with a
   SELL that is open on the same bars; matched pairs are netting accounts and the broker holds
   **zero** position while both are marked open. Two orders filled on the same bar timestamp is the
   fingerprint — quote the two adjacent rows to prove the hedge actually happened.
2. **Re-price the matched pairs.** Total PnL should be recomputed as the price difference between
   the two entries at close time, not as `TP distance × count`; the gap is often an order of
   magnitude (a $21k equity-curve total against a few hundred dollars of realisable balance).
3. **Say plainly that the template overstates it.** A per-row simulator (Excel, or the user's own
   checker) treats every row as an independent trade, which is valid for the one-slot method and
   inflated for hedge mode. Never hand over a 70% win rate without that sentence in the same reply.
4. **Expect the two-way scenarios to be identical until the loser can fill.** Hedge and OCO return
   byte-identical results when the loser's pending order sits far enough away that it never fills
   in its TTL — the difference only appears in the tails. If the numbers match to the trade, do not
   hunt for a bug: report the identity and show the window where a loser DID fill.
5. **Identify WHY they are identical before explaining it.** Instrument the walk with a counter of
   "bars where a pending order of the opposite side to an open position still exists" and print it.
   The locked engine searches for a breakout only when `pos is None and pending is None`, so a bar
   can only break ONE side and planning emits ONE order — the opposite pending is **0 for the whole
   history**. Hedge vs OCO is therefore a rule about a state the method never reaches. That
   measurement, not a story, is the answer; add that the pair only matters for a genuinely paired
   strategy, which is a different method.

## Entry-side and fill-bar invariants — validate these before quoting ANY variant number

A hand-written variant simulator can produce a spectacular number from a logic error that the
locked-engine reproduction does not catch, because reproduction only exercises the *unchanged*
path. Two invariants must be asserted on the variant's own trade list, and both must read **0
violations** or the result is discarded, not caveated:

- **Fill-bar truth.** For every trade, the bar stamped `entry_time` must actually contain the entry:
  `high >= entry` for a Buy, `low <= entry` for a Sell. Recording the first bar AFTER the order was
  placed instead of the bar that touched it silently invents fills.
- **Correct side.** Compare each entry with the previous bar's close: a Buy stop must sit ABOVE it,
  a Sell stop BELOW it. A stop placed on the wrong side of current price "fills" on the very next
  bar regardless of direction, which manufactures a huge number of winners out of nothing.

Both are one loop over the trade list (~8 lines). Print the violation count next to the result, and
re-print the locked-engine reproduction match in the same block — a variant is only trustworthy
when the unchanged path still reproduces exactly AND the changed path satisfies both invariants.

**A number that flips by an order of magnitude is the signal to audit, not to explain.** When a
variant's win rate and net collapse (or explode) versus an earlier run of the same idea, the prior
run is suspect first — walk one concrete trade from the FIRST rows of the file against the raw CSV
bars and print `high`/`low` next to the entry. If the recorded fill bar does not contain the entry,
withdraw the figure, delete the deliverable file, and say plainly which number was wrong and why;
then re-run and report only the validated set. Do not present the old and new figures side by side
as if both were measurements — one of them was not.
