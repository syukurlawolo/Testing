# Robot Sinyal XAUUSD H4 — Panduan Singkat

Metode terkunci: `XAUUSD-SR-BREAKOUT-BT2-CAP30-H4 v1.0.0`
Hasil backtest: 346 trade, win rate 58,7%, profit factor 2,38.

---

## Cara pakai sehari-hari

Buka Telegram, chat **@cerita_today_bot**, ketik:

| Perintah | Yang Anda dapat |
|---|---|
| `/status` | Harga sekarang, level terdekat, ada sinyal atau tidak, sejak kapan berlaku |
| `/start` | Konfirmasi robot aktif |

Sinyal baru **dikirim otomatis** setiap lilin H4 tutup. Tidak perlu tanya.

---

## Kapan robot bekerja

Lilin H4 tutup jam (WIB): **07, 11, 15, 19, 23, 03**
Robot jalan 5 menit setelahnya: **07:05, 11:05, 15:05, 19:05, 23:05, 03:05**

Perintah `/status` dibalas maksimal 5 menit setelah Anda kirim.

**Penting:** robot hanya membaca data yang ditulis MT4. Kalau MT4 tertutup
atau belum login, tidak ada lilin baru dan tidak ada sinyal baru.
Bagian atas `/status` akan menampilkan peringatan bila data sudah basi.

---

## Cek kesehatan robot

Klik dua kali: **`CEK_STATUS.bat`**

Menampilkan status, integritas metode terkunci, dan jadwal otomatis.

---

## File di folder ini

| File | Isi |
|---|---|
| `xauusd_method_LOCKED_H4.py` | **Aturan trading. Jangan diubah.** |
| `xauusd_method_LOCKED.py` | Metode H1, referensi. Jangan diubah. |
| `signal_live_h4.py` | Robot Telegram |
| `run_signal.bat` | Dipanggil penjadwal: kirim sinyal + balas /status |
| `poll_only.bat` | Dipanggil penjadwal: balas /status tiap 5 menit |
| `CEK_STATUS.bat` | Cek kesehatan manual |
| `signal_state.json` | Ingatan robot (sinyal yang sudah dikirim) |
| `signals_log.jsonl` | Riwayat semua sinyal |
| `logs/` | Log setiap kali robot jalan |

---

## Aturan metode (ringkas)

- 38 level support/resistance sudah ditetapkan, tidak dihitung ulang
- Sinyal muncul bila 1 lilin H4 **tutup melewati** sebuah level
- Entry = **limit order** 3,00 di belakang garis yang ditembus
- TP = level berikutnya, maksimal 30,00
- SL = 60% dari jarak TP (menang 30, kalah 18)
- Limit hangus setelah 2 lilin H4 (8 jam)
- Hanya 1 posisi pada satu waktu

---

## Kalau mau mematikan sementara

Buka Task Scheduler, nonaktifkan kedua task:
- `XAUUSD_Locked_H4_Signal`
- `XAUUSD_Telegram_Status`

Atau lewat Command Prompt:

```
schtasks /Change /TN "XAUUSD_Locked_H4_Signal" /DISABLE
schtasks /Change /TN "XAUUSD_Telegram_Status" /DISABLE
```

Menyalakan lagi: ganti `/DISABLE` dengan `/ENABLE`.

---

## Batasannya (jujur)

- Ini **pengirim sinyal**, bukan eksekutor. Tidak ada order yang dipasang
  otomatis di MT4 — Anda tetap memasangnya manual.
- Kalau laptop mati atau MT4 tertutup, tidak ada sinyal. Saat laptop hidup
  lagi, robot menyusul dan **tidak** mengirim sinyal yang sudah kedaluwarsa.
- Sinyal yang sudah lewat 3 lilin H4 sengaja tidak dikirim, karena limit-nya
  sudah hangus dan tidak bisa diisi.
