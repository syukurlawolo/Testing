# Cara Push ke GitHub

Repo sudah siap di folder ini: **20 file, 10.771 baris, 1 commit**.
Remote sudah terpasang ke `github.com/syukurlawolo/Testing`.
Yang kurang hanya izin akses (token).

---

## Pilihan A — cara termudah (klik dua kali)

1. Buat token dulu kalau belum punya:
   - Buka https://github.com/settings/tokens
   - **Generate new token (classic)**
   - Centang scope **`repo`** (yang paling atas, satu blok penuh)
   - Set masa berlaku, lalu **Generate** dan **copy** token-nya
2. Klik dua kali **`PUSH.bat`**
3. Saat diminta:
   - `Username` → `syukurlawolo`
   - `Password` → **tempel token**, bukan password GitHub

Selesai. Lihat hasilnya di https://github.com/syukurlawolo/Testing

> Git mungkin membuka jendela login browser. Kalau muncul, pilih
> **"Sign in with a code"** atau **"Token"** — itu lebih mudah daripada
> mengetik manual.

---

## Pilihan B — dari Command Prompt

```
cd "C:\Users\Sharing Vision\Documents\OTHER\Testing"
git push -u origin main
```

---

## Pilihan C — pakai SSH (kalau Anda sudah punya SSH key)

```
cd "C:\Users\Sharing Vision\Documents\OTHER\Testing"
git remote set-url origin git@github.com:syukurlawolo/Testing.git
git push -u origin main
```

---

## Kalau muncul error

| Pesan | Artinya | Solusi |
|---|---|---|
| `Authentication failed` | Username/token salah | Ulangi, tempel token dengan benar |
| `Support for password authentication was removed` | Anda mengetik password GitHub | Harus pakai **token**, bukan password |
| `remote: Permission denied` | Token tidak punya scope `repo` | Buat token baru, centang `repo` |
| `Updates were rejected` | Repo sudah berisi commit lain | Kabari saya, jangan `--force` |

---

## Setelah berhasil

Supaya tidak perlu mengetik token lagi di kemudian hari:

```
git config --global credential.helper manager
```

Windows akan menyimpannya di Credential Manager.

---

## Yang sudah saya uji sebelum repo ini diserahkan

Semua lulus, dijalankan dari clone bersih:

| Uji | Hasil |
|---|---|
| H4 `--verify` dari repo | **PASS** — 346 trade, WR 58,7 %, PF 2,38 |
| H1 `--verify` dari repo | **PASS** — 165 trade, WR 56,4 %, PF 2,15 |
| Hash file setelah clone | **identik** (CRLF tidak merusak apa pun) |
| `xauusd_bundle.py --restore` ke folder baru | **9 file terpulihkan** |
| Scan kredensial di dalam bundle | **bersih** — tidak ada token |
| `tg.json` ikut ter-commit? | **tidak** — sudah diblokir `.gitignore` |

---

## Isi repo

```
README.md                    penjelasan lengkap + hasil acuan
LICENSE                      MIT + disclaimer trading
PUSH.bat                     skrip push satu-klik
CARA-PUSH.md                 file ini
.gitignore                   memblokir kredensial & log
.gitattributes               menjaga .bat tetap CRLF

trading/                     SISTEM LENGKAP
  xauusd_bundle.py           peti penyimpan, 9 file ter-embed
  xauusd_method_LOCKED_H4.py aturan H4 — JANGAN DIUBAH
  xauusd_method_LOCKED.py    aturan H1 — JANGAN DIUBAH
  signal_live_h4.py          robot Telegram
  run_signal.bat             kirim sinyal + balas /status
  poll_only.bat              balas /status tiap 5 menit
  register_tasks.bat         daftarkan 2 task Windows
  CEK_STATUS.bat             cek kesehatan
  PANDUAN.md                 panduan bahasa Indonesia
  signal_state.json          memori robot (snapshot)

docs/
  restore-and-boot.md        kontrak pemulihan
  live-deployment.md
  backtest-reproducibility.md

skill/
  SKILL.md                   skill Hermes

data/
  XAUUSD240.csv              data H4 untuk reproduksi backtest
  template-backtest.csv      skema ekspor CSV
```
