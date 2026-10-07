"""Registry platform notifikasi (titik ekstensi Open/Closed Principle).

Modul ini mengagregasi kanal yang tersedia. Menambah platform baru cukup dengan
memasukkan modulnya ke daftar import di bawah — logika di `base.py` tidak berubah.
"""
from .base import (
    Channel,
    CommandRouter,
    InteractiveChannel,
    ReplyContext,
    all_channels,
    build_report_messages,
    build_welcome_text,
    dispatch_report,
    register_channel,
    run_listeners,
)

from . import discord  
from . import telegram  

__all__ = [
    "Channel",
    "CommandRouter",
    "InteractiveChannel",
    "ReplyContext",
    "all_channels",
    "build_report_messages",
    "build_welcome_text",
    "dispatch_report",
    "register_channel",
    "run_listeners",
]
