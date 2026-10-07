"""Kanal Telegram (Bot API) — implementasi `Channel`/`InteractiveChannel`."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .base import CommandRouter, InteractiveChannel, ReplyContext, register_channel

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot"


@register_channel
class TelegramChannel(InteractiveChannel):
    name = "telegram"

    @staticmethod
    def token() -> str:
        return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    @staticmethod
    def chat_id() -> str:
        return os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    def is_configured(self) -> bool:
        token = self.token()
        return bool(token) and not token.startswith("isi_") and token != "123456:ABC-DEF"

    def default_recipient(self) -> str:
        return self.chat_id()

    def bold(self, text: str) -> str:
        return f"*{text}*"

    def request(self, method: str, payload: dict[str, Any], timeout: int = 15) -> dict[str, Any] | None:
        """Kirim request POST ke Telegram Bot API."""
        token = self.token()
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN belum dikonfigurasi")
            return None

        request = urllib.request.Request(
            f"{API_BASE}{token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            logger.error("Telegram API error %s: %s", error.code, error.read()[:200])
            return None
        except (urllib.error.URLError, TimeoutError) as error:
            if "timed out" in str(error).lower():
                logger.debug("Telegram polling long-poll timed out normally")
            else:
                logger.error("Koneksi Telegram gagal: %s", error)
            return None

    def send(self, recipient: str, text: str) -> dict[str, Any] | None:
        return self.request("sendMessage", {
            "chat_id": recipient,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })

    def _create_reply_sender(self, chat_id: str) -> Callable[[str], None]:
        """Buat fungsi pengirim balasan untuk satu chat id."""
        return lambda content: self.send(chat_id, content)

    def _ensure_recipient_configured(self, chat_id: str) -> None:
        """Simpan chat_id aktif ke environment dan file .env bila belum dikonfigurasi."""
        current = self.chat_id()
        if not current or current.startswith("-100xxxx") or current.startswith("isi_"):
            os.environ["TELEGRAM_CHAT_ID"] = chat_id
            env_file = Path(__file__).resolve().parent.parent.parent / ".env"
            if env_file.exists():
                try:
                    content = env_file.read_text(encoding="utf-8")
                    new_content = re.sub(r"^TELEGRAM_CHAT_ID=.*", f"TELEGRAM_CHAT_ID={chat_id}", content, flags=re.M)
                    if new_content == content and "TELEGRAM_CHAT_ID=" not in content:
                        new_content += f"\nTELEGRAM_CHAT_ID={chat_id}\n"
                    env_file.write_text(new_content, encoding="utf-8")
                    logger.info("TELEGRAM_CHAT_ID otomatis dikonfigurasi ke: %s", chat_id)
                except OSError as error:
                    logger.warning("Gagal memperbarui file .env: %s", error)

    def run_listener(self, router: CommandRouter) -> None:
        if not self.token():
            logger.error("TELEGRAM_BOT_TOKEN wajib diisi untuk menjalankan polling")
            return

        logger.info("Kanal Telegram siap berpatroli (polling mode aktif)...")
        last_update_id = 0

        while True:
            try:
                updates = self.request("getUpdates", {"offset": last_update_id, "timeout": 20}, timeout=25)
                if not updates or not updates.get("ok"):
                    time.sleep(1)
                    continue

                for update in updates.get("result", []):
                    last_update_id = update["update_id"] + 1
                    message = update.get("message", {})
                    text = str(message.get("text", ""))
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    if not text or not chat_id:
                        continue

                    logger.info("Pesan Telegram masuk dari chat_id [%s]: %s", chat_id, text)
                    self._ensure_recipient_configured(chat_id)

                    if text.strip().split("@")[0].lower() in {"/id", "/chatid"}:
                        self.send(chat_id, f"🆔 *Chat ID Anda/grup ini:* `{chat_id}`\n✅ *Berhasil didaftarkan sebagai penerima broadcast laporan!*")
                        continue

                    reply_sender = self._create_reply_sender(chat_id)
                    router.handle(text, ReplyContext(send=reply_sender, bold=self.bold))
            except KeyboardInterrupt:
                logger.info("Polling Telegram dihentikan oleh pengguna")
                break
            except Exception as error:
                logger.error("Kesalahan pada polling Telegram: %s", error)
                time.sleep(5)
