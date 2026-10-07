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
        user_id: Identitas pengirim di platform asal (chat id / user id).
        platform: Nama kanal pengirim (mis. "telegram", "discord") untuk routing pesan langsung.
    """

    send: Callable[[str], None]
    bold: Callable[[str], str]
    user_id: str = ""
    platform: str = ""


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

    def send_to_user(self, user_id: str, text: str) -> Any:
        """Kirim pesan langsung ke seorang pengguna (bawaan: id diperlakukan sebagai recipient).

        Platform yang tidak bisa mengirim ke user id mentah (mis. Discord, yang
        butuh membuka DM channel lebih dulu) menimpa metode ini.
        """
        return self.send(user_id, text)


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
            ctx.send("ℹ️ Format perintah: `/ronda TICKER` (contoh: `/ronda BBCA` atau `/ronda BBRI`)")
            return

        ticker = tokens[1].upper().replace(".JK", "")

        # Antisipasi jika pengguna mengetik /ronda aset atau /ronda portofolio
        if ticker in {"ASET", "PORTOFOLIO", "PORTFOLIO", "WATCHLIST"}:
            ctx.send(
                f"💡 {ctx.bold('Info Pos Ronda:')}\n\n"
                "Perintah `/ronda` digunakan untuk meronda 1 kode saham spesifik (contoh: `/ronda BBRI`).\n\n"
                "Untuk melihat atau mendaftarkan saham portofolio yang ingin diawasi rutin, gunakan perintah `/aset` (contoh: `/aset` atau `/aset BBRI, BBCA, TLKM`)."
            )
            return

        ctx.send(f"⏳ Sedang patroli ke pos saham {ctx.bold(ticker)}...")
        result = self._evaluate(ticker)
        if "error" in result:
            ctx.send(f"❌ {ctx.bold(ticker)}: {result['error']}")
        else:
            ctx.send(result["narration"])

    def _handle_aset(self, tokens: list[str], full_text: str, ctx: ReplyContext) -> None:
        from ..portfolio import (
            add_ticker,
            clean_ticker,
            get_portfolio,
            remove_ticker,
            scope_user_key,
            set_portfolio,
        )

        user_id = scope_user_key(ctx.platform, ctx.user_id or "default")

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
        if action == "tambah":
            if len(tokens) < 3:
                ctx.send("ℹ️ Format perintah: `/aset tambah TICKER` (contoh: `/aset tambah BBRI`)")
                return
            sym = clean_ticker(tokens[2])
            updated = add_ticker(user_id, tokens[2])
            ctx.send(f"✅ Saham {ctx.bold(sym)} berhasil ditambahkan ke radar pantauan Anda!")
            return
        elif action == "hapus":
            if len(tokens) < 3:
                ctx.send("ℹ️ Format perintah: `/aset hapus TICKER` (contoh: `/aset hapus BBRI`)")
                return
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
    """Susun laporan ronda memakai markup tebal milik kanal menjadi 1 pesan/bubble terpadu."""
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
    header = (
        f"🔔 {bold(f'Laporan Ronda Sore — {date.today().isoformat()}')}\n\n"
        f"Perhatian warga, terdeteksi {bold(f'{len(ranked)} saham')} masuk radar risiko:\n\n"
        f"{scoreboard}"
    )

    clean_narrations = []
    for alert in ranked:
        narration = alert.get("narration", "").strip()
        # Bersihkan disclaimer per saham agar tidak terulang-ulang
        narration = narration.replace("⚠️ Ini bukan saran investasi. Data dari Sectors.app.", "").strip()
        clean_narrations.append(narration)

    divider = "\n\n───────────────────\n\n"
    disclaimer = "\n\n⚠️ Ini bukan saran investasi. Data dari Sectors.app."

    combined = f"{header}{divider}{divider.join(clean_narrations)}{disclaimer}"
    if len(combined) <= 3900:
        return [combined]

    # Pemecahan cerdas jika daftar saham sangat panjang (> 15 saham) melebihi batas 1 bubble
    chunks = []
    current_chunk = header
    for item in clean_narrations:
        candidate = f"{current_chunk}{divider}{item}"
        if len(candidate) > 3800:
            chunks.append(current_chunk)
            current_chunk = item
        else:
            current_chunk = candidate
    if current_chunk:
        chunks.append(current_chunk + disclaimer)
    return chunks


def build_briefing_messages(channel: Channel, candidates: list[dict[str, Any]]) -> list[str]:
    """Susun briefing pagi (kandidat fundamental) menjadi 1 pesan/bubble terpadu."""
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
    header = (
        f"🌅 {bold(f'Briefing Pagi — {date.today().isoformat()}')}\n\n"
        f"Kandidat fundamental sehat ({bold(f'{len(ranked)} saham')}):\n\n{scoreboard}"
    )

    clean_narrations = [item.get("narration", "").strip() for item in ranked]
    divider = "\n\n───────────────────\n\n"
    disclaimer = "\n\n⚠️ Ini bukan saran investasi. Data dari Sectors.app."

    combined = f"{header}{divider}{divider.join(clean_narrations)}{disclaimer}"
    if len(combined) <= 3900:
        return [combined]

    chunks = []
    current_chunk = header
    for item in clean_narrations:
        candidate = f"{current_chunk}{divider}{item}"
        if len(candidate) > 3800:
            chunks.append(current_chunk)
            current_chunk = item
        else:
            current_chunk = candidate
    if current_chunk:
        chunks.append(current_chunk + disclaimer)
    return chunks


def build_portfolio_messages(
    channel: Channel,
    items: list[dict[str, Any]],
    title: str,
    summary: Callable[[dict[str, Any]], str],
) -> list[str]:
    """Susun section aset pantauan warga (per-user) memakai markup tebal kanal menjadi 1 pesan/bubble terpadu.

    `items` masing-masing memuat `symbol` dan opsional `narration`; `summary`
    merangkum satu item menjadi baris singkat pada papan skor.
    """
    if not items:
        return []

    bold = channel.bold
    scoreboard = "\n".join(
        f"{rank}. {bold(item['symbol'].replace('.JK', ''))} — {summary(item)}"
        for rank, item in enumerate(items, start=1)
    )
    header = f"📌 {bold(title)}\n\n{scoreboard}"

    clean_narrations = []
    for item in items:
        narration = item.get("narration", "").strip()
        narration = narration.replace("⚠️ Ini bukan saran investasi. Data dari Sectors.app.", "").strip()
        if narration:
            clean_narrations.append(narration)

    divider = "\n\n───────────────────\n\n"
    disclaimer = "\n\n⚠️ Ini bukan saran investasi. Data dari Sectors.app."

    if clean_narrations:
        combined = f"{header}{divider}{divider.join(clean_narrations)}{disclaimer}"
    else:
        combined = f"{header}{disclaimer}"

    if len(combined) <= 3900:
        return [combined]

    chunks = []
    current_chunk = header
    for item in clean_narrations:
        candidate = f"{current_chunk}{divider}{item}"
        if len(candidate) > 3800:
            chunks.append(current_chunk)
            current_chunk = item
        else:
            current_chunk = candidate
    if current_chunk:
        chunks.append(current_chunk + disclaimer)
    return chunks


def _clean_narration(raw_narration: str) -> str:
    """Bersihkan disclaimer bawaan dari narasi item agar tidak berulang sebelum footer."""
    return raw_narration.replace("⚠️ Ini bukan saran investasi. Data dari Sectors.app.", "").strip()


def _fit_narrations_into_budget(
    header: str,
    narrations: list[str],
    current_length: int,
    divider: str,
    max_length: int = 3850,
) -> tuple[str, int]:
    """Saring narasi agar total panjang pesan tidak melampaui batas 1 bubble platform."""
    included: list[str] = []
    for narration in narrations:
        est_len = current_length + sum(len(n) + len(divider) for n in included) + len(narration) + 120
        if est_len <= max_length:
            included.append(narration)
        else:
            break

    omitted = len(narrations) - len(included)
    content = header
    if included:
        content += f"{divider}{divider.join(included)}"
    return content, omitted


def build_unified_patrol_messages(
    channel: Channel,
    portfolio_items: list[dict[str, Any]],
    market_alerts: list[dict[str, Any]],
) -> list[str]:
    """Susun laporan patroli sore terpadu: ASET KELUAR PERTAMA, lalu disusul laporan pasar, DIJAMIN 1 BUBBLE CHAT."""
    bold = channel.bold
    today_str = date.today().isoformat()
    divider_sub = "\n\n───────────────────\n\n"
    section_divider = "\n\n═══════════════════\n\n"
    disclaimer = "\n\n⚠️ Ini bukan saran investasi. Data dari Sectors.app."
    max_bubble_length = 3850

    sections: list[str] = []

    # 1. ASSET WARGA KELUAR PERTAMA (PRIORITAS UTAMA - LENGKAP)
    if portfolio_items:
        ranked_port = sorted(portfolio_items, key=lambda a: -a.get("score", 0))
        scoreboard_port = "\n".join(
            f"{rank}. {bold(item['symbol'].replace('.JK', ''))} — Skor {item.get('score', 0)}/100"
            for rank, item in enumerate(ranked_port, start=1)
        )
        port_header = f"📌 {bold(f'Radar Aset Pantauan Anda — {today_str}')}\n\n{scoreboard_port}"
        clean_port_narrations = [_clean_narration(item.get("narration", "")) for item in ranked_port if item.get("narration")]
        clean_port_narrations = [n for n in clean_port_narrations if n]

        if clean_port_narrations:
            sections.append(f"{port_header}{divider_sub}{divider_sub.join(clean_port_narrations)}")
        else:
            sections.append(port_header)

    # 2. LAPORAN PASAR RONDA SORE (SMART COMPRESSION AGAR TETAP 1 BUBBLE)
    if market_alerts:
        ranked_market = sorted(market_alerts, key=lambda a: -a.get("score", 0))
        scoreboard_market = "\n".join(
            f"{rank}. {bold(alert['symbol'].replace('.JK', ''))} — {alert['score']}/100"
            for rank, alert in enumerate(ranked_market, start=1)
        )
        market_header = (
            f"🔔 {bold(f'Laporan Ronda Sore — {today_str}')}\n\n"
            f"Perhatian warga, terdeteksi {bold(f'{len(ranked_market)} saham')} top gainers masuk radar risiko:\n\n"
            f"{scoreboard_market}"
        )
        clean_market_narrations = [_clean_narration(item.get("narration", "")) for item in ranked_market if item.get("narration")]
        clean_market_narrations = [n for n in clean_market_narrations if n]

        current_len = sum(len(s) for s in sections) + len(market_header) + len(disclaimer) + 100
        market_content, omitted_count = _fit_narrations_into_budget(
            market_header, clean_market_narrations, current_len, divider_sub, max_bubble_length
        )
        if omitted_count > 0:
            market_content += f"\n\nℹ️ {bold(f'(+{omitted_count} saham risiko lainnya tercatat pada scoreboard di atas. Cek detail via')} `/ronda TICKER`{bold(')')}"

        sections.append(market_content)
    else:
        market_header = (
            f"🛡️ {bold(f'Laporan Ronda Sore — {today_str}')}\n\n"
            "Situasi pasar terpantau kondusif. Tidak ada saham mencurigakan pada jajaran top gainers hari ini."
        )
        sections.append(market_header)

    combined = f"{section_divider.join(sections)}{disclaimer}"
    return [combined]


def build_unified_morning_messages(
    channel: Channel,
    portfolio_items: list[dict[str, Any]],
    market_candidates: list[dict[str, Any]],
) -> list[str]:
    """Susun briefing pagi terpadu: ASET KELUAR PERTAMA, lalu disusul kandidat fundamental bursa, DIJAMIN 1 BUBBLE CHAT."""
    bold = channel.bold
    today_str = date.today().isoformat()
    divider_sub = "\n\n───────────────────\n\n"
    section_divider = "\n\n═══════════════════\n\n"
    disclaimer = "\n\n⚠️ Ini bukan saran investasi. Data dari Sectors.app."
    max_bubble_length = 3850

    sections: list[str] = []

    # 1. ASSET WARGA KELUAR PERTAMA (PRIORITAS UTAMA - LENGKAP)
    if portfolio_items:
        def _div_yield(item: dict[str, Any]) -> str:
            y = item.get("dividend_yield")
            if isinstance(y, (int, float)):
                return f"Dividen {y * 100:.1f}%" if y < 1.0 else f"Dividen {y:.1f}%"
            return "Dividen n/a"

        scoreboard_port = "\n".join(
            f"{rank}. {bold(item['symbol'].replace('.JK', ''))} — {_div_yield(item)}"
            for rank, item in enumerate(portfolio_items, start=1)
        )
        port_header = f"📌 {bold(f'Aset Pantauan Anda — Briefing {today_str}')}\n\n{scoreboard_port}"
        clean_port_narrations = [_clean_narration(item.get("narration", "")) for item in portfolio_items if item.get("narration")]
        clean_port_narrations = [n for n in clean_port_narrations if n]

        if clean_port_narrations:
            sections.append(f"{port_header}{divider_sub}{divider_sub.join(clean_port_narrations)}")
        else:
            sections.append(port_header)

    # 2. BRIEFING PAGI (KANDIDAT FUNDAMENTAL BURSA - SMART COMPRESSION)
    if market_candidates:
        ranked_market = sorted(market_candidates, key=lambda item: -(item.get("dividend_yield") or 0))
        scoreboard_market = "\n".join(
            f"{rank}. {bold(item['symbol'].replace('.JK', ''))} — yield "
            f"{(item.get('dividend_yield') or 0) * 100:.1f}%"
            for rank, item in enumerate(ranked_market, start=1)
        )
        market_header = (
            f"🌅 {bold(f'Briefing Pagi — {today_str}')}\n\n"
            f"Kandidat fundamental sehat ({bold(f'{len(ranked_market)} saham')}):\n\n{scoreboard_market}"
        )
        clean_market_narrations = [_clean_narration(item.get("narration", "")) for item in ranked_market if item.get("narration")]
        clean_market_narrations = [n for n in clean_market_narrations if n]

        current_len = sum(len(s) for s in sections) + len(market_header) + len(disclaimer) + 100
        market_content, omitted_count = _fit_narrations_into_budget(
            market_header, clean_market_narrations, current_len, divider_sub, max_bubble_length
        )
        if omitted_count > 0:
            market_content += f"\n\nℹ️ {bold(f'(+{omitted_count} kandidat lainnya tercatat pada scoreboard di atas)')}"

        sections.append(market_content)
    else:
        market_header = (
            f"🌅 {bold(f'Briefing Pagi — {today_str}')}\n\n"
            "Tidak ada kandidat fundamental yang lolos kriteria hari ini."
        )
        sections.append(market_header)

    combined = f"{section_divider.join(sections)}{disclaimer}"
    return [combined]


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


# Kunci portofolio lama tanpa prefiks platform diasumsikan milik Telegram.
DEFAULT_DIRECT_PLATFORM = "telegram"


def dispatch_direct(
    channels: Iterable[Channel],
    recipient: str,
    build_messages: Callable[[Channel], list[str]],
    platform: str = "",
) -> None:
    """Kirim pesan langsung ke satu penerima (mis. DM aset warga) pada kanal yang cocok.

    `platform` adalah nama kanal tujuan (mis. "telegram", "discord"). Bila kosong,
    pesan dikirim melalui `DEFAULT_DIRECT_PLATFORM` agar data lama tetap terkirim.
    """
    if not recipient:
        return

    target = platform or DEFAULT_DIRECT_PLATFORM
    for channel in channels:
        if not channel.is_configured() or channel.name != target:
            continue

        messages = build_messages(channel)
        for index, message in enumerate(messages):
            channel.send_to_user(recipient, message)
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
