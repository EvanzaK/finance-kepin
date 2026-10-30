"""
Finance Kepin - Hybrid Personal Finance & ShopeeFood Driver Tracker
Data Access Layer (Google Sheets with Automatic SQLite Fallback + Multi-Wallet Digital Pocketing)
"""

import os
import sqlite3
import datetime
import logging
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DatabaseManager")

load_dotenv()

# Konstanta Spesifikasi & Asumsi
DEFAULT_KONSUMSI_BBM = float(os.getenv("KONSUMSI_BBM_KM_PER_LITER", "54.0"))  # Honda BeAT 2021: 54 km/L
DEFAULT_HARGA_BENSIN = int(os.getenv("HARGA_BENSIN_PER_LITER", "10000"))      # Pertalite: Rp10.000 / liter
DEFAULT_BIAYA_SERVIS = int(os.getenv("BIAYA_SERVIS_PER_KM", "150"))           # Cadangan servis: Rp150 / km
DEFAULT_TARGET_BULANAN = int(os.getenv("TARGET_OJOL_BULANAN", "1000000"))     # Rp 1.000.000
DEFAULT_TARGET_MILESTONE = int(os.getenv("TARGET_OJOL_MILESTONE", "500000"))  # Rp 500.000

DB_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keuangan.db")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Database_Keuangan")
STORAGE_MODE = os.getenv("STORAGE_MODE", "auto").lower()

# Default Dompet / Pocket awal
DEFAULT_DOMPET_SEED = [
    {"nama": "Kas Tunai", "tipe": "Cash", "saldo_awal": 0, "icon": "💵", "catatan": "Uang fisik di saku / hasil narik ShopeeFood"},
    {"nama": "Bank BRI", "tipe": "Bank", "saldo_awal": 0, "icon": "💳", "catatan": "Rekening transaksi operasional harian / QRIS"},
    {"nama": "Blu BCA - Tabungan", "tipe": "bluSaving", "saldo_awal": 0, "icon": "🏦", "catatan": "Pos Tabungan Utama bluSaving"},
    {"nama": "Blu BCA - Dana Darurat", "tipe": "bluSaving", "saldo_awal": 0, "icon": "🛡️", "catatan": "Pos Tabungan Dana Darurat bluSaving"}
]


def hitung_metrik_ojol(
    odo_awal: int,
    odo_akhir: int,
    omzet_kotor: int,
    modal_bensin: int,
    konsumsi_bbm: float = DEFAULT_KONSUMSI_BBM,
    harga_bensin: int = DEFAULT_HARGA_BENSIN,
    biaya_servis_per_km: int = DEFAULT_BIAYA_SERVIS
) -> Dict[str, Any]:
    """
    Menghitung seluruh variabel analitik ShopeeFood sesuai spesifikasi:
    - jarak_km = odo_akhir - odo_awal
    - laba_kas = omzet_kotor - modal_bensin (uang bersih di tangan)
    - estimasi_liter = jarak_km / konsumsi_bbm
    - estimasi_bensin_riil = round(estimasi_liter * harga_bensin)
    - dana_servis = jarak_km * biaya_servis_per_km
    - laba_bersih_murni = omzet_kotor - estimasi_bensin_riil - dana_servis
    - rp_per_km = round(omzet_kotor / jarak_km)
    """
    jarak_km = max(0, int(odo_akhir) - int(odo_awal))
    laba_kas = int(omzet_kotor) - int(modal_bensin)
    
    estimasi_liter = (jarak_km / konsumsi_bbm) if konsumsi_bbm > 0 else 0.0
    estimasi_bensin_riil = round(estimasi_liter * harga_bensin)
    dana_servis = round(jarak_km * biaya_servis_per_km)
    laba_bersih_murni = int(omzet_kotor) - estimasi_bensin_riil - dana_servis
    
    rp_per_km = round(int(omzet_kotor) / jarak_km) if jarak_km > 0 else 0
    
    if rp_per_km >= 1200:
        indikator_label = "Sangat Efisien"
        indikator_badge = "🟢 Sangat Efisien"
        status_color = "emerald"
    elif rp_per_km >= 800:
        indikator_label = "Cukup"
        indikator_badge = "🟡 Cukup"
        status_color = "amber"
    else:
        indikator_label = "Banyak KM Kosong"
        indikator_badge = "🔴 Banyak KM Kosong"
        status_color = "rose"

    return {
        "jarak_km": jarak_km,
        "laba_kas": laba_kas,
        "estimasi_liter": round(estimasi_liter, 2),
        "estimasi_bensin_riil": estimasi_bensin_riil,
        "dana_servis": dana_servis,
        "laba_bersih_murni": laba_bersih_murni,
        "rp_per_km": rp_per_km,
        "indikator_label": indikator_label,
        "indikator_badge": indikator_badge,
        "status_color": status_color
    }


class SQLiteStorage:
    """Implementasi backend penyimpanan lokal SQLite (keuangan.db) dengan Multi-Dompet."""

    def __init__(self, db_path: str = DB_FILE_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Tabel Dompet (Wallets & Pockets)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Dompet (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama TEXT NOT NULL UNIQUE,
                    tipe TEXT NOT NULL,
                    saldo_awal INTEGER NOT NULL DEFAULT 0,
                    icon TEXT DEFAULT '🏦',
                    catatan TEXT DEFAULT ''
                )
            """)

            # 2. Tabel Transaksi Umum
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Transaksi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT NOT NULL,
                    tipe TEXT NOT NULL,
                    kategori TEXT NOT NULL,
                    nominal INTEGER NOT NULL,
                    catatan TEXT,
                    dompet TEXT DEFAULT 'Kas Tunai',
                    dompet_tujuan TEXT DEFAULT ''
                )
            """)

            # Migrasi kolom dompet & dompet_tujuan jika tabel lama belum memilikinya
            cursor.execute("PRAGMA table_info(Transaksi)")
            cols = [c[1] for c in cursor.fetchall()]
            if "dompet" not in cols:
                cursor.execute("ALTER TABLE Transaksi ADD COLUMN dompet TEXT DEFAULT 'Kas Tunai'")
            if "dompet_tujuan" not in cols:
                cursor.execute("ALTER TABLE Transaksi ADD COLUMN dompet_tujuan TEXT DEFAULT ''")

            # 3. Tabel Log_Ojol
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Log_Ojol (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT NOT NULL,
                    jumlah_order INTEGER NOT NULL,
                    odo_awal INTEGER NOT NULL,
                    odo_akhir INTEGER NOT NULL,
                    jarak_km INTEGER NOT NULL,
                    omzet_kotor INTEGER NOT NULL,
                    modal_bensin INTEGER NOT NULL,
                    laba_kas INTEGER NOT NULL,
                    estimasi_bensin_riil INTEGER NOT NULL,
                    dana_servis INTEGER NOT NULL,
                    laba_bersih_murni INTEGER NOT NULL,
                    rp_per_km INTEGER NOT NULL
                )
            """)
            conn.commit()

        # Seed default dompet jika masih kosong
        self._seed_default_dompet_if_needed()
        # Seed data awal ojol jika kosong
        self._seed_initial_data_if_needed()

    def _seed_default_dompet_if_needed(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt FROM Dompet")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                logger.info("Tabel Dompet kosong. Memasukkan dompet default...")
                for d in DEFAULT_DOMPET_SEED:
                    cursor.execute("""
                        INSERT OR IGNORE INTO Dompet (nama, tipe, saldo_awal, icon, catatan)
                        VALUES (?, ?, ?, ?, ?)
                    """, (d["nama"], d["tipe"], d["saldo_awal"], d["icon"], d["catatan"]))
                conn.commit()

    def _seed_initial_data_if_needed(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS cnt FROM Log_Ojol")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                logger.info("Database kosong. Memasukkan data awal riil 2026-10-29...")
                self.add_log_ojol(
                    tanggal="2026-10-29",
                    jumlah_order=7,
                    odo_awal=4818,
                    odo_akhir=4907,
                    omzet_kotor=61000,
                    modal_bensin=15000,
                    sync_transaksi=True,
                    custom_jam="21:00"
                )

    # --- Manajemen Dompet ---
    def get_dompet(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Dompet ORDER BY id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def add_dompet(self, nama: str, tipe: str = "bluSaving", saldo_awal: int = 0, icon: str = "🏦", catatan: str = "") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Dompet (nama, tipe, saldo_awal, icon, catatan)
                VALUES (?, ?, ?, ?, ?)
            """, (nama.strip(), tipe.strip(), int(saldo_awal), icon.strip(), catatan.strip()))
            conn.commit()
            return cursor.lastrowid

    def update_dompet(self, dompet_id: int, nama: str, saldo_awal: int, tipe: Optional[str] = None, icon: Optional[str] = None, catatan: Optional[str] = None) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Dompet WHERE id = ?", (dompet_id,))
            old = cursor.fetchone()
            if not old:
                return False
            
            old_nama = old["nama"]
            new_nama = nama.strip()
            new_tipe = tipe.strip() if tipe else old["tipe"]
            new_icon = icon.strip() if icon else old["icon"]
            new_catatan = catatan.strip() if catatan is not None else old["catatan"]

            cursor.execute("""
                UPDATE Dompet 
                SET nama = ?, tipe = ?, saldo_awal = ?, icon = ?, catatan = ?
                WHERE id = ?
            """, (new_nama, new_tipe, int(saldo_awal), new_icon, new_catatan, dompet_id))

            # Jika nama dompet berubah, update riwayat transaksi yang merujuk nama lama
            if old_nama != new_nama:
                cursor.execute("UPDATE Transaksi SET dompet = ? WHERE dompet = ?", (new_nama, old_nama))
                cursor.execute("UPDATE Transaksi SET dompet_tujuan = ? WHERE dompet_tujuan = ?", (new_nama, old_nama))

            conn.commit()
            return True

    def delete_dompet(self, dompet_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT nama FROM Dompet WHERE id = ?", (dompet_id,))
            row = cursor.fetchone()
            if not row:
                return False
            nama = row["nama"]
            if nama in ["Kas Tunai", "Bank BRI"]:
                return False  # Lindungi dompet inti sistem
            cursor.execute("DELETE FROM Dompet WHERE id = ?", (dompet_id,))
            conn.commit()
            return True

    # --- Transaksi & Transfer ---
    def add_transaksi(
        self,
        tipe: str,
        kategori: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None,
        dompet: str = "Kas Tunai",
        dompet_tujuan: str = ""
    ) -> int:
        if not tanggal:
            tanggal = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        elif len(tanggal) == 10:
            tanggal = f"{tanggal} {datetime.datetime.now().strftime('%H:%M')}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Transaksi (tanggal, tipe, kategori, nominal, catatan, dompet, dompet_tujuan)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (tanggal, tipe, kategori, int(nominal), catatan, dompet, dompet_tujuan))
            conn.commit()
            return cursor.lastrowid

    def add_transfer(
        self,
        dompet_asal: str,
        dompet_tujuan: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None
    ) -> int:
        catatan_full = catatan.strip() or f"Pindah dana: {dompet_asal} ➡️ {dompet_tujuan}"
        return self.add_transaksi(
            tipe="Transfer",
            kategori="Transfer Antar Dompet",
            nominal=nominal,
            catatan=catatan_full,
            tanggal=tanggal,
            dompet=dompet_asal,
            dompet_tujuan=dompet_tujuan
        )

    def get_transaksi(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM Transaksi"
        params = []
        if bulan:
            query += " WHERE tanggal LIKE ?"
            params.append(f"{bulan}%")
        query += " ORDER BY tanggal DESC, id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            for r in rows:
                if not r.get("dompet"):
                    r["dompet"] = "Kas Tunai"
                if not r.get("dompet_tujuan"):
                    r["dompet_tujuan"] = ""
            return rows

    def delete_transaksi(self, transaksi_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Transaksi WHERE id = ?", (transaksi_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- Log Ojol ---
    def add_log_ojol(
        self,
        tanggal: str,
        jumlah_order: int,
        odo_awal: int,
        odo_akhir: int,
        omzet_kotor: int,
        modal_bensin: int,
        sync_transaksi: bool = True,
        custom_jam: Optional[str] = None
    ) -> Dict[str, Any]:
        metrik = hitung_metrik_ojol(odo_awal, odo_akhir, omzet_kotor, modal_bensin)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO Log_Ojol (
                    tanggal, jumlah_order, odo_awal, odo_akhir, jarak_km,
                    omzet_kotor, modal_bensin, laba_kas, estimasi_bensin_riil,
                    dana_servis, laba_bersih_murni, rp_per_km
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tanggal, int(jumlah_order), int(odo_awal), int(odo_akhir), metrik["jarak_km"],
                int(omzet_kotor), int(modal_bensin), metrik["laba_kas"], metrik["estimasi_bensin_riil"],
                metrik["dana_servis"], metrik["laba_bersih_murni"], metrik["rp_per_km"]
            ))
            ojol_id = cursor.lastrowid
            conn.commit()

        # Otomatis sinkronisasi ke tabel Transaksi (MASUK KE KAS TUNAI!)
        transaksi_id = None
        if sync_transaksi:
            jam_str = custom_jam if custom_jam else datetime.datetime.now().strftime("%H:%M")
            tanggal_transaksi = f"{tanggal} {jam_str}" if len(tanggal) == 10 else tanggal
            catatan = f"Bersih {jumlah_order} order ({metrik['jarak_km']} km)"
            transaksi_id = self.add_transaksi(
                tipe="Pemasukan",
                kategori="ShopeeFood",
                nominal=metrik["laba_kas"],
                catatan=catatan,
                tanggal=tanggal_transaksi,
                dompet="Kas Tunai"
            )

        return {
            "id": ojol_id,
            "tanggal": tanggal,
            "jumlah_order": jumlah_order,
            "odo_awal": odo_awal,
            "odo_akhir": odo_akhir,
            "omzet_kotor": omzet_kotor,
            "modal_bensin": modal_bensin,
            "transaksi_id": transaksi_id,
            **metrik
        }

    def get_log_ojol(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM Log_Ojol"
        params = []
        if bulan:
            query += " WHERE tanggal LIKE ?"
            params.append(f"{bulan}%")
        query += " ORDER BY tanggal DESC, id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]

        for r in rows:
            metrik = hitung_metrik_ojol(r["odo_awal"], r["odo_akhir"], r["omzet_kotor"], r["modal_bensin"])
            r["indikator_badge"] = metrik["indikator_badge"]
            r["indikator_label"] = metrik["indikator_label"]
            r["status_color"] = metrik["status_color"]
            r["estimasi_liter"] = metrik["estimasi_liter"]

        return rows

    def delete_log_ojol(self, ojol_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM Log_Ojol WHERE id = ?", (ojol_id,))
            conn.commit()
            return cursor.rowcount > 0


class GoogleSheetsStorage:
    """Implementasi backend penyimpanan Google Sheets (gspread) dengan Multi-Dompet."""

    def __init__(self, credentials_file: Optional[str] = None, sheet_name: str = GOOGLE_SHEET_NAME, credentials_json: Optional[str] = None):
        self.credentials_file = credentials_file
        self.credentials_json = credentials_json or os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        self.sheet_name = sheet_name
        self.client = None
        self.spreadsheet = None
        self.ws_dompet = None
        self.ws_transaksi = None
        self.ws_ojol = None
        self._init_sheets()

    def _init_sheets(self):
        import gspread
        import json
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if self.credentials_json:
            creds_data = json.loads(self.credentials_json) if isinstance(self.credentials_json, str) else self.credentials_json
            creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(self.credentials_file, scopes=scopes)
        self.client = gspread.authorize(creds)

        try:
            self.spreadsheet = self.client.open(self.sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            logger.info(f"Spreadsheet '{self.sheet_name}' belum ada. Membuat spreadsheet baru...")
            self.spreadsheet = self.client.create(self.sheet_name)

        # 1. Worksheet Dompet
        try:
            self.ws_dompet = self.spreadsheet.worksheet("Dompet")
        except gspread.exceptions.WorksheetNotFound:
            self.ws_dompet = self.spreadsheet.add_worksheet(title="Dompet", rows=200, cols=10)
            self.ws_dompet.append_row(["id", "nama", "tipe", "saldo_awal", "icon", "catatan"])
            # Seed default
            for idx, d in enumerate(DEFAULT_DOMPET_SEED, start=1):
                self.ws_dompet.append_row([idx, d["nama"], d["tipe"], d["saldo_awal"], d["icon"], d["catatan"]])

        # 2. Worksheet Transaksi
        try:
            self.ws_transaksi = self.spreadsheet.worksheet("Transaksi")
            headers = self.ws_transaksi.row_values(1)
            # Pastikan kolom dompet & dompet_tujuan ada
            if "dompet" not in headers:
                self.ws_transaksi.update_cell(1, len(headers) + 1, "dompet")
                headers.append("dompet")
            if "dompet_tujuan" not in headers:
                self.ws_transaksi.update_cell(1, len(headers) + 1, "dompet_tujuan")
        except gspread.exceptions.WorksheetNotFound:
            self.ws_transaksi = self.spreadsheet.add_worksheet(title="Transaksi", rows=1000, cols=10)
            self.ws_transaksi.append_row(["id", "tanggal", "tipe", "kategori", "nominal", "catatan", "dompet", "dompet_tujuan"])

        # 3. Worksheet Log_Ojol
        try:
            self.ws_ojol = self.spreadsheet.worksheet("Log_Ojol")
        except gspread.exceptions.WorksheetNotFound:
            self.ws_ojol = self.spreadsheet.add_worksheet(title="Log_Ojol", rows=1000, cols=15)
            self.ws_ojol.append_row([
                "id", "tanggal", "jumlah_order", "odo_awal", "odo_akhir", "jarak_km",
                "omzet_kotor", "modal_bensin", "laba_kas", "estimasi_bensin_riil",
                "dana_servis", "laba_bersih_murni", "rp_per_km"
            ])

        # Hapus Sheet1 jika ada
        try:
            sheet1 = self.spreadsheet.worksheet("Sheet1")
            if len(sheet1.get_all_values()) == 0:
                self.spreadsheet.del_worksheet(sheet1)
        except Exception:
            pass

        # Seed data ojol jika kosong
        try:
            ojol_rows = self.ws_ojol.col_values(1)
            if len(ojol_rows) <= 1:
                logger.info("Google Sheet Log_Ojol kosong. Memasukkan data awal riil 2026-10-29...")
                self.add_log_ojol(
                    tanggal="2026-10-29",
                    jumlah_order=7,
                    odo_awal=4818,
                    odo_akhir=4907,
                    omzet_kotor=61000,
                    modal_bensin=15000,
                    sync_transaksi=True,
                    custom_jam="21:00"
                )
        except Exception as e:
            logger.warning(f"Gagal melakukan auto-seed di Google Sheets: {e}")

    def _get_next_id(self, worksheet) -> int:
        col_ids = worksheet.col_values(1)
        if len(col_ids) <= 1:
            return 1
        numeric_ids = []
        for val in col_ids[1:]:
            try:
                numeric_ids.append(int(val))
            except ValueError:
                pass
        return max(numeric_ids) + 1 if numeric_ids else 1

    # --- Manajemen Dompet (Google Sheets) ---
    def get_dompet(self) -> List[Dict[str, Any]]:
        records = self.ws_dompet.get_all_records()
        results = []
        for r in records:
            results.append({
                "id": int(r.get("id", 0)),
                "nama": str(r.get("nama", "")).strip(),
                "tipe": str(r.get("tipe", "bluSaving")).strip(),
                "saldo_awal": int(r.get("saldo_awal", 0)),
                "icon": str(r.get("icon", "🏦")).strip() or "🏦",
                "catatan": str(r.get("catatan", "")).strip()
            })
        return results

    def add_dompet(self, nama: str, tipe: str = "bluSaving", saldo_awal: int = 0, icon: str = "🏦", catatan: str = "") -> int:
        new_id = self._get_next_id(self.ws_dompet)
        row = [new_id, nama.strip(), tipe.strip(), int(saldo_awal), icon.strip(), catatan.strip()]
        self.ws_dompet.append_row(row)
        return new_id

    def update_dompet(self, dompet_id: int, nama: str, saldo_awal: int, tipe: Optional[str] = None, icon: Optional[str] = None, catatan: Optional[str] = None) -> bool:
        col_ids = self.ws_dompet.col_values(1)
        target_str = str(dompet_id)
        for idx, val in enumerate(col_ids[1:], start=2):
            if val == target_str:
                row_vals = self.ws_dompet.row_values(idx)
                old_nama = row_vals[1] if len(row_vals) > 1 else ""
                new_tipe = tipe.strip() if tipe else (row_vals[2] if len(row_vals) > 2 else "bluSaving")
                new_icon = icon.strip() if icon else (row_vals[4] if len(row_vals) > 4 else "🏦")
                new_catatan = catatan.strip() if catatan is not None else (row_vals[5] if len(row_vals) > 5 else "")
                
                # Update row
                self.ws_dompet.update(range_name=f"B{idx}:F{idx}", values=[[nama.strip(), new_tipe, int(saldo_awal), new_icon, new_catatan]])
                return True
        return False

    def delete_dompet(self, dompet_id: int) -> bool:
        col_ids = self.ws_dompet.col_values(1)
        target_str = str(dompet_id)
        for idx, val in enumerate(col_ids[1:], start=2):
            if val == target_str:
                row_vals = self.ws_dompet.row_values(idx)
                nama = row_vals[1] if len(row_vals) > 1 else ""
                if nama in ["Kas Tunai", "Bank BRI"]:
                    return False
                self.ws_dompet.delete_rows(idx)
                return True
        return False

    # --- Transaksi (Google Sheets) ---
    def add_transaksi(
        self,
        tipe: str,
        kategori: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None,
        dompet: str = "Kas Tunai",
        dompet_tujuan: str = ""
    ) -> int:
        if not tanggal:
            tanggal = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        elif len(tanggal) == 10:
            tanggal = f"{tanggal} {datetime.datetime.now().strftime('%H:%M')}"

        new_id = self._get_next_id(self.ws_transaksi)
        row = [new_id, tanggal, tipe, kategori, int(nominal), catatan, dompet, dompet_tujuan]
        self.ws_transaksi.append_row(row)
        return new_id

    def add_transfer(
        self,
        dompet_asal: str,
        dompet_tujuan: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None
    ) -> int:
        catatan_full = catatan.strip() or f"Pindah dana: {dompet_asal} ➡️ {dompet_tujuan}"
        return self.add_transaksi(
            tipe="Transfer",
            kategori="Transfer Antar Dompet",
            nominal=nominal,
            catatan=catatan_full,
            tanggal=tanggal,
            dompet=dompet_asal,
            dompet_tujuan=dompet_tujuan
        )

    def get_transaksi(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self.ws_transaksi.get_all_records()
        results = []
        for r in records:
            tgl = str(r.get("tanggal", ""))
            if bulan and not tgl.startswith(bulan):
                continue
            domp = str(r.get("dompet", "")).strip() or "Kas Tunai"
            domp_tuj = str(r.get("dompet_tujuan", "")).strip()
            results.append({
                "id": int(r.get("id", 0)),
                "tanggal": tgl,
                "tipe": str(r.get("tipe", "")),
                "kategori": str(r.get("kategori", "")),
                "nominal": int(r.get("nominal", 0)),
                "catatan": str(r.get("catatan", "")),
                "dompet": domp,
                "dompet_tujuan": domp_tuj
            })
        results.sort(key=lambda x: (x["tanggal"], x["id"]), reverse=True)
        if limit:
            results = results[:limit]
        return results

    def delete_transaksi(self, transaksi_id: int) -> bool:
        col_ids = self.ws_transaksi.col_values(1)
        target_str = str(transaksi_id)
        for idx, val in enumerate(col_ids[1:], start=2):
            if val == target_str:
                self.ws_transaksi.delete_rows(idx)
                return True
        return False

    def add_log_ojol(
        self,
        tanggal: str,
        jumlah_order: int,
        odo_awal: int,
        odo_akhir: int,
        omzet_kotor: int,
        modal_bensin: int,
        sync_transaksi: bool = True,
        custom_jam: Optional[str] = None
    ) -> Dict[str, Any]:
        metrik = hitung_metrik_ojol(odo_awal, odo_akhir, omzet_kotor, modal_bensin)
        new_id = self._get_next_id(self.ws_ojol)
        row = [
            new_id,
            tanggal,
            int(jumlah_order),
            int(odo_awal),
            int(odo_akhir),
            metrik["jarak_km"],
            int(omzet_kotor),
            int(modal_bensin),
            metrik["laba_kas"],
            metrik["estimasi_bensin_riil"],
            metrik["dana_servis"],
            metrik["laba_bersih_murni"],
            metrik["rp_per_km"]
        ]
        self.ws_ojol.append_row(row)

        transaksi_id = None
        if sync_transaksi:
            jam_str = custom_jam if custom_jam else datetime.datetime.now().strftime("%H:%M")
            tanggal_transaksi = f"{tanggal} {jam_str}" if len(tanggal) == 10 else tanggal
            catatan = f"Bersih {jumlah_order} order ({metrik['jarak_km']} km)"
            transaksi_id = self.add_transaksi(
                tipe="Pemasukan",
                kategori="ShopeeFood",
                nominal=metrik["laba_kas"],
                catatan=catatan,
                tanggal=tanggal_transaksi,
                dompet="Kas Tunai"
            )

        return {
            "id": new_id,
            "tanggal": tanggal,
            "jumlah_order": jumlah_order,
            "odo_awal": odo_awal,
            "odo_akhir": odo_akhir,
            "omzet_kotor": omzet_kotor,
            "modal_bensin": modal_bensin,
            "transaksi_id": transaksi_id,
            **metrik
        }

    def get_log_ojol(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self.ws_ojol.get_all_records()
        results = []
        for r in records:
            tgl = str(r.get("tanggal", ""))
            if bulan and not tgl.startswith(bulan):
                continue
            item = {
                "id": int(r.get("id", 0)),
                "tanggal": tgl,
                "jumlah_order": int(r.get("jumlah_order", 0)),
                "odo_awal": int(r.get("odo_awal", 0)),
                "odo_akhir": int(r.get("odo_akhir", 0)),
                "jarak_km": int(r.get("jarak_km", 0)),
                "omzet_kotor": int(r.get("omzet_kotor", 0)),
                "modal_bensin": int(r.get("modal_bensin", 0)),
                "laba_kas": int(r.get("laba_kas", 0)),
                "estimasi_bensin_riil": int(r.get("estimasi_bensin_riil", 0)),
                "dana_servis": int(r.get("dana_servis", 0)),
                "laba_bersih_murni": int(r.get("laba_bersih_murni", 0)),
                "rp_per_km": int(r.get("rp_per_km", 0)),
            }
            metrik = hitung_metrik_ojol(item["odo_awal"], item["odo_akhir"], item["omzet_kotor"], item["modal_bensin"])
            item["indikator_badge"] = metrik["indikator_badge"]
            item["indikator_label"] = metrik["indikator_label"]
            item["status_color"] = metrik["status_color"]
            item["estimasi_liter"] = metrik["estimasi_liter"]
            results.append(item)

        results.sort(key=lambda x: (x["tanggal"], x["id"]), reverse=True)
        if limit:
            results = results[:limit]
        return results

    def delete_log_ojol(self, ojol_id: int) -> bool:
        col_ids = self.ws_ojol.col_values(1)
        target_str = str(ojol_id)
        for idx, val in enumerate(col_ids[1:], start=2):
            if val == target_str:
                self.ws_ojol.delete_rows(idx)
                return True
        return False


class DataManager:
    """
    Abstraksi tunggal untuk aplikasi dengan dukungan Multi-Dompet Digital Pocketing.
    """

    def __init__(self):
        self.mode = "sqlite"
        self.storage = None
        self.status_detail = ""
        self._init_storage()

    def _init_storage(self):
        creds_json_env = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        creds_exist = os.path.isfile(CREDENTIALS_FILE) or bool(creds_json_env)

        if STORAGE_MODE in ["google_sheets", "auto"]:
            if creds_exist:
                try:
                    logger.info(f"Mencoba menghubungkan ke Google Sheets: '{GOOGLE_SHEET_NAME}'...")
                    if creds_json_env:
                        self.storage = GoogleSheetsStorage(credentials_json=creds_json_env, sheet_name=GOOGLE_SHEET_NAME)
                    else:
                        self.storage = GoogleSheetsStorage(credentials_file=CREDENTIALS_FILE, sheet_name=GOOGLE_SHEET_NAME)
                    self.mode = "google_sheets"
                    self.status_detail = f"Tersambung ke Google Sheet '{GOOGLE_SHEET_NAME}'"
                    logger.info("Berhasil terhubung ke Google Sheets!")
                    return
                except Exception as e:
                    logger.warning(f"Gagal menghubungkan ke Google Sheets: {e}")
                    logger.warning("Beralih ke mode Fallback SQLite lokal (keuangan.db)...")
                    self.status_detail = f"Fallback aktif (Error GSheets: {str(e)[:40]}...)"
            else:
                self.status_detail = "credentials.json / GOOGLE_CREDENTIALS_JSON belum ada. Berjalan dalam SQLite Local Mode."
                logger.info("Credentials Google tidak ditemukan. Menggunakan SQLite lokal (keuangan.db).")

        self.storage = SQLiteStorage(DB_FILE_PATH)
        self.mode = "sqlite"

    def get_status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "is_sheets": self.mode == "google_sheets",
            "is_sqlite": self.mode == "sqlite",
            "db_path": DB_FILE_PATH,
            "sheet_name": GOOGLE_SHEET_NAME,
            "credentials_exist": os.path.isfile(CREDENTIALS_FILE),
            "detail": self.status_detail
        }

    # Proxy Dompet
    def get_dompet(self) -> List[Dict[str, Any]]:
        return self.storage.get_dompet()

    def add_dompet(self, nama: str, tipe: str = "bluSaving", saldo_awal: int = 0, icon: str = "🏦", catatan: str = "") -> int:
        return self.storage.add_dompet(nama, tipe, saldo_awal, icon, catatan)

    def update_dompet(self, dompet_id: int, nama: str, saldo_awal: int, tipe: Optional[str] = None, icon: Optional[str] = None, catatan: Optional[str] = None) -> bool:
        return self.storage.update_dompet(dompet_id, nama, saldo_awal, tipe, icon, catatan)

    def delete_dompet(self, dompet_id: int) -> bool:
        return self.storage.delete_dompet(dompet_id)

    # Proxy Transaksi & Transfer
    def add_transaksi(
        self,
        tipe: str,
        kategori: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None,
        dompet: str = "Kas Tunai",
        dompet_tujuan: str = ""
    ) -> int:
        return self.storage.add_transaksi(tipe, kategori, nominal, catatan, tanggal, dompet, dompet_tujuan)

    def add_transfer(
        self,
        dompet_asal: str,
        dompet_tujuan: str,
        nominal: int,
        catatan: str = "",
        tanggal: Optional[str] = None
    ) -> int:
        return self.storage.add_transfer(dompet_asal, dompet_tujuan, nominal, catatan, tanggal)

    def get_transaksi(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.storage.get_transaksi(limit, bulan)

    def delete_transaksi(self, transaksi_id: int) -> bool:
        return self.storage.delete_transaksi(transaksi_id)

    # Proxy Ojol
    def add_log_ojol(
        self,
        tanggal: str,
        jumlah_order: int,
        odo_awal: int,
        odo_akhir: int,
        omzet_kotor: int,
        modal_bensin: int,
        sync_transaksi: bool = True,
        custom_jam: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.storage.add_log_ojol(
            tanggal, jumlah_order, odo_awal, odo_akhir, omzet_kotor, modal_bensin, sync_transaksi, custom_jam
        )

    def get_log_ojol(self, limit: Optional[int] = None, bulan: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.storage.get_log_ojol(limit, bulan)

    def delete_log_ojol(self, ojol_id: int) -> bool:
        return self.storage.delete_log_ojol(ojol_id)

    # --- Kalkulasi Saldo Per-Dompet & Rekap ---
    def get_saldo_dompet(self) -> List[Dict[str, Any]]:
        """
        Menghitung saldo realtime masing-masing dompet/kantong:
        saldo_sekarang = saldo_awal + masuk_umum - keluar_umum + transfer_masuk - transfer_keluar
        """
        dompet_list = self.get_dompet()
        semua_transaksi = self.get_transaksi()

        results = []
        for d in dompet_list:
            nama = d["nama"]
            saldo_awal = int(d.get("saldo_awal", 0))

            masuk_umum = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "pemasukan" and t.get("dompet") == nama)
            keluar_umum = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "pengeluaran" and t.get("dompet") == nama)
            transfer_masuk = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "transfer" and t.get("dompet_tujuan") == nama)
            transfer_keluar = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "transfer" and t.get("dompet") == nama)

            saldo_sekarang = saldo_awal + masuk_umum - keluar_umum + transfer_masuk - transfer_keluar

            d_copy = dict(d)
            d_copy["saldo_sekarang"] = saldo_sekarang
            d_copy["masuk_umum"] = masuk_umum
            d_copy["keluar_umum"] = keluar_umum
            d_copy["transfer_masuk"] = transfer_masuk
            d_copy["transfer_keluar"] = transfer_keluar
            results.append(d_copy)

        return results

    def get_rekap_bulanan(self, bulan: Optional[str] = None) -> Dict[str, Any]:
        """
        Rekap komprehensif: Saldo Total Riil (sum seluruh dompet) + Arus Kas Bulan Ini + ShopeeFood Tracker
        """
        if not bulan:
            bulan = datetime.datetime.now().strftime("%Y-%m")

        dompet_list = self.get_saldo_dompet()
        saldo_total = sum(d["saldo_sekarang"] for d in dompet_list)
        total_saldo_awal = sum(d["saldo_awal"] for d in dompet_list)

        semua_transaksi = self.get_transaksi()
        total_masuk_kumulatif = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "pemasukan")
        total_keluar_kumulatif = sum(t["nominal"] for t in semua_transaksi if t["tipe"].lower() == "pengeluaran")

        # Transaksi bulan ini (Transfer tidak dihitung sebagai pemasukan/pengeluaran baru, hanya realokasi)
        transaksi_bulan = [t for t in semua_transaksi if t["tanggal"].startswith(bulan)]
        masuk_bulan = sum(t["nominal"] for t in transaksi_bulan if t["tipe"].lower() == "pemasukan")
        keluar_bulan = sum(t["nominal"] for t in transaksi_bulan if t["tipe"].lower() == "pengeluaran")

        # Log Ojol
        semua_ojol = self.get_log_ojol()
        ojol_bulan = [o for o in semua_ojol if o["tanggal"].startswith(bulan)]

        total_omzet_ojol = sum(o["omzet_kotor"] for o in ojol_bulan)
        total_bensin_kas_ojol = sum(o["modal_bensin"] for o in ojol_bulan)
        total_laba_kas_ojol = sum(o["laba_kas"] for o in ojol_bulan)
        total_km_ojol = sum(o["jarak_km"] for o in ojol_bulan)
        total_order_ojol = sum(o["jumlah_order"] for o in ojol_bulan)
        total_dana_servis = sum(o["dana_servis"] for o in ojol_bulan)
        total_laba_bersih_murni = sum(o["laba_bersih_murni"] for o in ojol_bulan)
        rata_rp_per_km = round(total_omzet_ojol / total_km_ojol) if total_km_ojol > 0 else 0

        # Target Progres
        target_utama = DEFAULT_TARGET_BULANAN
        target_milestone = DEFAULT_TARGET_MILESTONE
        pct_utama = min(100.0, round((total_laba_kas_ojol / target_utama) * 100, 1)) if target_utama > 0 else 0.0
        pct_milestone = min(100.0, round((total_laba_kas_ojol / target_milestone) * 100, 1)) if target_milestone > 0 else 0.0
        sisa_target_utama = max(0, target_utama - total_laba_kas_ojol)
        sisa_target_milestone = max(0, target_milestone - total_laba_kas_ojol)

        asumsi_per_shift = 46000
        shift_dibutuhkan = (sisa_target_utama + asumsi_per_shift - 1) // asumsi_per_shift if sisa_target_utama > 0 else 0

        return {
            "bulan": bulan,
            "saldo_total": saldo_total,
            "total_saldo_awal": total_saldo_awal,
            "dompet_list": dompet_list,
            "total_masuk_kumulatif": total_masuk_kumulatif,
            "total_keluar_kumulatif": total_keluar_kumulatif,
            "pemasukan_bulan_ini": masuk_bulan,
            "pengeluaran_bulan_ini": keluar_bulan,
            "selisih_bulan_ini": masuk_bulan - keluar_bulan,
            "total_laba_kas_ojol": total_laba_kas_ojol,
            "total_omzet_ojol": total_omzet_ojol,
            "total_bensin_kas_ojol": total_bensin_kas_ojol,
            "total_km_ojol": total_km_ojol,
            "total_order_ojol": total_order_ojol,
            "total_dana_servis": total_dana_servis,
            "total_laba_bersih_murni": total_laba_bersih_murni,
            "rata_rp_per_km": rata_rp_per_km,
            "target_utama": target_utama,
            "target_milestone": target_milestone,
            "pct_utama": pct_utama,
            "pct_milestone": pct_milestone,
            "sisa_target_utama": sisa_target_utama,
            "sisa_target_milestone": sisa_target_milestone,
            "asumsi_per_shift": asumsi_per_shift,
            "shift_dibutuhkan": shift_dibutuhkan,
            "count_transaksi": len(transaksi_bulan),
            "count_ojol": len(ojol_bulan)
        }

    def get_chart_data(self, bulan: Optional[str] = None) -> Dict[str, Any]:
        if not bulan:
            bulan = datetime.datetime.now().strftime("%Y-%m")

        ojol_list = self.get_log_ojol(bulan=bulan)
        ojol_sorted = sorted(ojol_list, key=lambda x: x["tanggal"])

        ojol_labels = [o["tanggal"] for o in ojol_sorted]
        ojol_laba_kas = [o["laba_kas"] for o in ojol_sorted]
        ojol_jarak_km = [o["jarak_km"] for o in ojol_sorted]
        ojol_laba_bersih = [o["laba_bersih_murni"] for o in ojol_sorted]

        transaksi_list = self.get_transaksi(bulan=bulan)
        pengeluaran_by_cat: Dict[str, int] = {}
        for t in transaksi_list:
            if t["tipe"].lower() == "pengeluaran":
                cat = t["kategori"].strip().title() if t["kategori"] else "Lain-Lain"
                pengeluaran_by_cat[cat] = pengeluaran_by_cat.get(cat, 0) + t["nominal"]

        cat_labels = list(pengeluaran_by_cat.keys())
        cat_values = list(pengeluaran_by_cat.values())

        return {
            "ojol_chart": {
                "labels": ojol_labels,
                "laba_kas": ojol_laba_kas,
                "jarak_km": ojol_jarak_km,
                "laba_bersih": ojol_laba_bersih
            },
            "kategori_chart": {
                "labels": cat_labels,
                "values": cat_values
            }
        }


# Global DataManager instance
db = DataManager()
