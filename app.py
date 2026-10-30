"""
Finance Kepin - Hybrid Personal Finance & ShopeeFood Driver Tracker
Main Application Server (Flask Web Dashboard + Telegram Bot Background Service + Multi-Wallet Pocketing)
"""

import os
import re
import sys
import threading
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

# Pastikan output konsol Windows mendukung UTF-8 (Emoji & Simbol)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from dotenv import load_dotenv

# Dapatkan direktori dasar absolut
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load konfigurasi environment secara absolut dari folder aplikasi
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
load_dotenv()

import database
from database import db, hitung_metrik_ojol

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s"
)
logger = logging.getLogger("AppServer")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "hybrid-finance-shopeefood-secret-2026")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

DEFAULT_REGISTERED_TOKEN = "9201080606:AAFYKLFkIbdwgo66nSc82DJyY_uD-oLE3bM"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN or "YOUR_TELEGRAM" in TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "none":
    TELEGRAM_BOT_TOKEN = DEFAULT_REGISTERED_TOKEN

IS_TOKEN_PLACEHOLDER = False
bot = None
bot_init_error = None

bot = None


# =====================================================================
# HELPER UTILITIES
# =====================================================================

def format_rupiah(nominal: int) -> str:
    """Format integer ke format mata uang Rupiah Indonesia (Rp 1.000.000)."""
    try:
        val = int(nominal)
        return f"Rp {val:,}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"


def parse_nominal_string(text: str) -> Optional[int]:
    """
    Ekstrak nilai nominal uang dari teks dengan dukungan singkatan:
    - 500k / 500rb -> 500000
    - 1.5jt / 1.5m -> 1500000
    - 15.000 / Rp15.000 -> 15000
    """
    clean = text.strip().lower().replace("rp", "").replace(".", "").replace(",", "")
    match_k = re.match(r"^(\d+(?:\.\d+)?)(k|rb)$", clean)
    if match_k:
        return int(float(match_k.group(1)) * 1000)
    match_m = re.match(r"^(\d+(?:\.\d+)?)(jt|m)$", clean)
    if match_m:
        return int(float(match_m.group(1)) * 1000000)
    
    digits_only = re.sub(r"[^0-9]", "", clean)
    if digits_only:
        return int(digits_only)
    return None


def cari_nama_dompet(keyword: str, dompet_list: List[Dict[str, Any]]) -> Optional[str]:
    """Mencari nama dompet yang cocok berdasarkan kata kunci fleksibel."""
    if not keyword:
        return None
    kw = keyword.strip().lower()

    # Exact or alias mapping
    alias = {
        "tunai": "Kas Tunai",
        "cash": "Kas Tunai",
        "saku": "Kas Tunai",
        "bri": "Bank BRI",
        "atm": "Bank BRI",
        "tabungan": "Blu BCA - Tabungan",
        "blu tabungan": "Blu BCA - Tabungan",
        "blu bca tabungan": "Blu BCA - Tabungan",
        "blu": "Blu BCA - Tabungan",
        "bca": "Blu BCA - Tabungan",
        "saving": "Blu BCA - Tabungan",
        "blusaving": "Blu BCA - Tabungan",
        "darurat": "Blu BCA - Dana Darurat",
        "emergency": "Blu BCA - Dana Darurat",
        "dana darurat": "Blu BCA - Dana Darurat",
        "blu darurat": "Blu BCA - Dana Darurat",
        "blu bca dana darurat": "Blu BCA - Dana Darurat"
    }
    if kw in alias:
        target = alias[kw]
        for d in dompet_list:
            if d["nama"].lower() == target.lower():
                return d["nama"]

    # Substring search
    for d in dompet_list:
        if kw in d["nama"].lower() or d["nama"].lower() in kw:
            return d["nama"]

    return None


def parse_transaksi_command_text(teks: str, dompet_list: List[Dict[str, Any]], tipe_trx: str = "Pemasukan") -> Optional[Dict[str, Any]]:
    """
    Parser pintar untuk perintah /masuk dan /keluar Telegram.
    Mendukung multi-kata kategori seperti:
    - /masuk Blu BCA Dana Darurat 100000 Simpan uang sisa
    - /masuk "Dana Bermain" 50000 Jajan game
    - /keluar Dana Bermain 25000 Beli game di Steam
    - /keluar Makan 15000 Nasi Padang bri
    """
    import shlex
    try:
        parts = shlex.split(teks)
    except Exception:
        parts = teks.split()

    if not parts:
        return None

    # Cari token mana yang merupakan angka nominal
    nom_idx = -1
    nominal = None
    for i, p in enumerate(parts):
        parsed = parse_nominal_string(p)
        if parsed is not None and parsed > 0:
            nom_idx = i
            nominal = parsed
            break

    if nominal is None or nom_idx == -1:
        return None

    if nom_idx > 0:
        kategori_raw = " ".join(parts[:nom_idx]).strip()
        catatan_raw = " ".join(parts[nom_idx + 1:]).strip()
    else:
        # Nominal ada di posisi awal: e.g. /masuk 100000 Dana Darurat
        if len(parts) > 1:
            kategori_raw = parts[1].strip()
            catatan_raw = " ".join(parts[2:]).strip()
        else:
            kategori_raw = "Lain-Lain"
            catatan_raw = ""

    kategori = kategori_raw.title()
    catatan = catatan_raw
    target_dompet = "Kas Tunai"  # Default dasar

    # 1. Cek apakah kata terakhir di catatan adalah nama dompet eksplisit (e.g. "... bri", "... darurat")
    catatan_words = catatan.split()
    if catatan_words:
        last_word = catatan_words[-1]
        resolved_from_catatan = cari_nama_dompet(last_word, dompet_list)
        if resolved_from_catatan:
            target_dompet = resolved_from_catatan
            catatan = " ".join(catatan_words[:-1]).strip()

    # 2. Jika belum ditentukan oleh catatan, cek apakah kategori secara alami merujuk ke pos/dompet tertentu
    if target_dompet == "Kas Tunai":
        kat_lower = kategori.lower()
        dompet_by_kat = cari_nama_dompet(kat_lower, dompet_list)
        if dompet_by_kat:
            target_dompet = dompet_by_kat
        elif any(k in kat_lower for k in ["darurat", "emergency"]):
            target_dompet = "Blu BCA - Dana Darurat"
        elif any(k in kat_lower for k in ["tabungan", "blu", "bca", "saving"]):
            target_dompet = "Blu BCA - Tabungan"
        elif any(k in kat_lower for k in ["gaji", "salary", "payroll"]):
            target_dompet = "Bank BRI"

    return {
        "kategori": kategori,
        "nominal": nominal,
        "catatan": catatan,
        "target_dompet": target_dompet
    }


def buat_progress_bar_ascii(current: int, target: int, length: int = 10) -> str:
    """Membuat visualisasi progress bar karakter untuk pesan Telegram."""
    if target <= 0:
        return "[░" * length + "]"
    ratio = min(1.0, max(0.0, current / target))
    filled = int(round(ratio * length))
    bar = "▓" * filled + "░" * (length - filled)
    return f"[{bar}]"


# =====================================================================
# TELEGRAM BOT CONTROLLERS & HANDLERS
# =====================================================================

def init_telegram_bot():
    """Inisialisasi bot telebot dan daftarkan seluruh handler perintah."""
    global bot, bot_init_error
    if not TELEGRAM_BOT_TOKEN:
        bot_init_error = "Token belum disetel di TELEGRAM_BOT_TOKEN."
        return None

    try:
        import telebot
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, parse_mode="HTML")
        logger.info("[TELEGRAM BOT] Bot client berhasil diinisialisasi.")
        bot_init_error = None
    except Exception as e:
        bot_init_error = f"Gagal inisialisasi TeleBot (Pustaka pyTelegramBotAPI): {e}"
        logger.error(f"[TELEGRAM BOT] {bot_init_error}")
        return None

    @bot.message_handler(commands=["start", "help"])
    def handle_start(message):
        rekap = db.get_rekap_bulanan()
        status_db = db.get_status()
        storage_text = "🟢 Google Sheets" if status_db["is_sheets"] else "🔵 SQLite Local"

        pesan = (
            "🛵 <b>Finance Kepin - Personal Finance & ShopeeFood Tracker</b>\n"
            "<i>Sistem Multi-Dompet & Asisten Driver Pintar</i>\n"
            f"Database: <b>{storage_text}</b>\n\n"
            "<b>📋 DAFTAR PERINTAH BOT:</b>\n\n"
            "1️⃣ <b>Cek Saldo Semua Dompet:</b>\n"
            "<code>/dompet</code> atau <code>/saldo</code>\n"
            "<i>Melihat rincian saldo Kas Tunai, BRI, & Blu BCA</i>\n\n"
            "2️⃣ <b>Pemasukan Kas:</b>\n"
            "<code>/masuk [kategori] [nominal] [catatan] [dompet]</code>\n"
            "<i>Contoh:</i> <code>/masuk gaji 3000000 bonus bri</code>\n\n"
            "3️⃣ <b>Pengeluaran Kas:</b>\n"
            "<code>/keluar [kategori] [nominal] [catatan] [dompet]</code>\n"
            "<i>Contoh:</i> <code>/keluar makan 15000 warteg tunai</code>\n"
            "<i>Contoh:</i> <code>/keluar bensin 20000 pertalite bri</code>\n\n"
            "4️⃣ <b>Pindah Dana / Transfer Antar Dompet:</b>\n"
            "<code>/transfer [asal] [tujuan] [nominal] [catatan]</code>\n"
            "<i>Contoh setor tunai:</i> <code>/transfer tunai bri 40000 setor atm</code>\n"
            "<i>Contoh tabung ke Blu:</i> <code>/transfer bri blu 200000 alokasi tabungan</code>\n\n"
            "5️⃣ <b>Catat Tarikan ShopeeFood:</b>\n"
            "<code>/ojol [omzet] [bensin] [order] [odo_awal] [odo_akhir]</code>\n"
            "<i>Contoh:</i> <code>/ojol 61000 15000 7 4818 4907</code>\n"
            "<i>(Laba kas otomatis masuk ke Kas Tunai!)</i>\n\n"
            "6️⃣ <b>Rekap Bulanan:</b>\n"
            "<code>/rekap</code>\n\n"
            f"💰 <b>Total Saldo Bersih:</b> {format_rupiah(rekap['saldo_total'])}\n"
            f"🎯 <b>ShopeeFood Bulan Ini:</b> {format_rupiah(rekap['total_laba_kas_ojol'])} "
            f"({rekap['pct_utama']}% dari Rp1 Juta)"
        )
        bot.reply_to(message, pesan)

    @bot.message_handler(commands=["dompet", "saldo"])
    def handle_dompet(message):
        rekap = db.get_rekap_bulanan()
        dompet_list = rekap.get("dompet_list", [])

        pesan = "💳 <b>RINCIAN SALDO DOMPET & REKENING:</b>\n\n"
        for d in dompet_list:
            icon = d.get("icon", "🏦")
            nama = d["nama"]
            saldo = d["saldo_sekarang"]
            tipe = d.get("tipe", "")
            pesan += f"{icon} <b>{nama}</b> ({tipe}):\n   👉 <b>{format_rupiah(saldo)}</b>\n"

        pesan += "───────────────────────\n"
        pesan += f"💰 <b>TOTAL KESELURUHAN:</b> <b>{format_rupiah(rekap['saldo_total'])}</b>\n\n"
        pesan += "💡 <i>Gunakan /transfer untuk memindahkan uang antar rekening.</i>"
        bot.reply_to(message, pesan)

    @bot.message_handler(commands=["transfer"])
    def handle_transfer(message):
        # Format: /transfer [asal] [tujuan] [nominal] [catatan]
        # Contoh: /transfer tunai bri 40000 setor atm
        teks = message.text.replace("/transfer", "").strip()
        tokens = teks.split(maxsplit=3)
        if len(tokens) < 3:
            bot.reply_to(
                message,
                "⚠️ <b>Format perintah transfer salah!</b>\n\n"
                "Gunakan: <code>/transfer [asal] [tujuan] [nominal] [catatan]</code>\n"
                "<i>Contoh:</i> <code>/transfer tunai bri 40000 setor tunai ke atm</code>\n"
                "<i>Contoh:</i> <code>/transfer bri blu 200000 alokasi tabungan</code>"
            )
            return

        dompet_list = db.get_dompet()
        asal_nama = cari_nama_dompet(tokens[0], dompet_list)
        tujuan_nama = cari_nama_dompet(tokens[1], dompet_list)
        nominal = parse_nominal_string(tokens[2])
        catatan = tokens[3].strip() if len(tokens) >= 4 else ""

        if not asal_nama:
            bot.reply_to(message, f"❌ Dompet asal '<b>{tokens[0]}</b>' tidak dikenali. Ketik /dompet untuk melihat daftar nama.")
            return
        if not tujuan_nama:
            bot.reply_to(message, f"❌ Dompet tujuan '<b>{tokens[1]}</b>' tidak dikenali. Ketik /dompet untuk melihat daftar nama.")
            return
        if asal_nama == tujuan_nama:
            bot.reply_to(message, "❌ Dompet asal dan tujuan tidak boleh sama!")
            return
        if nominal is None or nominal <= 0:
            bot.reply_to(message, "❌ Nominal transfer tidak valid.")
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        db.add_transfer(
            dompet_asal=asal_nama,
            dompet_tujuan=tujuan_nama,
            nominal=nominal,
            catatan=catatan,
            tanggal=now_str
        )

        # Ambil saldo terbaru kedua dompet
        saldos = {d["nama"]: d["saldo_sekarang"] for d in db.get_saldo_dompet()}

        pesan = (
            "🔄 <b>Transfer Dana Berhasil Dicatat!</b>\n\n"
            f"📅 <b>Waktu:</b> {now_str}\n"
            f"💰 <b>Nominal:</b> <b>{format_rupiah(nominal)}</b>\n"
            f"📤 <b>Dari:</b> {asal_nama} (Sisa: {format_rupiah(saldos.get(asal_nama, 0))})\n"
            f"📥 <b>Ke:</b> {tujuan_nama} (Total: {format_rupiah(saldos.get(tujuan_nama, 0))})\n"
            f"📝 <b>Catatan:</b> {catatan or 'Transfer Antar Dompet'}\n"
            "───────────────────────\n"
            "✨ <i>Saldo masing-masing rekening telah disesuaikan otomatis!</i>"
        )
        bot.reply_to(message, pesan)

    @bot.message_handler(commands=["masuk"])
    def handle_masuk(message):
        # Format: /masuk [kategori] [nominal] [catatan] [opsional_dompet]
        teks = message.text.replace("/masuk", "").strip()
        if not teks:
            bot.reply_to(
                message,
                "⚠️ <b>Format perintah salah!</b>\n"
                "Gunakan: <code>/masuk [kategori] [nominal] [catatan]</code>\n\n"
                "<i>Contoh Tabungan:</i> <code>/masuk Blu BCA Tabungan 100000 Simpanan sisa</code>\n"
                "<i>Contoh Darurat:</i> <code>/masuk Blu BCA Dana Darurat 150000 Simpan dana darurat</code>\n"
                "<i>Contoh Gaji:</i> <code>/masuk Gaji 3000000 Bonus proyek</code>"
            )
            return

        dompet_list = db.get_dompet()
        parsed = parse_transaksi_command_text(teks, dompet_list, tipe_trx="Pemasukan")
        if not parsed or not parsed.get("nominal") or parsed["nominal"] <= 0:
            bot.reply_to(message, "❌ Format salah atau nominal tidak valid. Contoh: <code>/masuk Dana Darurat 100000</code>")
            return

        kategori = parsed["kategori"]
        nominal = parsed["nominal"]
        catatan = parsed["catatan"]
        target_dompet = parsed["target_dompet"]

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_id = db.add_transaksi(
            tipe="Pemasukan",
            kategori=kategori,
            nominal=nominal,
            catatan=catatan,
            tanggal=now_str,
            dompet=target_dompet
        )

        rekap = db.get_rekap_bulanan()
        saldos = {d["nama"]: d["saldo_sekarang"] for d in rekap.get("dompet_list", [])}

        balasan = (
            "✅ <b>Pemasukan Berhasil Dicatat!</b>\n\n"
            f"📅 <b>Waktu:</b> {now_str}\n"
            f"🏷️ <b>Kategori:</b> {kategori}\n"
            f"💰 <b>Nominal:</b> <b>{format_rupiah(nominal)}</b>\n"
            f"📥 <b>Masuk ke Dompet:</b> <b>{target_dompet}</b> (Saldo: {format_rupiah(saldos.get(target_dompet, 0))})\n"
            f"📝 <b>Catatan:</b> {catatan or '-'}\n"
            "───────────────────────\n"
            f"💳 <b>Total Saldo Bersih:</b> {format_rupiah(rekap['saldo_total'])}\n"
            f"📊 <b>Pemasukan Bulan Ini:</b> {format_rupiah(rekap['pemasukan_bulan_ini'])}"
        )
        bot.reply_to(message, balasan)

    @bot.message_handler(commands=["keluar"])
    def handle_keluar(message):
        # Format: /keluar [kategori] [nominal] [catatan] [opsional_dompet]
        teks = message.text.replace("/keluar", "").strip()
        if not teks:
            bot.reply_to(
                message,
                "⚠️ <b>Format perintah salah!</b>\n"
                "Gunakan: <code>/keluar [kategori] [nominal] [catatan]</code>\n\n"
                "<i>Contoh Darurat:</i> <code>/keluar Dana Darurat 50000 Tambal ban bocor</code>\n"
                "<i>Contoh Tabungan:</i> <code>/keluar Tabungan 200000 Keperluan mendesak</code>\n"
                "<i>Contoh Makan:</i> <code>/keluar Makan 15000 Nasi Padang</code>\n"
                "<i>Contoh (via BRI):</i> <code>/keluar Bensin 20000 Pertalite bri</code>"
            )
            return

        dompet_list = db.get_dompet()
        parsed = parse_transaksi_command_text(teks, dompet_list, tipe_trx="Pengeluaran")
        if not parsed or not parsed.get("nominal") or parsed["nominal"] <= 0:
            bot.reply_to(message, "❌ Format salah atau nominal tidak valid. Contoh: <code>/keluar Dana Bermain 25000 Steam</code>")
            return

        kategori = parsed["kategori"]
        nominal = parsed["nominal"]
        catatan = parsed["catatan"]
        target_dompet = parsed["target_dompet"]

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_id = db.add_transaksi(
            tipe="Pengeluaran",
            kategori=kategori,
            nominal=nominal,
            catatan=catatan,
            tanggal=now_str,
            dompet=target_dompet
        )

        rekap = db.get_rekap_bulanan()
        saldos = {d["nama"]: d["saldo_sekarang"] for d in rekap.get("dompet_list", [])}

        balasan = (
            "💸 <b>Pengeluaran Berhasil Dicatat!</b>\n\n"
            f"📅 <b>Waktu:</b> {now_str}\n"
            f"🏷️ <b>Kategori:</b> {kategori}\n"
            f"🔴 <b>Nominal:</b> <b>{format_rupiah(nominal)}</b>\n"
            f"📤 <b>Diambil Dari:</b> <b>{target_dompet}</b> (Sisa: {format_rupiah(saldos.get(target_dompet, 0))})\n"
            f"📝 <b>Catatan:</b> {catatan or '-'}\n"
            "───────────────────────\n"
            f"💳 <b>Total Saldo Bersih:</b> {format_rupiah(rekap['saldo_total'])}\n"
            f"📉 <b>Pengeluaran Bulan Ini:</b> {format_rupiah(rekap['pengeluaran_bulan_ini'])}"
        )
        bot.reply_to(message, balasan)

    @bot.message_handler(commands=["ojol"])
    def handle_ojol(message):
        # Format: /ojol [omzet] [bensin] [order] [odo_awal] [odo_akhir]
        raw_args = message.text.replace("/ojol", "").strip()
        tokens = [t.replace(".", "").replace(",", "") for t in raw_args.split()]

        numbers = []
        for t in tokens:
            parsed = parse_nominal_string(t)
            if parsed is not None:
                numbers.append(parsed)

        if len(numbers) < 5:
            bot.reply_to(
                message,
                "⚠️ <b>Format Data ShopeeFood Belum Lengkap!</b>\n\n"
                "Format: <code>/ojol [omzet] [bensin] [order] [odo_awal] [odo_akhir]</code>\n"
                "<i>Contoh:</i> <code>/ojol 61000 15000 7 4818 4907</code>"
            )
            return

        omzet_kotor = numbers[0]
        modal_bensin = numbers[1]
        jumlah_order = numbers[2]
        odo_awal = numbers[3]
        odo_akhir = numbers[4]

        if odo_akhir < odo_awal:
            bot.reply_to(
                message,
                f"❌ <b>Odometer Akhir ({odo_akhir}) tidak boleh lebih kecil dari Odometer Awal ({odo_awal})!</b>"
            )
            return

        today_str = datetime.now().strftime("%Y-%m-%d")
        log_res = db.add_log_ojol(
            tanggal=today_str,
            jumlah_order=jumlah_order,
            odo_awal=odo_awal,
            odo_akhir=odo_akhir,
            omzet_kotor=omzet_kotor,
            modal_bensin=modal_bensin,
            sync_transaksi=True
        )

        rekap = db.get_rekap_bulanan()

        bar_milestone = buat_progress_bar_ascii(rekap['total_laba_kas_ojol'], rekap['target_milestone'])
        bar_utama = buat_progress_bar_ascii(rekap['total_laba_kas_ojol'], rekap['target_utama'])

        pesan = (
            "🛵 <b>Laporan Narik ShopeeFood Tersimpan!</b>\n\n"
            f"📅 <b>Tanggal:</b> {today_str}\n"
            f"📦 <b>Order Selesai:</b> {jumlah_order} pesanan\n"
            f"🛣️ <b>Jarak Tempuh:</b> {log_res['jarak_km']} km <i>(Odo: {odo_awal} ➡️ {odo_akhir})</i>\n"
            f"💵 <b>Omzet Kotor:</b> {format_rupiah(omzet_kotor)}\n"
            f"⛽ <b>Modal Bensin Kas:</b> {format_rupiah(modal_bensin)}\n"
            "───────────────────────\n"
            f"💰 <b>Laba Kas di Tangan:</b> <b>{format_rupiah(log_res['laba_kas'])}</b>\n"
            f"🔧 <b>Cadangan Servis (Rp150/km):</b> {format_rupiah(log_res['dana_servis'])}\n"
            f"⛽ <b>Estimasi BBM Riil (54 km/L):</b> {log_res['estimasi_liter']} L (~{format_rupiah(log_res['estimasi_bensin_riil'])})\n"
            f"💎 <b>Laba Bersih Murni:</b> <b>{format_rupiah(log_res['laba_bersih_murni'])}</b>\n\n"
            f"📊 <b>Efisiensi Rasio:</b> {format_rupiah(log_res['rp_per_km'])}/km\n"
            f"Status: <b>{log_res['indikator_badge']}</b>\n"
            "───────────────────────\n"
            "🎯 <b>Pencapaian Target Bulanan:</b>\n"
            f"• Milestone 1: {bar_milestone} {rekap['pct_milestone']}%\n"
            f"• Target Utama: {bar_utama} {rekap['pct_utama']}%\n"
        )

        if rekap["sisa_target_utama"] > 0:
            pesan += f"\n🚀 <i>Kurang {format_rupiah(rekap['sisa_target_utama'])} lagi (~{rekap['shift_dibutuhkan']} shift lagi). Semangat!</i>\n"
        else:
            pesan += "\n🎉 <b>LUAR BIASA! Target Rp1 Juta bulan ini sudah tembus! 🏆</b>\n"

        pesan += "\n💵 <i>Uang kas bersih Rp " + f"{log_res['laba_kas']:,}".replace(",", ".") + " otomatis masuk ke <b>Kas Tunai</b>!</i>"
        bot.reply_to(message, pesan)

    @bot.message_handler(commands=["rekap"])
    def handle_rekap(message):
        rekap = db.get_rekap_bulanan()
        status_db = db.get_status()
        storage_text = "Google Sheets" if status_db["is_sheets"] else "SQLite Local"

        bar_utama = buat_progress_bar_ascii(rekap['total_laba_kas_ojol'], rekap['target_utama'])
        bar_milestone = buat_progress_bar_ascii(rekap['total_laba_kas_ojol'], rekap['target_milestone'])

        pesan = (
            f"📊 <b>REKAP KEUANGAN & SHOPEEFOOD ({rekap['bulan']})</b>\n"
            f"<i>Database: {storage_text}</i>\n\n"
            "💳 <b>SALDO KESELURUHAN:</b>\n"
            f"• Total Saldo Bersih: <b>{format_rupiah(rekap['saldo_total'])}</b>\n"
            f"• Pemasukan Bulan Ini: {format_rupiah(rekap['pemasukan_bulan_ini'])}\n"
            f"• Pengeluaran Bulan Ini: {format_rupiah(rekap['pengeluaran_bulan_ini'])}\n\n"
            "🛵 <b>SHOPEEFOOD BULAN INI:</b>\n"
            f"• Total Laba Kas: <b>{format_rupiah(rekap['total_laba_kas_ojol'])}</b>\n"
            f"• Total Omzet: {format_rupiah(rekap['total_omzet_ojol'])}\n"
            f"• Total Bensin Kas: {format_rupiah(rekap['total_bensin_kas_ojol'])}\n"
            f"• Total Order: {rekap['total_order_ojol']} trip\n"
            f"• Total Jarak: {rekap['total_km_ojol']} km\n"
            f"• Cadangan Servis: {format_rupiah(rekap['total_dana_servis'])}\n"
            f"• Laba Bersih Murni: {format_rupiah(rekap['total_laba_bersih_murni'])}\n"
            f"• Rata-rata Rasio: {format_rupiah(rekap['rata_rp_per_km'])}/km\n\n"
            "🎯 <b>TARGET SHOPEEFOOD (Rp 1.000.000):</b>\n"
            f"• Milestone (500k): {bar_milestone} {rekap['pct_milestone']}%\n"
            f"• Target Utama: {bar_utama} {rekap['pct_utama']}%\n"
        )

        if rekap["sisa_target_utama"] > 0:
            pesan += f"• Kurang: <b>{format_rupiah(rekap['sisa_target_utama'])}</b> (~{rekap['shift_dibutuhkan']} shift lagi)\n"
        else:
            pesan += "• Status: <b>🎉 Target Rp1 Juta Sudah Tercapai!</b>\n"

        bot.reply_to(message, pesan)

    return bot


def run_telegram_bot_background():
    """Menjalankan bot polling di background thread tanpa memblokir server Flask."""
    if not bot:
        return

    def polling_worker():
        logger.info("[TELEGRAM BOT] Memulai polling thread...")
        while True:
            try:
                bot.infinity_polling(timeout=15, long_polling_timeout=20)
            except Exception as e:
                logger.error(f"[TELEGRAM BOT] Polling error terdeteksi: {e}. Mengulang dalam 5 detik...")
                import time
                time.sleep(5)

    thread = threading.Thread(target=polling_worker, daemon=True, name="TelegramBotPollingThread")
    thread.start()


init_telegram_bot()

USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() in ["true", "1", "yes"]
if not USE_WEBHOOK:
    run_telegram_bot_background()
else:
    logger.info("[TELEGRAM BOT] Mode Webhook aktif (Background polling dinonaktifkan).")


# =====================================================================
# FLASK WEB ROUTES & API
# =====================================================================

@app.context_processor
def utility_processor():
    """Fungsi helper template Jinja2 untuk format angka dan status."""
    return {
        "format_rupiah": format_rupiah,
        "round": round,
        "max": max,
        "min": min
    }


@app.route("/")
def index():
    """Halaman Dashboard Utama."""
    rekap = db.get_rekap_bulanan()
    transaksi = db.get_transaksi(limit=15)
    log_ojol = db.get_log_ojol(limit=15)
    storage_status = db.get_status()
    dompet_list = rekap.get("dompet_list", [])
    today_str = datetime.now().strftime("%Y-%m-%d")

    return render_template(
        "index.html",
        rekap=rekap,
        transaksi=transaksi,
        log_ojol=log_ojol,
        dompet_list=dompet_list,
        storage_status=storage_status,
        today_str=today_str,
        bot_active=not IS_TOKEN_PLACEHOLDER
    )


@app.route("/api/summary")
def api_summary():
    """Mengembalikan ringkasan rekap bulanan dalam format JSON."""
    bulan = request.args.get("bulan")
    rekap = db.get_rekap_bulanan(bulan=bulan)
    status_db = db.get_status()
    return jsonify({
        "success": True,
        "data": rekap,
        "storage": status_db
    })


@app.route("/api/charts")
def api_charts():
    """Mengembalikan data yang siap divisualisasikan oleh Chart.js."""
    bulan = request.args.get("bulan")
    chart_data = db.get_chart_data(bulan=bulan)
    return jsonify({
        "success": True,
        "data": chart_data
    })


@app.route("/api/dompet", methods=["GET", "POST"])
def api_dompet():
    """Melihat daftar dompet atau menambahkan kantong/rekening baru."""
    if request.method == "POST":
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        nama = data.get("nama", "").strip()
        tipe = data.get("tipe", "bluSaving").strip()
        saldo_awal = parse_nominal_string(str(data.get("saldo_awal", 0))) or 0
        icon = data.get("icon", "🏦").strip() or "🏦"
        catatan = data.get("catatan", "").strip()

        if not nama:
            if is_json:
                return jsonify({"success": False, "error": "Nama dompet tidak boleh kosong"}), 400
            flash("Nama dompet tidak boleh kosong!", "danger")
            return redirect(url_for("index"))

        new_id = db.add_dompet(nama, tipe, saldo_awal, icon, catatan)

        if is_json:
            return jsonify({"success": True, "id": new_id, "message": "Dompet berhasil ditambahkan"})
        flash(f"Dompet/Kantong '{nama}' berhasil dibuat!", "success")
        return redirect(url_for("index"))

    # GET
    saldos = db.get_saldo_dompet()
    return jsonify({"success": True, "data": saldos})


@app.route("/api/dompet/update/<int:dompet_id>", methods=["POST"])
def api_update_dompet(dompet_id):
    """Memperbarui nama, saldo awal, tipe, atau icon dompet."""
    is_json = request.is_json
    data = request.get_json() if is_json else request.form

    nama = data.get("nama", "").strip()
    saldo_awal = parse_nominal_string(str(data.get("saldo_awal", 0))) or 0
    tipe = data.get("tipe", "").strip() or None
    icon = data.get("icon", "").strip() or None
    catatan = data.get("catatan", "").strip() or None

    if not nama:
        if is_json:
            return jsonify({"success": False, "error": "Nama dompet tidak boleh kosong"}), 400
        flash("Nama dompet tidak boleh kosong!", "danger")
        return redirect(url_for("index"))

    success = db.update_dompet(dompet_id, nama, saldo_awal, tipe, icon, catatan)

    if is_json:
        return jsonify({"success": success})
    if success:
        flash(f"Dompet '{nama}' berhasil diperbarui!", "success")
    else:
        flash("Gagal memperbarui dompet.", "danger")
    return redirect(url_for("index"))


@app.route("/api/dompet/delete/<int:dompet_id>", methods=["POST", "DELETE"])
def api_delete_dompet(dompet_id):
    """Menghapus dompet/kantong kustom (Kas Tunai & BRI dilindungi)."""
    success = db.delete_dompet(dompet_id)
    if request.is_json or request.method == "DELETE":
        return jsonify({"success": success})

    if success:
        flash("Dompet berhasil dihapus.", "info")
    else:
        flash("Dompet inti tidak dapat dihapus.", "danger")
    return redirect(url_for("index"))


@app.route("/api/transfer", methods=["POST"])
def api_transfer():
    """Memindahkan saldo antar dompet/kantong (setor tunai, alokasi tabungan, dll)."""
    is_json = request.is_json
    data = request.get_json() if is_json else request.form

    dompet_asal = data.get("dompet_asal", "").strip()
    dompet_tujuan = data.get("dompet_tujuan", "").strip()
    nominal = parse_nominal_string(str(data.get("nominal", 0))) or 0
    catatan = data.get("catatan", "").strip()
    tanggal = data.get("tanggal", "").strip() or None

    if not dompet_asal or not dompet_tujuan:
        err = "Pilih dompet asal dan dompet tujuan transfer!"
        if is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(err, "danger")
        return redirect(url_for("index"))

    if dompet_asal == dompet_tujuan:
        err = "Dompet asal dan tujuan tidak boleh sama!"
        if is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(err, "danger")
        return redirect(url_for("index"))

    if nominal <= 0:
        err = "Nominal transfer harus lebih besar dari 0!"
        if is_json:
            return jsonify({"success": False, "error": err}), 400
        flash(err, "danger")
        return redirect(url_for("index"))

    trans_id = db.add_transfer(dompet_asal, dompet_tujuan, nominal, catatan, tanggal)

    if is_json:
        return jsonify({"success": True, "id": trans_id, "message": "Transfer berhasil dicatat"})

    flash(f"Pindah dana {format_rupiah(nominal)} dari {dompet_asal} ke {dompet_tujuan} berhasil!", "success")
    return redirect(url_for("index"))


@app.route("/api/transaksi", methods=["GET", "POST"])
def api_transaksi():
    """Melihat daftar transaksi atau menambahkan transaksi umum baru."""
    if request.method == "POST":
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        tipe = data.get("tipe", "Pengeluaran").strip().title()
        kategori = data.get("kategori", "Umum").strip().title()
        nominal_raw = data.get("nominal", 0)
        nominal = parse_nominal_string(str(nominal_raw)) or 0
        catatan = data.get("catatan", "").strip()
        tanggal = data.get("tanggal", "").strip() or None
        dompet = data.get("dompet", "Kas Tunai").strip()

        if nominal <= 0:
            if is_json:
                return jsonify({"success": False, "error": "Nominal harus lebih besar dari 0"}), 400
            flash("Nominal transaksi harus lebih dari 0!", "danger")
            return redirect(url_for("index"))

        new_id = db.add_transaksi(tipe, kategori, nominal, catatan, tanggal, dompet=dompet)

        if is_json:
            return jsonify({"success": True, "id": new_id, "message": "Transaksi berhasil disimpan"})
        
        flash(f"Transaksi {tipe} ({format_rupiah(nominal)}) dicatat pada dompet '{dompet}'!", "success")
        return redirect(url_for("index"))

    # GET
    limit = request.args.get("limit", type=int)
    bulan = request.args.get("bulan")
    items = db.get_transaksi(limit=limit, bulan=bulan)
    return jsonify({"success": True, "data": items})


@app.route("/api/transaksi/delete/<int:transaksi_id>", methods=["POST", "DELETE"])
def api_delete_transaksi(transaksi_id):
    """Menghapus baris transaksi umum."""
    success = db.delete_transaksi(transaksi_id)
    if request.is_json or request.method == "DELETE":
        return jsonify({"success": success})
    
    if success:
        flash("Transaksi berhasil dihapus.", "info")
    else:
        flash("Gagal menghapus transaksi.", "danger")
    return redirect(url_for("index"))


@app.route("/api/calculate_ojol", methods=["POST"])
def api_calculate_ojol():
    """Endpoint utilitas untuk kalkulasi live saat user mengetik di form web."""
    try:
        data = request.get_json() or request.form
        odo_awal = int(data.get("odo_awal", 0))
        odo_akhir = int(data.get("odo_akhir", 0))
        omzet = int(data.get("omzet_kotor", 0))
        bensin = int(data.get("modal_bensin", 0))

        metrik = hitung_metrik_ojol(odo_awal, odo_akhir, omzet, bensin)
        return jsonify({"success": True, "data": metrik})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/ojol", methods=["GET", "POST"])
def api_ojol():
    """Melihat riwayat atau menambahkan catatan narik ShopeeFood baru."""
    if request.method == "POST":
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        tanggal = data.get("tanggal", "").strip() or datetime.now().strftime("%Y-%m-%d")
        jumlah_order = int(data.get("jumlah_order", 0))
        odo_awal = int(data.get("odo_awal", 0))
        odo_akhir = int(data.get("odo_akhir", 0))
        omzet_kotor = parse_nominal_string(str(data.get("omzet_kotor", 0))) or 0
        modal_bensin = parse_nominal_string(str(data.get("modal_bensin", 0))) or 0

        if odo_akhir < odo_awal:
            err = "Odometer akhir tidak boleh lebih kecil dari odometer awal!"
            if is_json:
                return jsonify({"success": False, "error": err}), 400
            flash(err, "danger")
            return redirect(url_for("index"))

        if omzet_kotor <= 0:
            err = "Omzet kotor harus lebih besar dari 0!"
            if is_json:
                return jsonify({"success": False, "error": err}), 400
            flash(err, "danger")
            return redirect(url_for("index"))

        res = db.add_log_ojol(
            tanggal=tanggal,
            jumlah_order=jumlah_order,
            odo_awal=odo_awal,
            odo_akhir=odo_akhir,
            omzet_kotor=omzet_kotor,
            modal_bensin=modal_bensin,
            sync_transaksi=True
        )

        if is_json:
            return jsonify({"success": True, "data": res, "message": "Log ShopeeFood berhasil disimpan"})

        flash(f"Data ShopeeFood berhasil dicatat! Laba Kas: {format_rupiah(res['laba_kas'])} otomatis masuk ke Kas Tunai.", "success")
        return redirect(url_for("index"))

    # GET
    limit = request.args.get("limit", type=int)
    bulan = request.args.get("bulan")
    items = db.get_log_ojol(limit=limit, bulan=bulan)
    return jsonify({"success": True, "data": items})


@app.route("/api/ojol/delete/<int:ojol_id>", methods=["POST", "DELETE"])
def api_delete_ojol(ojol_id):
    """Menghapus entri log ShopeeFood."""
    success = db.delete_log_ojol(ojol_id)
    if request.is_json or request.method == "DELETE":
        return jsonify({"success": success})

    if success:
        flash("Log ShopeeFood berhasil dihapus.", "info")
    else:
        flash("Gagal menghapus log ShopeeFood.", "danger")
    return redirect(url_for("index"))


@app.route("/webhook", methods=["POST"])
def webhook():
    """Webhook endpoint untuk Telegram jika dijalankan di server dengan domain SSL."""
    global bot
    if not bot:
        init_telegram_bot()

    if not bot:
        return "Bot is not configured", 400

    try:
        ct = request.headers.get("content-type", "").lower()
        if "application/json" in ct or request.is_json:
            import telebot
            json_string = request.get_data().decode("utf-8")
            if json_string and json_string.strip():
                update = telebot.types.Update.de_json(json_string)
                if update:
                    bot.process_new_updates([update])
            return "OK", 200
        return "Forbidden", 403
    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)
        return "Error", 500


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """Mengaktifkan Webhook Telegram secara instan dari browser."""
    global bot
    if not bot:
        init_telegram_bot()

    if not bot:
        return jsonify({
            "success": False,
            "error": "Bot belum dikonfigurasi",
            "detail": bot_init_error or "Gagal inisialisasi bot telebot",
            "token_masked": TELEGRAM_BOT_TOKEN[:10] + "..." if TELEGRAM_BOT_TOKEN else "None"
        }), 400

    host = request.host_url.rstrip("/")
    if host.startswith("http://") and ("pythonanywhere.com" in host or "onrender.com" in host):
        host = host.replace("http://", "https://")

    webhook_url = f"{host}/webhook"
    try:
        bot.remove_webhook()
        success = bot.set_webhook(url=webhook_url)
        return jsonify({
            "success": success,
            "webhook_url": webhook_url,
            "message": "✅ Webhook Telegram berhasil aktif! Bot kini merespons 24 jam nonstop."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =====================================================================
# SERVER LAUNCHER
# =====================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", 5000)))
    debug = os.getenv("FLASK_DEBUG", "False").lower() in ["true", "1", "yes"]

    logger.info("================================================================")
    logger.info("🚀 FINANCE KEPIN - PERSONAL FINANCE & SHOPEEFOOD TRACKER BERJALAN")
    logger.info(f"🌐 Akses Web Dashboard di: http://127.0.0.1:{port}")
    status_db = db.get_status()
    logger.info(f"💾 Storage Mode: {status_db['mode'].upper()} ({status_db['detail']})")
    if IS_TOKEN_PLACEHOLDER:
        logger.info("🤖 Bot Telegram: Mode siaga (Isi TELEGRAM_BOT_TOKEN di .env untuk mengaktifkan)")
    else:
        logger.info("🤖 Bot Telegram: AKTIF (Polling background berjalan)")
    logger.info("================================================================")

    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
