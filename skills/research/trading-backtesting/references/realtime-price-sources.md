# Real-time / fresh gold price sources — what works, and what must not be used

Use when the user says the data is frozen ("semuanya terakhir 2 nov"), asks where to get
fresh gold prices, or names TradingView / an "open source API" as the source he wants.

## Diagnose a frozen MT4 file before shopping for a new provider

An `.hst` that stops updating is almost never a broken feed. **MT4 only writes the history
file for the timeframe whose chart is open**, so a stale `XAUUSD240.hst` next to a fresh
`XAUUSD60.hst` means nobody had the H4 chart open — not that the network died.

- Compare mtimes across the `.hst` family (`XAUUSD5/15/30/60/240/1440.hst`). One fresh file
  and one stale file = chart-open problem.
- Confirm which charts are actually open by grep-ing the profile:
  `grep -ao 'symbol=[A-Za-z0-9_.]*\s*period=[0-9]*' profiles/**/*.chr`. A `period=60` for
  XAUUSD and no `period=240` explains the freeze exactly.
- The fix costs nothing: open XAUUSD, switch to H4, leave it open. Report the cause
  ("chart H4 tidak dibuka") instead of proposing a paid data source.

## Source matrix (tested from this machine)

| Source | Endpoint | Gives | Status |
|---|---|---|---|
| gold-api.com | `api.gold-api.com/price/XAU` | spot XAUUSD, ~1 s `updatedAt` | works, no key for the price; `/history/XAU` demands `x-api-key` |
| TradingView scanner | `scanner.tradingview.com/symbol?symbol=OANDA%3AXAUUSD&fields=close,open,high,low,change,update_mode` | spot XAUUSD, `update_mode: streaming` | works, no key |
| Yahoo chart | `query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1h&range=60d` | **futures** OHLC history, ~1418 bars | works, `User-Agent` header required |

Do not report dead ones as options: `XAUUSD=X` on Yahoo is 404, TradingView's history feed
(`symbol-search.tradingview.com`) returns 403, Stooq returns a JavaScript wall, TwelveData
needs a key. A price-only API is NOT a replacement for a bar history — say which one you have.

## GC=F must never be used as XAUUSD

Futures and the broker's spot quote are different instruments and the spread is neither small
nor constant. Measured over 280 overlapping H4 bars: **mean |difference| ≈ $32.68**, sometimes
$19, sometimes $40, with the best UTC offset at 0. Feeding GC=F into the breakout levels shifts
every entry/TP/SL by that much and silently produces signals at the wrong price.

Scope the rule to pricing, not to the backtest: GC=F is fine when **normalised** — a backtest
run on both series to establish that the method's edge is instrument-shape, not a specific
price level. It is not fine for anything that emits a number the user will trade at.

## Feeding live data into a robot without lying about it

Layer it, and name the layers so a failure is attributable:

1. **MT4 as the price source** (after the chart-open fix) — zero drift, the user's own broker.
2. **Spot API as an alarm, not a source** — poll gold-api.com every few minutes; if it has moved
   more than ~$10 from the last bar close in MT4, warn that MT4 is behind. Never substitute the
   API price into an entry/TP/SL.
3. **A second spot API as cross-check** — two independent spot quotes agreeing is evidence; a
   futures quote agreeing is a coincidence of the day's basis.

If the user's real problem is a machine that sleeps or gets locked, no API fixes it — say
plainly that only a VPS (or a machine that stays awake) keeps a bot live, and keep that
conversation separate from the data-source one.

## Fetch hygiene

- Pipe `curl` output to a FILE, not into `python -c json.load(sys.stdin)` inside a `terminal`
  call: the tool truncates long output mid-JSON and the parse fails with `Expecting ',' delimiter`
  at a byte offset nowhere near the real problem. `curl -o <scratch>/x.json` then read the file.
- Reconstructing H4 from 1h bars: `floor('4h')` on UTC timestamps, then
  first open / max high / min low / last close per bucket, and drop the bucket that is still
  forming (`ts < now.floor('4h')`) or its half-bar close looks like a spike.
