"""Kanal Discord (REST + Gateway WebSocket) — implementasi `Channel`/`InteractiveChannel`."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from .base import CommandRouter, InteractiveChannel, ReplyContext, register_channel
from .discord_gateway import DiscordGateway, build_intents

logger = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (+https://github.com/diwanparker/siskamling-pasar)"
MESSAGE_LIMIT = 2000

APPLICATION_COMMAND = 2
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5

COMMAND_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "ronda",
        "description": "Periksa skor risiko satu saham IDX",
        "options": [
            {"type": 3, "name": "ticker", "description": "Kode saham, contoh: BBCA", "required": True}
        ],
    },
    {"name": "help", "description": "Panduan penggunaan Siskamling Pasar"},
]


def chunk_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pecah teks panjang agar memenuhi batas karakter pesan Discord."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


@register_channel
class DiscordChannel(InteractiveChannel):
    name = "discord"

    @staticmethod
    def token() -> str:
        return os.environ.get("DISCORD_BOT_TOKEN", "").strip()

    @staticmethod
    def channel_id() -> str:
        return os.environ.get("DISCORD_CHANNEL_ID", "").strip()

    @staticmethod
    def application_id() -> str:
        return os.environ.get("DISCORD_APPLICATION_ID", "").strip()

    @staticmethod
    def guild_id() -> str:
        return os.environ.get("DISCORD_GUILD_ID", "").strip()

    def is_configured(self) -> bool:
        return bool(self.token())

    def default_recipient(self) -> str:
        return self.channel_id()

    def bold(self, text: str) -> str:
        return f"**{text}**"

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any | None:
        """Kirim request REST ke Discord API v10 dengan autentikasi bot."""
        token = self.token()
        if not token:
            logger.warning("DISCORD_BOT_TOKEN belum dikonfigurasi")
            return None

        request = urllib.request.Request(
            f"{API_BASE}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            logger.error("Discord API error %s: %s", error.code, error.read()[:200])
            return None
        except urllib.error.URLError as error:
            logger.error("Koneksi Discord gagal: %s", error)
            return None

    def send(self, recipient: str, text: str) -> Any | None:
        response = None
        for chunk in chunk_message(text):
            response = self.request("POST", f"/channels/{recipient}/messages", {"content": chunk})
        return response

    def register_commands(self, application_id: str) -> Any | None:
        """Daftarkan slash command global, atau per-guild bila DISCORD_GUILD_ID di-set."""
        path = f"/applications/{application_id}/commands"
        guild_id = self.guild_id()
        if guild_id:
            path = f"/applications/{application_id}/guilds/{guild_id}/commands"
        return self.request("PUT", path, COMMAND_DEFINITIONS)

    def resolve_application_id(self) -> str:
        configured = self.application_id()
        if configured:
            return configured
        profile = self.request("GET", "/applications/@me")
        if profile and profile.get("id"):
            return str(profile["id"])
        return ""

    def run_listener(self, router: CommandRouter) -> None:
        if not self.token():
            logger.error("DISCORD_BOT_TOKEN wajib diisi untuk menjalankan bot Discord")
            return

        application_id = self.resolve_application_id()
        if application_id:
            self.register_commands(application_id)
            logger.info("Slash command Discord terdaftar (application_id=%s)", application_id)
        else:
            logger.warning("Application ID Discord tidak diketahui; slash command tidak didaftarkan")

        logger.info("Kanal Discord siap berpatroli (gateway mode aktif)...")
        self._router = router
        gateway = DiscordGateway(
            self.token(),
            intents=build_intents(),
            on_event=self._on_event,
        )
        gateway.run_forever()

    def _on_event(self, event_name: str, data: Any, router: CommandRouter | None = None) -> None:
        active_router = router or getattr(self, "_router", None)
        if active_router is None:
            return
        if event_name == "INTERACTION_CREATE" and isinstance(data, dict):
            self._handle_interaction(data, active_router)
        elif event_name == "MESSAGE_CREATE" and isinstance(data, dict):
            self._handle_message(data, active_router)

    def _handle_interaction(self, interaction: dict[str, Any], router: CommandRouter | None = None) -> None:
        active_router = router or getattr(self, "_router", None)
        if active_router is None:
            return
        if interaction.get("type") != APPLICATION_COMMAND:
            return

        interaction_id = str(interaction.get("id", ""))
        interaction_token = str(interaction.get("token", ""))
        application_id = str(interaction.get("application_id", ""))
        if not interaction_id or not interaction_token:
            return

        command_text = self._command_text(interaction)
        if command_text is None:
            return

        # Ack deferred (<3 detik) sebelum evaluasi berat agar interaction tidak gagal.
        self.request(
            "POST",
            f"/interactions/{interaction_id}/{interaction_token}/callback",
            {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE},
        )

        interaction_sender = self._create_interaction_reply_sender(application_id, interaction_token)
        router.handle(command_text, ReplyContext(send=interaction_sender, bold=self.bold))

    def _create_interaction_reply_sender(self, application_id: str, token: str) -> Callable[[str], Any]:
        """Buat fungsi pengirim balasan untuk Discord interaction response."""
        return lambda content: self.request(
            "PATCH", f"/webhooks/{application_id}/{token}/messages/@original", {"content": content}
        )

    def _create_channel_reply_sender(self, channel_id: str) -> Callable[[str], Any]:
        """Buat fungsi pengirim balasan untuk pesan teks di Discord channel."""
        return lambda content: self.send(channel_id, content)

    def _handle_message(self, message: dict[str, Any], router: CommandRouter) -> None:
        author = message.get("author") or {}
        if author.get("bot"):
            return

        text = str(message.get("content", "")).strip()
        channel_id = str(message.get("channel_id", ""))
        if not text or not channel_id:
            return

        channel_sender = self._create_channel_reply_sender(channel_id)
        router.handle(text, ReplyContext(send=channel_sender, bold=self.bold))

    @staticmethod
    def _command_text(interaction: dict[str, Any]) -> str | None:
        """Normalisasi interaksi menjadi teks perintah yang dikenali router bersama."""
        data = interaction.get("data") or {}
        name = str(data.get("name", "")).lower()
        if not name:
            return None
        if name == "ronda":
            ticker = ""
            for option in data.get("options") or []:
                if option.get("name") == "ticker":
                    ticker = str(option.get("value", "")).strip()
            return f"/ronda {ticker}".strip()
        return f"/{name}"
