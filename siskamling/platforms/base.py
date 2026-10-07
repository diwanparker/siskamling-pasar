"""Abstraksi kanal notifikasi & interaksi (Open/Closed Principle).

Menambah platform baru (mis. Slack, WhatsApp) cukup dengan:
1. Buat modul baru di paket ini berisi subclass `Channel` (dan `InteractiveChannel`
   bila platform mendukung perintah masuk).
2. Hias kelas dengan `@register_channel`.

Logika broadcast, pembentukan pesan, dan routing perintah di modul ini tidak
perlu diubah — tertutup untuk modifikasi, terbuka untuk ekstensi.
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


@dataclass
class ReplyContext:
    """Konteks balasan platform-agnostik untuk satu perintah masuk.

    Atribut:
        send: Kirim satu pesan balasan ke pengirim asal.
        bold: Bungkus teks dengan markup tebal milik platform.
    """

    send: Callable[[str], None]
    bold: Callable[[str], str]
    user_id: str = ""


class Channel(ABC):
    """Kontrak satu platform notifikasi."""

    name: str = "channel"

    @abstractmethod
    def is_configured(self) -> bool:
        """True bila kredensial minimum platform tersedia di environment."""

    @abstractmethod
    def default_recipient(self) -> str:
        """Tujuan bawaan untuk broadcast (chat/channel id)."""

    @abstractmethod
    def send(self, recipient: str, text: str) -> Any:
        """Kirim satu pesan teks ke recipient (pecah otomatis bila platform membatasi panjang)."""

    @abstractmethod
    def bold(self, text: str) -> str:
        """Bungkus teks dengan markup tebal milik platform."""


class PlainTextChannel(Channel):
    """Kanal virtual tanpa jaringan: merender pesan sebagai teks polos (tanpa markup).

    Dipakai untuk menghasilkan narasi mentah pada respons API/cURL tanpa perlu
    kredensial Telegram/Discord. Tidak didaftarkan di registry, sehingga tidak
    pernah ikut ter-broadcast.
    """

    name = "plain"

    def is_configured(self) -> bool:
        return True

    def default_recipient(self) -> str:
        return ""

    def send(self, recipient: str, text: str) -> None:
        return None

    def bold(self, text: str) -> str:
        return text


class InteractiveChannel(Channel):
    """Kanal yang juga mendengarkan perintah masuk secara live."""

    @abstractmethod
    def run_listener(self, router: "CommandRouter") -> None:
        """Dengarkan perintah masuk dan teruskan ke router (blocking)."""


class CommandRouter:
    """Router perintah platform-agnostik.

    Menambah perintah baru tidak menyentuh kode kanal; menambah kanal baru tidak
    menyentuh router.
    """

    def __init__(self, evaluate: Callable[[str], dict[str, Any]]) -> None:
        self._evaluate = evaluate

    def handle(self, text: str, ctx: ReplyContext) -> None:
        tokens = text.strip().split()
        if not tokens:
            return

        # Buang slash, dan suffix mention Discord (mis. "/ronda@Bot").
        command = tokens[0].lstrip("/").split("@", 1)[0].lower()

        if command == "ronda":
            self._handle_ronda(tokens, ctx)
        elif command in {"aset", "portofolio", "watchlist"}:
            self._handle_aset(tokens, text, ctx)
        elif command in {"start", "help"}:
            ctx.send(build_welcome_text(ctx.bold))

    def _handle_ronda(self, tokens: list[str], ctx: ReplyContext) -> None:
        if len(tokens) < 2:
            ctx.send("ℹ️ Format perintah: `/ronda TICKER` (contoh: `/ronda BBCA` atau `/ronda UNSP`)")
            return

        ticker = tokens[1].upper()
        ctx.send(f"⏳ Sedang patroli ke pos saham {ctx.bold(ticker)}...")
        result = self._evaluate(ticker)
        if "error" in result:
            ctx.send(f"❌ {ctx.bold(ticker)}: {result['error']}")
        else:
            ctx.send(result["narration"])

    def _handle_aset(self, tokens: list[str], full_text: str, ctx: ReplyContext) -> None:
        user_id = ctx.user_id or "default"
        from ..portfolio import add_ticker, clean_ticker, get_portfolio, remove_ticker, set_portfolio

        if len(tokens) == 1:
            current = get_portfolio(user_id)
            if not current:
                ctx.send(
                    f"📭 {ctx.bold('Anda belum mendaftarkan saham portofolio ke pos ronda.')}\n\n"
                    "Ketik contoh: `/aset BBRI, BBCA, TLKM` untuk mendaftarkan saham yang Anda miliki agar diawasi setiap hari."
                )
            else:
                formatted = "\n".join(f"• {ctx.bold(s)}" for s in current)
                ctx.send(
                    f"📋 {ctx.bold('Saham Portofolio yang Sedang Diawasi:')}\n\n"
                    f"{formatted}\n\n"
                    "Gunakan `/aset tambah TICKER` untuk menambah atau `/aset hapus TICKER` untuk menghapus."
                )
            return

        action = tokens[1].lower()
        if action == "tambah" and len(tokens) >= 3:
            sym = clean_ticker(tokens[2])
            updated = add_ticker(user_id, tokens[2])
            ctx.send(f"✅ Saham {ctx.bold(sym)} berhasil ditambahkan ke radar pantauan Anda!")
            return
        elif action == "hapus" and len(tokens) >= 3:
            sym = clean_ticker(tokens[2])
            remove_ticker(user_id, tokens[2])
            ctx.send(f"🗑️ Saham {ctx.bold(sym)} telah dihapus dari radar pantauan Anda.")
            return

        # Anggap seluruh argumen setelah /aset adalah daftar ticker
        raw_tickers = full_text.split(None, 1)[1] if len(tokens) > 1 else ""
        raw_list = [item.strip() for item in raw_tickers.replace(",", " ").split() if item.strip()]
        if not raw_list:
            ctx.send("ℹ️ Format: `/aset BBRI, BBCA, TLKM`")
            return

        updated = set_portfolio(user_id, raw_list)
        formatted = "\n".join(f"• {ctx.bold(s)}" for s in updated)
        ctx.send(
            f"✅ {ctx.bold(f'Berhasil mendaftarkan {len(updated)} saham portofolio:')}\n\n"
            f"{formatted}\n\n"
            "🛡️ Pos ronda akan otomatis mengawasi saham Anda setiap jadwal patroli harian!"
        )


def build_welcome_text(bold: Callable[[str], str]) -> str:
    return (
        f"🏘️ {bold('Siskamling Pasar — Radar Saham Anti-Pom-Pom')}\n\n"
        "Pos ronda otomatis bursa IDX untuk mengawal saham portofolio Anda dan memindai potensi risiko pasar.\n\n"
        f"📌 {bold('Perintah Warga:')}\n"
        "• `/aset BBRI, BBCA, TLKM` — Daftarkan saham yang Anda miliki untuk diawasi rutin\n"
        "• `/aset` — Lihat daftar saham portofolio Anda yang sedang dipantau\n"
        "• `/aset tambah TICKER` / `/aset hapus TICKER` — Tambah atau hapus saham\n"
        "• `/ronda TICKER` — Periksa skor risiko saham secara instan (contoh: `/ronda BBRI`)\n\n"
        "🔔 Patroli harian otomatis berjalan tiap sore penutupan bursa (16:30 WIB) & pagi (08:30 WIB).\n\n"
        f"⚠️ {bold('Bukan saran investasi.')} Data bersumber dari Sectors.app."
    )


def build_report_messages(channel: Channel, triggered_alerts: list[dict[str, Any]]) -> list[str]:
    """Susun laporan ronda memakai markup tebal milik kanal."""
    bold = channel.bold

    if not triggered_alerts:
        return [
            f"🛡️ {bold('Laporan Ronda Sore')}\n\n"
            "Situasi pasar terpantau kondusif. Tidak ada saham mencurigakan pada jajaran top gainers hari ini."
        ]

    ranked = sorted(triggered_alerts, key=lambda alert: -alert["score"])
    scoreboard = "\n".join(
        f"{rank}. {bold(alert['symbol'].replace('.JK', ''))} — {alert['score']}/100"
        for rank, alert in enumerate(ranked, start=1)
    )
    messages = [
        f"🔔 {bold(f'Laporan Ronda Sore — {date.today().isoformat()}')}\n\n"
        f"Perhatian warga, terdeteksi {bold(f'{len(ranked)} saham')} masuk radar risiko:\n\n"
        f"{scoreboard}"
    ]
    messages.extend(alert["narration"] for alert in ranked)
    return messages


def build_briefing_messages(channel: Channel, candidates: list[dict[str, Any]]) -> list[str]:
    """Susun briefing pagi (kandidat fundamental) memakai markup tebal milik kanal."""
    bold = channel.bold

    if not candidates:
        return [
            f"🌅 {bold('Briefing Pagi')}\n\n"
            "Tidak ada kandidat fundamental yang lolos kriteria hari ini."
        ]

    ranked = sorted(candidates, key=lambda item: -(item.get("dividend_yield") or 0))
    scoreboard = "\n".join(
        f"{rank}. {bold(item['symbol'].replace('.JK', ''))} — yield "
        f"{(item.get('dividend_yield') or 0) * 100:.1f}%"
        for rank, item in enumerate(ranked, start=1)
    )
    messages = [
        f"🌅 {bold(f'Briefing Pagi — {date.today().isoformat()}')}\n\n"
        f"Kandidat fundamental sehat ({bold(f'{len(ranked)} saham')}):\n\n{scoreboard}"
    ]
    messages.extend(item["narration"] for item in ranked)
    messages.append("⚠️ Ini bukan saran investasi. Data dari Sectors.app.")
    return messages


def dispatch(channels: Iterable[Channel], build_messages: Callable[[Channel], list[str]]) -> None:
    """Siarkan kumpulan pesan (dibangun per-kanal) ke seluruh kanal terkonfigurasi."""
    for channel in channels:
        recipient = channel.default_recipient()
        if not channel.is_configured() or not recipient:
            continue

        messages = build_messages(channel)
        for index, message in enumerate(messages):
            channel.send(recipient, message)
            if index < len(messages) - 1:
                time.sleep(1)  # jeda antar-pesan untuk menghindari rate limit


def dispatch_report(channels: Iterable[Channel], triggered_alerts: list[dict[str, Any]]) -> None:
    """Siarkan laporan risiko ke seluruh kanal yang terkonfigurasi (fan-out)."""
    dispatch(channels, lambda channel: build_report_messages(channel, triggered_alerts))


def dispatch_briefing(channels: Iterable[Channel], candidates: list[dict[str, Any]]) -> None:
    """Siarkan briefing pagi ke seluruh kanal yang terkonfigurasi (fan-out)."""
    dispatch(channels, lambda channel: build_briefing_messages(channel, candidates))


def run_listeners(channels: Iterable[Channel], router: CommandRouter) -> None:
    """Jalankan semua listener kanal interaktif secara bersamaan."""
    active = [channel for channel in channels if isinstance(channel, InteractiveChannel) and channel.is_configured()]
    if not active:
        raise RuntimeError(
            "Tidak ada platform interaktif yang terkonfigurasi "
            "(butuh TELEGRAM_BOT_TOKEN atau DISCORD_BOT_TOKEN)"
        )

    for channel in active[:-1]:
        thread = threading.Thread(
            target=channel.run_listener,
            args=(router,),
            name=f"{channel.name}-listener",
            daemon=True,
        )
        thread.start()
        logger.info("Listener %s berjalan di background", channel.name)

    active[-1].run_listener(router)


# ─── Registry Kanal (titik ekstensi) ───────────────────────────────

_CHANNEL_TYPES: list[type[Channel]] = []


def register_channel(channel_type: type[Channel]) -> type[Channel]:
    """Dekorator: daftarkan kanal tanpa mengubah kode dispatch."""
    _CHANNEL_TYPES.append(channel_type)
    return channel_type


def all_channels() -> list[Channel]:
    """Instansiasi seluruh kanal yang terdaftar."""
    return [channel_type() for channel_type in _CHANNEL_TYPES]
