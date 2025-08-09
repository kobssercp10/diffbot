"""Utility helpers for reading the saved update JSON files."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict

from .differ import OUT_DIR, get_updates_async


def bot_uid_from_token(token: str) -> str:
    """Extract the numeric identifier from a bot token."""

    t = token.strip()
    if t.startswith("bot"):
        t = t[3:]
    return t.split(":", 1)[0]


async def load_updates(token: str, new: bool = False) -> Dict[str, Any]:
    """Load the saved difference for ``token``.

    When ``new`` is ``True`` or the file does not yet exist the latest
    updates are fetched from Telegram first.
    """

    uid = bot_uid_from_token(token)
    path = os.path.join(OUT_DIR, f"{uid}.json")
    os.makedirs(OUT_DIR, exist_ok=True)

    if new or not os.path.isfile(path):
        await get_updates_async(token, save_to_json=True)

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_updates_sync(token: str, new: bool = False) -> Dict[str, Any]:
    """Synchronous wrapper around :func:`load_updates`."""

    return asyncio.run(load_updates(token, new=new))


__all__ = ["load_updates", "load_updates_sync", "bot_uid_from_token"]

