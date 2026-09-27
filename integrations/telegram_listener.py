"""
integrations/telegram_listener.py
------------------------------------
Single Telegram ingestion point (product spec section 11): one
listener on the Ab Marshall channel, calling
core.signal_engine.handle_incoming_message() exactly ONCE per
message - never per-customer.

telethon is NOT installed in the build/verification sandbox (no
network access there), so this module has never actually been run.
The import is deferred into start() specifically so that failing to
`pip install telethon`, or running this on a machine with no
TELEGRAM_API_ID configured, cannot crash the web app or the rest of
the system - see main.py, which starts this in a background thread
wrapped in try/except for exactly that reason.

Verify this for real on your machine with your actual Telegram API
credentials before relying on it.
"""

import logging

from config import settings
from core.providers.registry import ACTIVE_PROVIDERS
from core.signal_engine import handle_incoming_message
from database.db import get_conn

logger = logging.getLogger("telegram_listener")


def start():
    """Blocks forever (telethon's run_until_disconnected). Call from a
    background thread, never from the main WSGI thread."""
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logger.warning("TELEGRAM_API_ID/API_HASH not configured - Telegram listener not started.")
        return

    from telethon import TelegramClient, events  # deferred: only required if actually starting

    client = TelegramClient(settings.TELEGRAM_SESSION, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    target_channel = ACTIVE_PROVIDERS["AbMarshall"].telegram_channel

    @client.on(events.NewMessage)
    async def handler(event):
        try:
            sender = None
            try:
                sender = (await event.get_sender()).username
            except Exception:
                pass
            if not sender and event.chat and getattr(event.chat, "username", None):
                sender = event.chat.username

            if not sender or sender.lower() != target_channel.lower():
                return  # not the Ab Marshall channel - ignore

            text = event.raw_text or ""
            result = handle_incoming_message(get_conn, text, sender=sender)
            logger.info("signal engine result: %s", result)
        except Exception as e:
            # A single malformed message must never take down the listener.
            logger.error("error handling Telegram message: %s", e)

    client.start(phone=lambda: settings.TELEGRAM_API_ID and input("Phone: "))
    logger.info("Telegram listener connected, watching %s", target_channel)
    client.run_until_disconnected()
