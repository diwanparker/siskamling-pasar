import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siskamling.platforms.discord_gateway import (
    DiscordGateway,
    build_intents,
    INTENT_MESSAGE_CONTENT,
)


def masked_frame(opcode: int, payload: bytes) -> bytes:
    """Bangun frame WebSocket ter-mask ala klien (RFC 6455)."""
    mask_key = b"\x01\x02\x03\x04"
    masked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
    return bytes([0x80 | opcode, 0x80 | len(payload)]) + mask_key + masked


class TestIntents(unittest.TestCase):
    def test_default_intents_exclude_message_content(self):
        intents = build_intents()
        self.assertTrue(intents & (1 << 0))  # GUILDS
        self.assertFalse(intents & INTENT_MESSAGE_CONTENT)

    def test_opt_in_message_content(self):
        self.assertTrue(build_intents(True) & INTENT_MESSAGE_CONTENT)


class TestWebSocketFraming(unittest.TestCase):
    def setUp(self):
        self.gateway = DiscordGateway("token", intents=0, on_event=lambda event, data: None)

    def _socketpair(self):
        client, server = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(server.close)
        self.gateway._socket = client
        return server

    def test_recv_frame_unmasks_payload(self):
        server = self._socketpair()
        server.sendall(masked_frame(0x1, b"hello"))

        fin, opcode, payload = self.gateway._recv_frame()

        self.assertTrue(fin)
        self.assertEqual(opcode, 0x1)
        self.assertEqual(payload, b"hello")

    def test_send_frame_masks_payload(self):
        server = self._socketpair()
        self.gateway._send_frame(0x1, b"hi")

        header = server.recv(2)
        self.assertEqual(header[0], 0x81)  # FIN + text
        self.assertTrue(header[1] & 0x80)  # bit mask aktif
        self.assertEqual(header[1] & 0x7F, 2)

        mask_key = server.recv(4)
        data = server.recv(2)
        self.assertEqual(bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(data)), b"hi")

    def test_recv_message_reassembles_fragments(self):
        server = self._socketpair()
        # Frame pertama: opcode text, FIN=0
        server.sendall(bytes([0x01, 0x80 | 2]) + b"\x00\x00\x00\x00" + b"he")
        # Frame kedua: continuation, FIN=1
        server.sendall(bytes([0x80, 0x80 | 1]) + b"\x00\x00\x00\x00" + b"y")

        self.assertEqual(self.gateway._recv_message(), b"hey")


if __name__ == "__main__":
    unittest.main()
