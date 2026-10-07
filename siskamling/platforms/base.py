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


def build_welcome_text(bold: Callable[[str], str]) -> str:
    return (
        f"🏘️ {bold('Siskamling Pasar')}\n\n"
        "Pos ronda otomatis untuk mendeteksi saham berisiko pom-pom di IDX.\n\n"
        "• `/ronda TICKER` — Periksa skor risiko suatu saham (contoh: `/ronda BBCA`)\n"
        "• Patroli sore otomatis setiap hari bursa jam 16:30 WIB.\n\n"
        f"⚠️ {bold('Bukan saran investasi.')} Data publik bersumber dari Sectors.app."
    )


def build_report_messages(channel: Channel, triggered_alerts: list[dict[str, Any]]) -> list[str]:
    """Susun laporan ronda memakai markup tebal milik kanal."""
    bold = channel.bold

    if not triggered_alerts:
        return [
            f"🛡️ {bold('Laporan Ronda Sore')}\n\n"
            "Situasi pasar terpantau kondusif. Tidak ada saham mencurigakan pada jajaran top gainers hari ini."
        ]

    messages = [
        f"🔔 {bold(f'Laporan Ronda Sore — {date.today().isoformat()}')}\n\n"
        f"Perhatian warga, terdeteksi {bold(f'{len(triggered_alerts)} saham')} masuk radar risiko:\n"
    ]
    messages.extend(alert["narration"] for alert in sorted(triggered_alerts, key=lambda alert: -alert["score"]))
    return messages


def dispatch_report(channels: Iterable[Channel], triggered_alerts: list[dict[str, Any]]) -> None:
    """Siarkan laporan ke seluruh kanal yang terkonfigurasi (fan-out)."""
    for channel in channels:
        recipient = channel.default_recipient()
        if not channel.is_configured() or not recipient:
            continue

        messages = build_report_messages(channel, triggered_alerts)
        for index, message in enumerate(messages):
            channel.send(recipient, message)
            if index < len(messages) - 1:
                time.sleep(1)  # jeda antar-pesan untuk menghindari rate limit


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
