#!/usr/bin/env python3
"""Parse an MT4 .hst history file to CSV + print summary stats.

Usage:
    python parse_mt4_hst.py <input.hst> <output.csv>

Handles build-600+ 60-byte records (version 401) and legacy 44-byte records.
"""
import struct, datetime, csv, sys, statistics

def parse(path):
    data = open(path, 'rb').read()
    version = struct.unpack_from('<i', data, 0)[0]
    symbol = data[68:80].split(b'\0')[0].decode('ascii', 'replace')
    period = struct.unpack_from('<i', data, 80)[0]
    digits = struct.unpack_from('<i', data, 84)[0]
    rec_size = 60 if (len(data) - 148) % 60 == 0 else 44
    start = 148
    n = (len(data) - start) // rec_size
    bars = []
    for i in range(n):
        rec = data[start + i * rec_size : start + (i + 1) * rec_size]
        t = struct.unpack_from('<i', rec, 0)[0]
        o = struct.unpack_from('<d', rec, 8)[0]
        h = struct.unpack_from('<d', rec, 16)[0]
        l = struct.unpack_from('<d', rec, 24)[0]
        c = struct.unpack_from('<d', rec, 32)[0]
        bars.append((datetime.datetime.fromtimestamp(t, datetime.UTC), o, h, l, c))
    return symbol, period, digits, bars

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    symbol, period, digits, bars = parse(src)
    with open(dst, 'w', newline='') as f:
        w = csv.writer(f)
        for dt, o, h, l, c in bars:
            w.writerow([dt.strftime('%Y.%m.%d'), dt.strftime('%H:%M'),
                        round(o, digits), round(h, digits),
                        round(l, digits), round(c, digits)])
    closes = [b[4] for b in bars]
    print(f"{symbol} period={period} digits={digits} bars={len(bars)}")
    print(f"range {bars[0][0]} -> {bars[-1][0]}")
    print(f"close min {min(closes)} max {max(closes)} mean {statistics.mean(closes):.2f}")
    print(f"wrote {dst}")
