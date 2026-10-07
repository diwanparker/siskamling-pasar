"""Unit tests untuk abstraksi platform (registry, dispatch, router) dan kanal Telegram/Discord."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siskamling.platforms.base import (
    Channel,
    CommandRouter,
    PlainTextChannel,
    ReplyContext,
    build_briefing_messages,
    build_portfolio_messages,
    build_report_messages,
    dispatch_direct,
    dispatch_report,
)
from siskamling.platforms.discord import DiscordChannel, chunk_message
from siskamling.platforms.telegram import TelegramChannel


class RecordingChannel(Channel):
    """Kanal palsu untuk menguji dispatch tanpa jaringan."""

    name = "recording"

    def __init__(self, configured: bool = True, recipient: str = "dest") -> None:
        self._configured = configured
        self._recipient = recipient
        self.sent: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self._configured

    def default_recipient(self) -> str:
        return self._recipient

    def send(self, recipient: str, text: str):
        self.sent.append((recipient, text))
        return {}

    def bold(self, text: str) -> str:
        return f"**{text}**"


def make_context(sent: list[str]) -> ReplyContext:
    return ReplyContext(send=sent.append, bold=lambda text: f"**{text}**")


class TestReportBuilder(unittest.TestCase):
    def test_safe_market_report_single_message(self):
        messages = build_report_messages(RecordingChannel(), [])
        self.assertEqual(len(messages), 1)
        self.assertIn("Laporan Ronda Sore", messages[0])
        self.assertIn("kondusif", messages[0])

    def test_alert_report_sorted_by_score(self):
        alerts = [
            {"symbol": "LOW.JK", "score": 45, "narration": "low"},
            {"symbol": "HIGH.JK", "score": 90, "narration": "high"},
        ]
        messages = build_report_messages(RecordingChannel(), alerts)
        self.assertEqual(len(messages), 1)
        self.assertIn("2 saham", messages[0])
        self.assertIn("high", messages[0])
        self.assertIn("low", messages[0])
        self.assertTrue(messages[0].index("high") < messages[0].index("low"))


class TestDispatchReport(unittest.TestCase):
    @patch("siskamling.platforms.base.time.sleep")
    def test_skips_unconfigured_and_empty_recipient(self, _mock_sleep):
        unconfigured = RecordingChannel(configured=False)
        no_recipient = RecordingChannel(recipient="")
        configured = RecordingChannel()

        dispatch_report([unconfigured, no_recipient, configured], [])

        self.assertEqual(unconfigured.sent, [])
        self.assertEqual(no_recipient.sent, [])
        self.assertEqual(len(configured.sent), 1)

    @patch("siskamling.platforms.base.time.sleep")
    def test_uses_each_channel_markup(self, _mock_sleep):
        channel = RecordingChannel()
        dispatch_report([channel], [{"symbol": "X.JK", "score": 50, "narration": "narasi"}])

        header = channel.sent[0][1]
        self.assertIn("**Laporan Ronda Sore", header)
        self.assertIn("narasi", header)


class TestBuildPortfolioMessages(unittest.TestCase):
    def test_renders_header_entries_and_narrations(self):
        items = [
            {"symbol": "BBCA.JK", "score": 30, "narration": "narasi-bbca"},
            {"symbol": "BBRI.JK", "score": 75, "narration": "narasi-bbri"},
        ]
        messages = build_portfolio_messages(
            RecordingChannel(), items, "Radar Aset Anda", lambda item: f"Skor {item['score']}/100"
        )

        self.assertEqual(len(messages), 3)
        self.assertIn("Radar Aset Anda", messages[0])
        self.assertIn("**BBCA**", messages[0])
        self.assertIn("Skor 75/100", messages[0])
        self.assertEqual(messages[1], "narasi-bbca")
        self.assertEqual(messages[2], "narasi-bbri")

    def test_empty_items_returns_no_message(self):
        self.assertEqual(build_portfolio_messages(RecordingChannel(), [], "t", lambda item: ""), [])


class TestDispatchDirect(unittest.TestCase):
    @patch("siskamling.platforms.base.time.sleep")
    def test_routes_only_to_matching_platform(self, _mock_sleep):
        telegram = RecordingChannel()
        telegram.name = "telegram"
        discord = RecordingChannel()
        discord.name = "discord"

        dispatch_direct([telegram, discord], "111", lambda channel: ["halo"], platform="discord")

        self.assertEqual(telegram.sent, [])
        self.assertEqual(discord.sent, [("111", "halo")])

    @patch("siskamling.platforms.base.time.sleep")
    def test_unprefixed_recipient_defaults_to_telegram(self, _mock_sleep):
        telegram = RecordingChannel()
        telegram.name = "telegram"
        discord = RecordingChannel()
        discord.name = "discord"

        dispatch_direct([telegram, discord], "222", lambda channel: ["halo"])

        self.assertEqual(telegram.sent, [("222", "halo")])
        self.assertEqual(discord.sent, [])

    @patch("siskamling.platforms.base.time.sleep")
    def test_empty_recipient_skips(self, _mock_sleep):
        channel = RecordingChannel()
        channel.name = "telegram"

        dispatch_direct([channel], "", lambda ch: ["halo"], platform="telegram")

        self.assertEqual(channel.sent, [])

    @patch("siskamling.platforms.base.time.sleep")
    def test_skips_unconfigured_channel(self, _mock_sleep):
        channel = RecordingChannel(configured=False)
        channel.name = "telegram"

        dispatch_direct([channel], "111", lambda ch: ["halo"], platform="telegram")

        self.assertEqual(channel.sent, [])


class TestCommandRouter(unittest.TestCase):
    def test_ronda_success(self):
        sent: list[str] = []
        router = CommandRouter(evaluate=lambda ticker: {"symbol": f"{ticker}.JK", "score": 77, "narration": "waspada"})

        router.handle("/ronda bbca", make_context(sent))

        self.assertEqual(len(sent), 2)
        self.assertIn("**BBCA**", sent[0])
        self.assertEqual(sent[1], "waspada")

    def test_ronda_missing_ticker(self):
        sent: list[str] = []
        CommandRouter(evaluate=lambda ticker: {}).handle("/ronda", make_context(sent))
        self.assertEqual(len(sent), 1)
        self.assertIn("Format perintah", sent[0])

    def test_ronda_error_uses_bold_ticker(self):
        sent: list[str] = []
        CommandRouter(evaluate=lambda ticker: {"error": "data kurang"}).handle("/ronda UNSP", make_context(sent))
        self.assertIn("**UNSP**", sent[-1])
        self.assertIn("data kurang", sent[-1])

    def test_help_command(self):
        sent: list[str] = []
        CommandRouter(evaluate=lambda ticker: {}).handle("/help", make_context(sent))
        self.assertIn("Siskamling Pasar", sent[0])

    def test_discord_mention_suffix_is_stripped(self):
        sent: list[str] = []
        router = CommandRouter(evaluate=lambda ticker: {"symbol": ticker, "score": 1, "narration": "ok"})
        router.handle("/ronda@SiskamlingBot bbca", make_context(sent))
        self.assertEqual(sent[1], "ok")

    @patch("siskamling.portfolio.PORTFOLIO_FILE")
    def test_aset_empty_prompts_user(self, mock_file):
        mock_file.exists.return_value = False
        sent: list[str] = []
        CommandRouter(evaluate=lambda t: {}).handle("/aset", make_context(sent))
        self.assertIn("belum mendaftarkan saham", sent[0])

    @patch("siskamling.portfolio.PORTFOLIO_FILE")
    def test_aset_register_and_list(self, mock_file):
        mock_file.exists.return_value = False
        sent: list[str] = []
        router = CommandRouter(evaluate=lambda t: {})
        with patch("siskamling.portfolio._save_data"):
            with patch("siskamling.portfolio._load_data", return_value={"u1": ["BBCA.JK", "BBRI.JK"]}):
                ctx = ReplyContext(send=sent.append, bold=lambda t: f"**{t}**", user_id="u1")
                router.handle("/aset", ctx)
                self.assertIn("BBCA.JK", sent[-1])
                self.assertIn("BBRI.JK", sent[-1])

    @patch("siskamling.portfolio.set_portfolio", return_value=["BBCA.JK", "TLKM.JK"])
    def test_aset_set_multiple_tickers(self, mock_set):
        sent: list[str] = []
        ctx = ReplyContext(send=sent.append, bold=lambda t: f"**{t}**", user_id="u2")
        CommandRouter(evaluate=lambda t: {}).handle("/aset BBCA, TLKM", ctx)
        self.assertIn("Berhasil mendaftarkan 2 saham", sent[0])
        mock_set.assert_called_once_with("u2", ["BBCA", "TLKM"])

    def test_ronda_aset_guides_user(self):
        sent: list[str] = []
        router = CommandRouter(evaluate=lambda t: {})
        router.handle("/ronda aset", make_context(sent))
        self.assertEqual(len(sent), 1)
        self.assertIn("/aset", sent[0])
        self.assertIn("Info Pos Ronda", sent[0])

    def test_aset_tambah_missing_args_shows_format(self):
        sent: list[str] = []
        router = CommandRouter(evaluate=lambda t: {})
        router.handle("/aset tambah", make_context(sent))
        self.assertIn("Format perintah", sent[0])
    @patch("siskamling.portfolio.set_portfolio", return_value=["BBCA.JK"])
    def test_aset_scopes_key_by_platform(self, mock_set):
        sent: list[str] = []
        ctx = ReplyContext(send=sent.append, bold=lambda t: f"**{t}**", user_id="42", platform="telegram")
        CommandRouter(evaluate=lambda t: {}).handle("/aset BBCA", ctx)
        mock_set.assert_called_once_with("telegram:42", ["BBCA"])


class TestTelegramChannel(unittest.TestCase):
    def test_bold_uses_markdown_v1(self):
        self.assertEqual(TelegramChannel().bold("hi"), "*hi*")

    def test_request_returns_none_without_token(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            self.assertIsNone(TelegramChannel().request("getMe", {}))

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc"})
    @patch("siskamling.platforms.telegram.urllib.request.urlopen")
    def test_send_posts_expected_payload(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = b'{"ok": true}'
        mock_urlopen.return_value.__enter__.return_value = response

        TelegramChannel().send("999", "halo")

        request = mock_urlopen.call_args.args[0]
        self.assertIn("/bot123:abc/sendMessage", request.full_url)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["chat_id"], "999")
        self.assertEqual(payload["text"], "halo")
        self.assertEqual(payload["parse_mode"], "Markdown")


class TestDiscordChannel(unittest.TestCase):
    def test_bold_uses_double_asterisk(self):
        self.assertEqual(DiscordChannel().bold("hi"), "**hi**")

    def test_chunk_message_splits_on_newline(self):
        text = ("x" * 1500 + "\n") * 3
        chunks = chunk_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))

    def test_chunk_message_short_text_unchanged(self):
        self.assertEqual(chunk_message("pendek"), ["pendek"])

    @patch.object(DiscordChannel, "request", return_value={})
    def test_send_chunks_long_message(self, mock_request):
        long_text = "y" * 4500
        DiscordChannel().send("42", long_text)

        self.assertGreater(mock_request.call_count, 1)
        for call in mock_request.call_args_list:
            self.assertEqual(call.args[0], "POST")
            self.assertLessEqual(len(call.args[2]["content"]), 2000)

    @patch.object(DiscordChannel, "request")
    def test_send_to_user_opens_dm_channel(self, mock_request):
        mock_request.side_effect = [{"id": "dm-chan"}, {}]

        DiscordChannel().send_to_user("111", "halo")

        self.assertEqual(
            mock_request.call_args_list[0].args,
            ("POST", "/users/@me/channels", {"recipient_id": "111"}),
        )
        self.assertEqual(
            mock_request.call_args_list[1].args,
            ("POST", "/channels/dm-chan/messages", {"content": "halo"}),
        )

    @patch.object(DiscordChannel, "request", return_value=None)
    def test_send_to_user_without_dm_channel_returns_none(self, mock_request):
        self.assertIsNone(DiscordChannel().send_to_user("111", "halo"))
        mock_request.assert_called_once_with("POST", "/users/@me/channels", {"recipient_id": "111"})

    @patch.object(DiscordChannel, "request", return_value={})
    def test_interaction_defers_then_edits_original(self, mock_request):
        channel = DiscordChannel()
        router = CommandRouter(evaluate=lambda ticker: {"symbol": f"{ticker}.JK", "score": 90, "narration": "bahaya"})
        interaction = {
            "type": 2,
            "id": "111",
            "token": "tok",
            "application_id": "app",
            "data": {"name": "ronda", "options": [{"name": "ticker", "value": "bbca"}]},
        }

        channel._handle_interaction(interaction, router)

        callbacks = [c for c in mock_request.call_args_list if c.args[1].endswith("/callback")]
        self.assertEqual(callbacks[0].args[2]["type"], 5)

        patches = [c for c in mock_request.call_args_list if c.args[0] == "PATCH"]
        self.assertEqual(len(patches), 2)  # interim + hasil
        self.assertIn("bahaya", patches[-1].args[2]["content"])

    @patch.dict(os.environ, {"DISCORD_GUILD_ID": "555"})
    @patch.object(DiscordChannel, "request", return_value={})
    def test_register_commands_guild_path(self, mock_request):
        DiscordChannel().register_commands("app")

        method, path, _payload = mock_request.call_args.args
        self.assertEqual(method, "PUT")
        self.assertEqual(path, "/applications/app/guilds/555/commands")

    @patch.dict(os.environ, {"DISCORD_GUILD_ID": ""})
    @patch.object(DiscordChannel, "request", return_value={})
    def test_register_commands_global_path(self, mock_request):
        DiscordChannel().register_commands("app")

        _method, path, _payload = mock_request.call_args.args
        self.assertEqual(path, "/applications/app/commands")

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(DiscordChannel, "request", return_value={"id": "app-dari-token"})
    def test_resolve_application_id_detects_from_token(self, mock_request):
        self.assertEqual(DiscordChannel().resolve_application_id(), "app-dari-token")
        mock_request.assert_called_once_with("GET", "/applications/@me")


class TestBriefingBuilder(unittest.TestCase):
    def test_empty_briefing_single_message(self):
        messages = build_briefing_messages(RecordingChannel(), [])
        self.assertEqual(len(messages), 1)
        self.assertIn("Briefing Pagi", messages[0])
        self.assertIn("Tidak ada kandidat", messages[0])

    def test_briefing_ranked_by_dividend_yield(self):
        candidates = [
            {"symbol": "LOW.JK", "dividend_yield": 0.05, "narration": "low"},
            {"symbol": "HIGH.JK", "dividend_yield": 0.09, "narration": "high"},
        ]
        messages = build_briefing_messages(RecordingChannel(), candidates)
        self.assertEqual(len(messages), 1)
        self.assertIn("2 saham", messages[0])
        self.assertIn("high", messages[0])
        self.assertIn("low", messages[0])
        self.assertTrue(messages[0].index("high") < messages[0].index("low"))
        self.assertIn("bukan saran investasi", messages[0])


class TestPlainTextChannel(unittest.TestCase):
    def test_bold_is_identity(self):
        self.assertEqual(PlainTextChannel().bold("hi"), "hi")

    def test_send_is_noop(self):
        self.assertIsNone(PlainTextChannel().send("dest", "halo"))

    def test_report_renders_without_markup(self):
        messages = build_report_messages(
            PlainTextChannel(),
            [{"symbol": "X.JK", "score": 50, "narration": "narasi polos"}],
        )
        self.assertIn("Laporan Ronda Sore", messages[0])
        self.assertNotIn("**", messages[0])
        self.assertNotIn("*", messages[0])


if __name__ == "__main__":
    unittest.main()

if __name__ == '__main__':
    unittest.main()
