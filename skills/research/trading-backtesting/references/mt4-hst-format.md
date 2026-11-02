# MT4 .hst history format

## Locating the data
- Install folder: `C:\Program Files (x86)\<Broker> MT4\` (`terminal.exe`) — NOT where history lives.
- Data folder: `%APPDATA%\MetaQuotes\Terminal\<32-hex-hash>\`
  - `origin.txt` = install path (UTF-16LE).
  - `history\<server-name>\<SYMBOL><period>.hst` — period in minutes: 1=M1, 5, 15, 30, 60=H1, 240=H4, 1440=D1.
  - `history\default\` holds pre-login demo symbols only; look for a `<server>` subfolder for real account data.
- Resolve a Start-Menu shortcut target with PowerShell via a `.ps1` file:
  `(New-Object -ComObject WScript.Shell).CreateShortcut('....lnk').TargetPath`
  (run as `-File`, not inline `-Command` — bash eats `$var` in double quotes).

## Binary layout (build 600+ / version 401)
Header = 148 bytes:

| offset | field | type |
|---|---|---|
| 0 | version | int32 (401) |
| 68 | symbol | char[12] |
| 80 | period | int32 (minutes) |
| 84 | digits | int32 |
| 88 | timesign | int32 |

Record = 60 bytes:

| offset | field | type |
|---|---|---|
| 0 | time | int32 (unix) |
| 4 | (padding) | 4 bytes |
| 8 | open | double |
| 16 | high | double |
| 24 | low | double |
| 32 | close | double |
| 40 | volume | double/int64 |
| 48 | spread | int32 |
| 52 | real_volume | int64 |

- **HIGH comes before LOW** (MqlRates order), unlike the legacy RateInfo order.
- The 4-byte padding after `time` is what misleads a naive parser into garbage
  doubles — offsets 8/16/24/32 are the four prices.
- Confirm record size empirically: `(filesize - 148) % 60 == 0` for build 600+;
  legacy files use 44-byte records (then prices are at 4/12/20/28 with low
  before high).
- Timestamps are UTC: `datetime.datetime.fromtimestamp(ts, datetime.UTC)`.
