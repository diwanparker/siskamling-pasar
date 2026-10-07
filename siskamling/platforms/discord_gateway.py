"""Klien Discord Gateway (WebSocket) minimal — stdlib saja.

Mengimplementasikan subset protokol yang dibutuhkan bot ini:
- Handshake WebSocket (RFC 6455) di atas TLS.
- Heartbeat (op 1) mengikuti interval dari HELLO (op 10).
- Identify (op 2) tanpa intent privileged.
- Dispatch (op 0), Reconnect (op 7), dan Invalid Session (op 9).

Tidak ada dependensi pihak ketiga.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import ssl
import struct
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

GATEWAY_HOST = "gateway.discord.gg"
GATEWAY_PATH = "/?v=10&encoding=json"

OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

INTENT_GUILDS = 1 << 0
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_DIRECT_MESSAGES = 1 << 12
INTENT_MESSAGE_CONTENT = 1 << 15  # privileged — aktifkan dulu di Discord Developer Portal

DEFAULT_USER_AGENT = "DiscordBot (+https://github.com/diwanparker/siskamling-pasar)"


def build_intents(enable_message_content: bool = False) -> int:
    """Intent non-privileged yang dibutuhkan, plus MESSAGE_CONTENT bila diminta."""
    intents = INTENT_GUILDS | INTENT_GUILD_MESSAGES | INTENT_DIRECT_MESSAGES
    if enable_message_content:
        intents |= INTENT_MESSAGE_CONTENT
    return intents


class DiscordGateway:
    """Koneksi Gateway Discord yang menyambung ulang otomatis saat terputus."""

    def __init__(
        self,
        token: str,
        *,
        intents: int,
        on_event: Callable[[str, Any], None],
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._token = token
        self._intents = intents
        self._on_event = on_event
        self._user_agent = user_agent
        self._socket: ssl.SSLSocket | None = None
        self._send_lock = threading.Lock()
        self._stopped = threading.Event()
        self._sequence: int | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def run_forever(self) -> None:
        """Sambungkan, dengar event, dan pulihkan koneksi tanpa henti."""
        while not self._stopped.is_set():
            try:
                self._run_session()
            except KeyboardInterrupt:
                logger.info("Gateway Discord dihentikan oleh pengguna")
                break
            except Exception as error:
                logger.warning("Koneksi gateway terputus (%s), menyambung ulang dalam 5 detik", error)
                self._stopped.wait(5)

    def stop(self) -> None:
        self._stopped.set()
        self._close_socket()

    def _run_session(self) -> None:
        self._socket = self._connect()
        self._sequence = None
        try:
            hello = self._read_payload()
            if hello.get("op") != OP_HELLO:
                raise ConnectionError(f"Pesan pertama bukan HELLO (op={hello.get('op')})")

            interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
            self._start_heartbeat(interval)
            self._identify()

            while not self._stopped.is_set():
                self._handle_payload(self._read_payload())
        finally:
            self._heartbeat_stop.set()
            self._close_socket()

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        if op == OP_DISPATCH:
            self._sequence = payload.get("s")
            self._emit(str(payload.get("t")), payload.get("d"))
        elif op == OP_HEARTBEAT:
            self._send_heartbeat()
        elif op == OP_RECONNECT:
            raise ConnectionError("server meminta reconnect")
        elif op == OP_INVALID_SESSION:
            logger.warning("Sesi Discord tidak valid, identifikasi ulang")
            raise ConnectionError("sesi tidak valid")
        elif op == OP_HEARTBEAT_ACK:
            logger.debug("Heartbeat Discord di-ack")

    def _emit(self, event_name: str, data: Any) -> None:
        try:
            self._on_event(event_name, data)
        except Exception as error:
            logger.error("Handler event Discord gagal untuk %s: %s", event_name, error)

    def _start_heartbeat(self, interval: float) -> None:
        self._heartbeat_stop.clear()

        def heartbeat_loop() -> None:
            while not self._heartbeat_stop.wait(interval):
                try:
                    self._send_heartbeat()
                except Exception:
                    return

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, name="discord-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _send_heartbeat(self) -> None:
        self._send_json({"op": OP_HEARTBEAT, "d": self._sequence})

    def _identify(self) -> None:
        self._send_json({
            "op": OP_IDENTIFY,
            "d": {
                "token": self._token,
                "intents": self._intents,
                "properties": {
                    "os": "linux",
                    "browser": "siskamling-pasar",
                    "device": "siskamling-pasar",
                },
            },
        })

    # ─── Transport WebSocket ───────────────────────────────────────

    def _connect(self) -> ssl.SSLSocket:
        raw_socket = socket.create_connection((GATEWAY_HOST, 443), timeout=30)
        context = ssl.create_default_context()
        sock = context.wrap_socket(raw_socket, server_hostname=GATEWAY_HOST)

        handshake_key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {GATEWAY_PATH} HTTP/1.1\r\n"
            f"Host: {GATEWAY_HOST}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {handshake_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: {self._user_agent}\r\n\r\n"
        )
        sock.sendall(handshake.encode("ascii"))

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Handshake WebSocket ditutup lebih awal")
            response += chunk

        status_line = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        if " 101 " not in status_line:
            raise ConnectionError(f"Handshake WebSocket gagal: {status_line}")

        sock.settimeout(None)
        return sock

    def _close_socket(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(0x1, json.dumps(payload).encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        sock = self._socket
        if sock is None:
            raise ConnectionError("Socket gateway belum tersambung")

        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)

        mask_key = os.urandom(4)
        masked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        with self._send_lock:
            sock.sendall(bytes(header) + mask_key + masked)

    def _read_payload(self) -> dict[str, Any]:
        return json.loads(self._recv_message().decode("utf-8"))

    def _recv_message(self) -> bytes:
        parts: list[bytes] = []
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 0x9:  # ping → balas pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                raise ConnectionError("Gateway menutup koneksi")
            parts.append(payload)
            if fin:
                return b"".join(parts)

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._recv_exact(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]

        mask_key = self._recv_exact(4) if masked else None
        payload = self._recv_exact(length) if length else b""
        if mask_key is not None:
            payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        sock = self._socket
        if sock is None:
            raise ConnectionError("Socket gateway belum tersambung")

        buffer = bytearray()
        while len(buffer) < length:
            chunk = sock.recv(length - len(buffer))
            if not chunk:
                raise ConnectionError("Koneksi gateway ditutup")
            buffer += chunk
        return bytes(buffer)
