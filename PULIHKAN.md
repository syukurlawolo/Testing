# PULIHKAN.md — Perintah paling penting

Kalau Hermes lupa semuanya (chat hilang, konteks ter-reset, instalasi baru),
**tempel kalimat ini ke Hermes:**

> Pulihkan semuanya dari repo `C:\Users\Sharing Vision\Documents\OTHER\Testing`.
> Baca `PULIHKAN.md` di root repo, ikuti urutannya, dan jangan menebak apa pun.
> Aturan metode ada di `README.md` dan `docs/`. Kalau angka tidak cocok, file
> yang salah — bukan metodenya.

---

## Apa isi repo ini

| Folder | Isi |
|---|---|
| `trading/` | Salinan **byte-identik** dari seluruh isi `hermes\trading\` (metode terkunci, robot sinyal, .bat, XML task, state) |
| `skill/` | Salinan `xauusd-sr-breakout/SKILL.md` — aturan kerja robot |
| `skills/` | **Backup seluruh skill Hermes** (60 SKILL.md + semua references/templates/assets) |
| `docs/` | Kontrak restore, backtest reproducibility, live deployment |
| `data/` | Dataset acuan (`XAUUSD240.csv` = data H4 MetaTrader) + template CSV backtest |

Yang **tidak** ada di repo (sengaja): token bot Telegram (`tg.json`),
log runtime, `__pycache__`, file `.hst` MT4.

---

## Urutan pulih kalau Hermes amnesia

### 1. Pulihkan file robot + metode

```bat
python trading\xauusd_bundle.py --restore
```

atau, kalau mau dari repo langsung:

```bat
copy trading\*.* "C:\Users\Sharing Vision\AppData\Local\hermes\trading\"
```

Lalu **wajib** cek dua metode:

```bat
python C:\Users\Sharing Vision\AppData\Local\hermes\trading\xauusd_method_LOCKED_H4.py --verify
python C:\Users\Sharing Vision\AppData\Local\hermes\trading\xauusd_method_LOCKED.py --verify
```

Harus **PASS** dua-duanya (H4 = 346 trade, H1 = 165 trade).

### 2. Pulihkan skill

Salin balik `skill\` dan `skills\` ke:

```
C:\Users\Sharing Vision\AppData\Local\hermes\skills\
C:\Users\Sharing Vision\AppData\Local\hermes\skills\productivity\xauusd-sr-breakout\
```

Lalu jalankan `python assets\xauusd_bundle.py --verify` **dari dalam skill**.

### 3. Telegram

Repo tidak menyimpan token. Token ada di
`C:\Users\Sharing Vision\Documents\OTHER\agen\tg.json`.
Kalau file itu juga hilang, buat bot baru lewat @BotFather dan isi ulang.

### 4. Jadwal Windows

```bat
trading\register_tasks.bat
```

Cek: `schtasks /Query /TN "XAUUSD_Locked_H4_Signal"` → harus ada
`Next Run Time` dan **tidak ada** `<Duration>` di XML.

### 5. Bukti hidup

```bat
python C:\Users\Sharing Vision\AppData\Local\hermes\trading\signal_live_h4.py --status
```

---

## Aturan yang tidak boleh dilanggar

1. **Jangan tuning ulang metodenya.** Angka acuan ada di `README.md`.
   Kalau beda, pulihkan dari bundle — jangan "perbaiki" metodenya.
2. **Jangan pernah kirim pesan contoh tanpa label.** Pesan demo wajib berjudul
   jelas "CONTOH — BUKAN SINYAL".
3. **Jangan hapus skrip sendiri.** Skrip demo/uji yang menghapus dirinya
   membuat jejak hilang; simpan atau masukkan ke repo dulu.
4. **Setiap kali `signal_live_h4.py` diubah:** jalankan `--verify`, rebuild
   bundle, lalu **samakan `xauusd_bundle.py` di `trading\`, `skill/assets\`,
   dan repo ini.** Ketiganya pernah tidak sinkron dan bisa memulihkan mesin
   yang salah.
5. **Rahasia tidak masuk git.** `tg.json`, token, chat_id: jangan commit.

---

## Cek cepat bahwa repo ini masih benar

```bat
cd C:\Users\Sharing Vision\Documents\OTHER\Testing
for %f in (signal_live_h4.py xauusd_bundle.py xauusd_method_LOCKED.py xauusd_method_LOCKED_H4.py) do @fc /b trading\%f "C:\Users\Sharing Vision\AppData\Local\hermes\trading\%f"
```

`fc` tidak boleh melaporkan perbedaan. Kalau ada, yang salah adalah file live
(kecuali Anda memang baru mengubahnya — maka perbarui repo-nya).
