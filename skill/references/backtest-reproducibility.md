# Backtest reproducibility & the HTTP bridge

Depth for two related traps: persisting strategy *claims* without the machinery that made
them, and exposing a frozen strategy to an external orchestrator.

## 1. The core rule

**A frozen strategy is only as trustworthy as the engine that can re-derive it.** Storing
parameters + a results table without a permanently-available backtester produces a file that
*looks* authoritative and cannot be checked. Anyone (including a later you) will quote it.

### What went wrong (mechanism, not narrative)

- The backtest scripts lived in `~/AppData/Local/hermes/cache/scratch/`, which is pruned
after 24h idle. Every script that produced the frozen numbers was deleted.
- The strategy JSON, its checksum lock, and a verification script survived — but the
  verification script imported the backtester from scratch. So a "verified" strategy broke
  the moment the temp files aged out.
- The rewritten backtester disagreed with the stored reference (169/55.6%/2.08 vs
  173/40.5%/1.13). With the original engine gone, there was no way to tell which was right.
- The checksum lock did **not** help: it hashes parameters, not results. Parameters were
  never the thing that was wrong.

### Rules that follow

- **Never let a strategy depend on anything under a scratch/temp/cache directory.** Put the
  backtester beside the strategy (`backtest_engine.py`) and import it from there.
- **Hash the results, not only the parameters.** The lock should cover the reproduced stats
  so a results drift trips it, not just a parameter edit.
- **When a reproduce-check fails, the failure IS the finding.** Report it plainly. Patching
  the reference block to match the current engine silently promotes an unknown into a claim.
  (This is the failure mode to avoid: editing the yardstick to agree with the measurement.)
- **Re-derive with a sweep, not a single guess.** A wrong engine can still land on a
  plausible trade count by accident. Sweeping cap × RR showed the target WR/PF was
  unreachable at any setting, which proved it was a data/engine mismatch rather than a
  near-miss. Always vary at least two dimensions before concluding "close enough".
- **Report trade-count agreement as insufficient evidence.** Matching `n` while WR/PF differ
  wildly means the entry generation is similar and the exit resolution differs — usually the
  intrabar TP-vs-SL tie-break or the pending-order fill rule.

### Re-derivation procedure when numbers must be re-established

1. Run `python verify_frozen.py`; record the actual reproduced stats verbatim.
2. Sweep the two parameters that dominate outcome shape (cap × RR) and keep the full table —
   it is the evidence that the target is or is not reachable.
3. If unreachable, stop and tell the user the recorded figure is wrong. Do not pick the
   closest result and present it as confirmation.
4. Only after the engine is trusted: replace `backtest_reference` in the frozen JSON, delete
   `strategy.lock`, re-run to re-lock, and state the new figures — including if worse.

### Deleted script? It is almost certainly recoverable from session history

Scratch pruning deletes files, not the conversation that wrote them. Every `write_file`
call stores its full `content` argument in the session DB, so a pruned script is
byte-identical recoverable — do this **before** telling the user the work is lost or
re-deriving anything by hand.

```python
import sqlite3, json
con = sqlite3.connect(r'C:\Users\Sharing Vision\AppData\Local\hermes\state.db')
cur = con.cursor()
rows = cur.execute("SELECT id, tool_calls FROM messages "
                   "WHERE tool_calls LIKE '%<script>.py%' AND tool_calls LIKE '%write_file%'").fetchall()
for rid, tc in rows:
    for c in json.loads(tc):
        if c['function']['name'] == 'write_file':
            a = json.loads(c['function']['arguments'])
            if a['path'].endswith('<script>.py'):
                open(a['path'], 'w', encoding='utf-8', newline='').write(a['content'])
```

Rules:

- **Recover dependencies too.** A restored script that `from bt2 import ...` still fails;
  grep session history for each imported local module and restore those first. Check the
  import list, not just the file the user named.
- **Take the LATEST matching `write_file`, not the first.** A script patched later has
  several writes to the same path; restoring an early one silently reverts bug fixes.
- **Verify by size and by re-running.** Compare restored byte count against the tool
  result's `bytes_written`, then execute it and confirm it still prints the numbers it
  printed originally.
- **A pruned script that still runs does not prove the stored reference was right — but it
  reopens the question.** If the recovered engine reproduces the old figures while your
  replacement engine does not, the disagreement was a logic difference between the two
  engines, not a fabricated number. Downgrade every "could not be reproduced" conclusion to
  "not reproduced by MY engine" and go find the divergent rule (see the ambiguity table
  below). Do not leave the stronger claim standing.

## 2. Exit-resolution ambiguities to pin down

When reproducing a bar-by-bar backtester, these change WR by tens of points while leaving
strategy logic identical. Fix each explicitly in the engine and in the verification:

| Ambiguity | Required convention here |
|---|---|
| Bar hits both TP and SL | Resolve as **SL** (conservative) |
| Pending order fill | Fill against bar high/low, not close |
| Breakout trigger | Previous **close** vs current **close** crossing the level |
| Pending expiry | Age counter compares to TTL with `>`, not `>=` |
| Level selection | Nearest level strictly above/below the *entry*, not the breakout level |

The `>` vs `>=` on TTL alone moved trade count 169→173 in testing — a one-character
ambiguity with a large result delta. Pin it in the skill, not in your head.

## 3. HTTP bridge for n8n / external orchestrators

`signal_service.py` exposes the frozen strategy over HTTP. Start it with
`python signal_service.py --port 8787` (binds 127.0.0.1 by default).

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness, strategy id, frozen checksum, csv existence |
| `GET /strategy` | the frozen parameter block (read-only) |
| `GET /status` | open position, pending order, running stats |
| `GET /signal` | scan using local CSV, return JSON |
| `POST /webhook/bar` | accept closed bar(s), append, scan, return signal |

### Architecture for MT4 → n8n → Python → execution

```
MT4 (EA exports CSV, or file trigger)
  → n8n cron hourly on H1 close (+ File Trigger as backup)
  → POST /webhook/bar
  → Python: frozen rules only
  → JSON {action, entry, tp, sl, tp_distance, rr}
  → n8n fans out: Telegram alert + MT4 order (EA / ZeroMQ)
```

**Never let n8n compute entry/TP/SL.** If the orchestrator recalculates prices you get two
sources of truth and they will diverge. n8n only moves bars in and signals out.

### Pitfalls found while building it

- **`--config <path>` plus a separate state file is mandatory for testing.** Without it the
  service reads the production CSV from `config.json` and your truncated test file is never
  touched — tests pass while proving nothing. Point `STATE_FILE` at the sandbox too, or the
  test mutates real position state.
- **`add_bars` must never write a header row.** If a header gets appended, the date column
  parses as float and `date + ' ' + time` raises `TypeError: can only concatenate str (not
  "float") to str` — which kills the HTTP handler and returns a bare
  `RemoteDisconnected` to the client with no diagnostic.
- **Harden `load_bars` against all of it:** drop a header row if `date` starts with
  `date`/`tanggal`, `dropna`, coerce numerics with `errors='coerce'`, dedupe on timestamp.
  MT4 exports and pandas-written files differ in header presence and dtype.
- **Wrap the scan in try/except inside the POST handler.** A single malformed bar otherwise
  takes down the request with an opaque connection close instead of a 500 body.
- **numpy scalar types are not JSON-serialisable.** Cast to `float()`/`int()` before building
  a payload, on both the client and the service side.
- Bind beyond localhost only with `API_KEY` set; the service then requires header
  `X-API-Key`. It warns (does not refuse) when exposing without a key.
