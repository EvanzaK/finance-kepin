# 🛵 Finance Kepin - Hybrid Personal Finance & ShopeeFood Tracker

Aplikasi modern pencatatan arus kas pribadi dengan sistem **Multi-Dompet / Digital Pocketing (Tunai, Bank BRI, dan Pos Tabungan bluSaving)** sekaligus analitik performa driver sampingan **ShopeeFood (Honda BeAT 2021)** berbasis **Python (Flask)**, **Telegram Bot API**, dan **Google Sheets API** dengan sistem **otomatis fallback ke SQLite lokal (`keuangan.db`)**.

---

## 🌟 Fitur Utama

1. **Digital Pocketing / Multi-Dompet Dinamis**:
   - 💵 **Kas Tunai**: Uang fisik di saku (otomatis terisi saat narik ShopeeFood).
   - 💳 **Bank BRI**: Rekening transaksi operasional harian / QRIS / belanja.
   - 🏦 **Blu BCA - Tabungan**: Pos tabungan utama bluSaving.
   - 🔧 **Blu BCA - Servis Motor**: Pos cadangan servis & ganti oli motor.
   - **Bebas Tambah & Edit Kantong**: Anda dapat menambah kantong baru (misal: *Dana Darurat, Pajak Motor, ShopeePay*) atau menyetel **Saldo Awal** agar nominal di aplikasi cocok dengan saldo nyata di m-Banking.
   - **Fitur Transfer / Pindah Dana**: Setor tunai hasil ojol ke ATM BRI atau menyisihkan uang dari BRI ke bluSaving tanpa dihitung sebagai pengeluaran baru.

2. **Dual Storage Engine (Hybrid)**:
   - **Google Sheets**: Sinkronisasi data real-time ke spreadsheet online `Database_Keuangan` (Worksheet: `Dompet`, `Transaksi`, `Log_Ojol`).
   - **SQLite Fallback**: Jika `credentials.json` belum dipasang atau internet offline, sistem otomatis beralih ke database SQLite lokal `keuangan.db` tanpa error.

3. **Bot Telegram Interaktif (Input Super Cepat)**:
   - `/dompet` atau `/saldo` : Cek rincian saldo semua rekening & grand total.
   - `/transfer [asal] [tujuan] [nominal] [catatan]` : Pindah dana antar rekening.  
     *Contoh:* `/transfer tunai bri 50000 setor tunai atm`  
     *Contoh:* `/transfer bri blu 200000 tabung bulanan`
   - `/masuk [kategori] [nominal] [catatan] [dompet]` : Catat pemasukan ke rekening tertentu.  
     *Contoh:* `/masuk gaji 3000000 bonus bri`
   - `/keluar [kategori] [nominal] [catatan] [dompet]` : Catat pengeluaran dari rekening tertentu.  
     *Contoh:* `/keluar makan 15000 warteg tunai`  
     *Contoh:* `/keluar bensin 20000 pertalite bri`
   - `/ojol [omzet] [bensin] [order] [odo_awal] [odo_akhir]` : Catat tarikan ShopeeFood (laba kas otomatis masuk ke Kas Tunai).
   - `/rekap` : Ringkasan performa bulanan & sisa kekurangan menuju target Rp1 Juta.

4. **Logika Analitik Otomatis ShopeeFood**:
   - Parameter kendaraan: **Honda BeAT 2021** (konsumsi rata-rata ~54 km/liter, harga Pertalite Rp10.000/liter).
   - Cadangan servis motor: **Rp 150 / km** (disisihkan untuk ganti oli & perawatan).
   - Perhitungan otomatis: `jarak_km`, `laba_kas`, `dana_servis`, `estimasi_bensin_riil`, `laba_bersih_murni`, dan `rp_per_km`.
   - Indikator efisiensi rasio Rp/km:
     - 🟢 **>= Rp 1.200/km**: Sangat Efisien.
     - 🟡 **Rp 800 - Rp 1.199/km**: Cukup.
     - 🔴 **< Rp 800/km**: Banyak KM Kosong.

5. **Web Dashboard Responsif (HP & Desktop)**:
   - Tema elegan Light Blue/White dengan tipografi *Plus Jakarta Sans*.
   - **Kartu Pos Rekening**: Tampilan saldo realtime masing-masing kantong.
   - **Tombol Transfer & Kelola Dompet**: Buka modal untuk memindahkan uang atau mengedit saldo awal.
   - **Dual Progress Bar Target ShopeeFood**: Milestone 1 (Rp 500.000) & Target Utama (Rp 1.000.000).
   - **Grafik Harian & Kategori Pengeluaran**: 100% murni data riil.

---

## 📁 Struktur Folder Proyek

```text
Project Keuangan/
├── app.py                 # Main Flask server + background polling thread Bot Telegram
├── database.py            # Modul abstraksi data Multi-Dompet (Google Sheets + SQLite)
├── requirements.txt       # Daftar pustaka Python yang dibutuhkan
├── .env                   # File konfigurasi aktif
├── .env.example           # Template konfigurasi environment
├── keuangan.db            # Database SQLite lokal (berisi data riil & dompet)
├── credentials.json       # Service account Google Cloud untuk Google Sheets
├── run_app.bat            # Script 1-klik untuk menjalankan server di Windows
├── templates/
│   └── index.html         # Web Dashboard responsif dengan Multi-Pocketing
└── README.md              # Dokumentasi lengkap proyek
```

---

## 🚀 Panduan Menjalankan Aplikasi

Jalankan server utama:
```powershell
& "C:\laragon\bin\python\python-3.13\python.exe" app.py
```
Atau klik ganda file **`run_app.bat`**.

Buka browser dan akses:
👉 **[http://localhost:5000](http://localhost:5000)**
