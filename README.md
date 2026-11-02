# XAUUSD S/R Breakout — H4 Locked Method + Telegram Signal Robot

Sistem trading XAUUSD yang **dibekukan**. Aturan trading, hasil backtest, dan
cara boot semuanya dikunci. Instalasi baru **wajib** mereproduksi hasil yang
identik — bukan mendekati, tapi sama persis.

> **Aturan emas:** jangan pernah menebak ulang, men-tuning ulang, atau
> "memperbaiki" metode ini. Kalau ada yang berbeda dari angka acuan di bawah,
> yang salah adalah file Anda — pulihkan dari bundle.

---

## Daftar isi

- [Hasil acuan (harus cocok persis)](#hasil-acuan-harus-cocok-persis)
- [Struktur repo](#struktur-repo)
- [Cara pakai di komputer baru](#cara-pakai-di-komputer-baru)
- [Cara pakai sehari-hari](#cara-pakai-sehari-hari)
- [Integritas & hash](#integritas--hash)
- [Perangkap yang sudah pernah menggigit](#perangkap-yang-sudah-pernah-menggigit)
- [Yang tidak ada di repo ini, dan kenapa](#yang-tidak-ada-di-repo-ini-dan-kenapa)

---

## Hasil acuan (harus cocok persis)

Jalankan `--verify` pada kedua metode. Angka di kolom "hasil Anda" **wajib**
sama dengan kolom "acuan". Selisih satu trade pun berarti ada yang berubah.

### H4 — metode utama

```
python trading/xauusd_method_LOCKED_H4.py --verify
```

| Metrik | Acuan | Hasil Anda |
|---|---|---|
| Jumlah trade | **346** | |
| Menang | **203** | |
| Kalah | **143** | |
| Win rate | **58,7 %** | |
| Profit factor | **2,38** | |
| Net profit | **+3.510,48 USD** | |
| Max drawdown | **−108,00 USD** | |
| Net / DD | **32,5** | |
| Expectancy | **10,15 USD** | |
| Lock hash | **`0c76e240…`** | |

### H1 — referensi

```
python trading/xauusd_method_LOCKED.py --verify
```

| Metrik | Acuan |
|---|---|
| Jumlah trade | **165** |
| Win rate | **56,4 %** |
| Profit factor | **2,15** |
| Net profit | **+1.480,24 USD** |
| Max drawdown | **−102,00 USD** |
| Lock hash | **`dda75a33…`** |

---

## Struktur repo

```
.
├── README.md                     <- Anda di sini
├── LICENSE
├── trading/                      <- SISTEM LENGKAP, siap pakai
│   ├── xauusd_bundle.py          <- PETI PENYIMPAN: 9 file ter-encode base64
│   ├── xauusd_method_LOCKED.py   <- aturan H1 (JANGAN DIUBAH)
│   ├── xauusd_method_LOCKED_H4.py<- aturan H4, metode utama (JANGAN DIUBAH)
│   ├── signal_live_h4.py         <- robot Telegram
│   ├── run_signal.bat            <- kirim sinyal + balas /status
│   ├── poll_only.bat             <- balas /status tiap 5 menit
│   ├── register_tasks.bat        <- daftarkan 2 task Windows
│   ├── CEK_STATUS.bat            <- cek kesehatan
│   ├── PANDUAN.md                <- panduan bahasa Indonesia
│   └── signal_state.json         <- memori robot (snapshot)
├── docs/
│   ├── restore-and-boot.md       <- KONTRAK PEMULIHAN, baca ini kalau bingung
│   ├── live-deployment.md        <- catatan deployment
│   └── backtest-reproducibility.md
├── skill/
│   └── SKILL.md                  <- skill Hermes (termasuk aturan "baca dulu")
└── data/
    ├── XAUUSD240.csv             <- data H4, untuk reproduksi backtest
    └── template-backtest.csv     <- skema ekspor CSV
```

---

## Cara pakai di komputer baru

### Langkah 1 — ambil repo

```
git clone https://github.com/syukurlawolo/Testing.git
```

### Langkah 2 — pulihkan sistem (satu perintah)

Bundle menulis semua file kembali dengan isi yang persis sama.

```
python trading/xauusd_bundle.py --restore
```

Kalau Anda ingin menaruhnya di lokasi standar Hermes
(`C:\Users\<user>\AppData\Local\hermes\trading`), bundle sudah menunjuk ke sana
secara default. Untuk lokasi lain, edit `TARGET_DIR` di baris atas
`xauusd_bundle.py`.

Cek dulu tanpa mengubah apa pun:

```
python trading/xauusd_bundle.py --verify   # bandingkan dengan salinan beku
python trading/xauusd_bundle.py --list     # lihat isi + hash
python trading/xauusd_bundle.py --diff     # hanya yang berbeda
```

### Langkah 3 — pastikan metode masih utuh

```
python trading/xauusd_method_LOCKED_H4.py --verify
python trading/xauusd_method_LOCKED.py --verify
```

Keduanya harus berbunyi **`RESULT : PASS`**. Kalau tidak, **berhenti** — jangan
lanjut ke langkah berikutnya.

### Langkah 4 — sesuaikan path Python

`.bat` memakai **path absolut** ke python, karena Task Scheduler tidak mengenal
`python` di PATH. Setelah pindah komputer, path ini hampir pasti berubah.

Cari yang baru:

```
ls ~/AppData/Local/hermes/installs/*/environments/*/venv/Scripts/python.exe
```

Lalu perbarui baris `set PYTHON=` di **`run_signal.bat`** dan **`poll_only.bat`**.

> Ini penyebab **paling sering** robot jadi diam setelah pindah komputer.

### Langkah 5 — taruh kredensial Telegram

Robot membaca `tg.json` (tidak disertakan di repo — lihat
[di bawah](#yang-tidak-ada-di-repo-ini-dan-kenapa)):

```json
{
  "token": "<token bot Anda>",
  "chat_id": "<chat id Anda>"
}
```

Simpan di `C:\Users\<user>\Documents\OTHER\agen\tg.json`, atau ubah path-nya di
`signal_live_h4.py`.

### Langkah 6 — daftarkan jadwal Windows

Klik dua kali **`trading/register_tasks.bat`**, atau dari Command Prompt:

```
cd trading
register_tasks.bat
```

Skrip ini membuat dua task dan **mematikan** syarat "hanya saat listrik".

| Task | Kapan | Fungsi |
|---|---|---|
| `XAUUSD_Locked_H4_Signal` | 07:05, 11:05, 15:05, 19:05, 23:05, 03:05 WIB | kirim sinyal baru |
| `XAUUSD_Telegram_Status` | tiap 5 menit | balas `/status` |

### Langkah 7 — tes ujung ke ujung

```
python trading/signal_live_h4.py --status      # baca data + state
python trading/signal_live_h4.py --test        # kirim pesan tes ke Telegram
python trading/signal_live_h4.py --run --dry   # simulasi, tidak mengirim
```

Lalu buka Telegram, kirim `/status` ke bot Anda.

---

## Cara pakai sehari-hari

Kirim ke bot Anda di Telegram:

| Perintah | Balasan |
|---|---|
| `/status` | Harga sekarang, level terdekat, ada sinyal atau tidak, dan sejak kapan berlaku |
| `/start` | Konfirmasi robot aktif |

Sinyal baru dikirim **otomatis** setiap lilin H4 tutup. Tidak perlu tanya.

Kalau `/status` menampilkan peringatan data basi, artinya MT4 tertutup atau
belum login — robot hanya membaca file yang ditulis MT4, jadi tidak ada lilin
baru dan tidak ada sinyal baru.

Panduan lengkap berbahasa Indonesia ada di [`trading/PANDUAN.md`](trading/PANDUAN.md).

---

## Integritas & hash

Ada **dua jenis hash yang berbeda**. Mencampuradukkan keduanya adalah sumber
alarm palsu.

| Jenis | Artinya | Cakupan |
|---|---|---|
| **Lock hash** | hash aturan trading | level, buffer, cap, RR, TTL |
| **File sha256** | hash byte file | seluruh isi file |

Nilai file sha256:

```
xauusd_method_LOCKED.py       bfb360af0f850474291f78a5b3c3cca5414a8417065f142985489bec3b710275
xauusd_method_LOCKED_H4.py    acc7d5beddae99db4044ca26305cb57c815ca62f02b65167fb4bded4450d2271
```

Nilai lock hash dilaporkan sendiri oleh `--verify` (`OK (0c76e240…)`).

---

## Aturan metode (ringkas)

- 38 level support/resistance sudah ditetapkan, tidak dihitung ulang
- Sinyal muncul bila **satu lilin H4 tutup** melewati sebuah level
- Entry = **limit order** 3,00 USD di belakang garis yang ditembus
- TP = level berikutnya, jaraknya di-cap maksimum 30,00 USD
- SL = 60 % dari jarak TP (menang 30, kalah 18)
- Limit hangus setelah 2 lilin H4 (8 jam)
- Hanya satu posisi pada satu waktu
- Cooldown di bar exit

---

## Perangkap yang sudah pernah menggigit

Empat hal ini pernah menghabiskan waktu berjam-jam. Semuanya sudah ditangani,
tapi akan muncul lagi kalau `.bat` atau task dibuat ulang dengan cara lama.

**1. "Last Result: 0" tapi tidak terjadi apa-apa.**
Windows menandai task sukses walaupun tidak pernah jalan. Penyebabnya
`DisallowStartIfOnBatteries=true` sementara laptop pakai baterai.
`register_tasks.bat` mematikannya. Verifikasi:

```
powershell -c "$s=Get-ScheduledTask -TaskName 'XAUUSD_Locked_H4_Signal'; $s.Settings.DisallowStartIfOnBatteries"
```

Harus mencetak `False`.

**2. `python` tidak ada di PATH Task Scheduler.**
Karena itu `.bat` memakai path absolut. Lihat Langkah 4.

**3. Nama file log mengandung titik dua.**
`%TIME%` menghasilkan `15:36:27` — tidak sah untuk nama file, log tidak pernah
terbentuk. `run_signal.bat` memakai `wmic os get localdatetime`.

**4. State kosong bisa membanjiri Telegram.**
`signal_state.json` adalah ingatan robot. Kalau hilang dan diganti snapshot
kosong, bot bisa mengirim ulang sinyal lama. Dua pengaman: bundle **tidak
pernah menimpa state yang masih hidup**, dan sinyal lebih tua dari 3 lilin H4
(12 jam) dibuang otomatis karena limit-nya sudah hangus.

---

## Yang tidak ada di repo ini, dan kenapa

| Hal | Alasan |
|---|---|
| `tg.json` (token & chat id) | **Kredensial tidak pernah di-commit.** Isi sendiri. |
| `XAUUSD240.hst` | Ditulis MT4, ukurannya besar dan berubah tiap saat. |
| Task Scheduler | Milik Windows, bukan file. Dibuat ulang oleh `register_tasks.bat`. |
| `signal_state.json` terkini | Hanya snapshot. State hidup tidak pernah ditimpa. |

---

## Batasan (jujur)

- Ini **pengirim sinyal**, bukan eksekutor. Tidak ada order yang dipasang
  otomatis di MT4. Anda tetap memasangnya manual.
- Robot hanya membaca data dari MT4. MT4 tertutup = tidak ada sinyal.
- Sinyal yang sudah lewat 3 lilin H4 tidak dikirim, karena limit-nya sudah
  hangus dan tidak bisa diisi.
- Hasil backtest bukan jaminan hasil ke depan.
