"""Download full update information from Telegram bots.

This module connects to Telegram using Pyrogram's raw ``GetDifference``
method and stores everything returned by the server: messages, service
messages, chats, users and the final update state.  In contrast to the
previous revision which only saved ``new_messages`` and attempted to
serialise TL objects using ``eval`` tricks, this version produces a
plain JSON file that mirrors the structure shown in Telegram's MTProto
documentation.

Only incoming regular messages are saved – outgoing messages of type
``Message`` are discarded.  Service messages (``MessageService``) are
always preserved even if they were sent by the bot itself.

Example
-------

>>> from diffbot.differ import get_updates
>>> get_updates("123456:ABCDEF", save_to_json=True)

This will create ``out/<bot_id>.json`` containing a structure similar to
``updates.Difference``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pyrogram import Client
from pyrogram.errors import InternalServerError, Unauthorized
from pyrogram.raw.functions.updates.get_difference import GetDifference
from pyrogram.raw.types import Message, MessageService
from pyrogram.raw.types.updates.difference import Difference
from pyrogram.raw.types.updates.difference_empty import DifferenceEmpty
from pyrogram.raw.types.updates.difference_slice import DifferenceSlice
from pyrogram.raw.types.updates.difference_too_long import DifferenceTooLong

# ---------------------------------------------------------------------------
# Credentials and paths

APP_ID = 28221462
APP_HASH = "929b210afa6e5226caeb5ec9a80f64a9"

OUT_DIR = "out"
WORK_DIR = "sessions"


def _ensure_dirs() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers

def _tl_to_dict(obj: Any) -> Any:
    """Convert Pyrogram TLObjects into plain Python dictionaries."""

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_tl_to_dict(x) for x in obj]

    if isinstance(obj, Enum):
        return obj.name

    if hasattr(obj, "__dict__"):
        data: Dict[str, Any] = {"_": f"types.{obj.__class__.__name__}"}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            data[k] = _tl_to_dict(v)
        return data

    return repr(obj)


def _chunked(it: Iterable[int], size: int) -> Iterable[List[int]]:
    seq = list(it)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _channel_to_chat_id(channel_id: int) -> int:
    return int(f"-100{channel_id}")


def _basicgroup_to_chat_id(chat_id: int) -> int:
    return -int(chat_id)


# ---------------------------------------------------------------------------
# Core difference collection

async def _collect_difference(token: str) -> Tuple[int, Dict[str, Any]]:
    """Collect the full ``updates.Difference`` for the given bot token."""

    session_name = str(token).split(":", 1)[0]

    async with Client(
        session_name,
        bot_token=token,
        api_id=APP_ID,
        api_hash=APP_HASH,
        workdir=WORK_DIR,
        workers=1,
        no_updates=True,
    ) as app:
        me = await app.get_me()
        uid = me.id

        # Aggregated containers
        messages: List[Any] = []
        other_updates: List[Any] = []
        chats: List[Any] = []
        users: List[Any] = []
        new_encrypted: List[Any] = []
        state: Any = None

        req = GetDifference(pts=0, date=0, qts=0)

        while True:
            try:
                diff = await app.invoke(req)
            except InternalServerError:
                continue
            except Unauthorized:
                return uid, {}

            if isinstance(diff, DifferenceSlice):
                messages.extend(diff.new_messages or [])
                other_updates.extend(diff.other_updates or [])
                chats.extend(diff.chats or [])
                users.extend(diff.users or [])
                new_encrypted.extend(diff.new_encrypted_messages or [])
                st = diff.intermediate_state
                req.pts = st.pts
                req.qts = st.qts
                req.date = st.date
                continue

            if isinstance(diff, DifferenceTooLong):
                req.pts = diff.pts
                continue

            if isinstance(diff, DifferenceEmpty):
                state = diff.state
                break

            if isinstance(diff, Difference):
                messages.extend(diff.new_messages or [])
                other_updates.extend(diff.other_updates or [])
                chats.extend(diff.chats or [])
                users.extend(diff.users or [])
                new_encrypted.extend(diff.new_encrypted_messages or [])
                state = diff.state
                break

        # ------------------------------------------------------------------
        # Filter and gather identifiers for full info
        filtered_messages: List[Any] = []
        user_ids: set[int] = set()
        channel_ids: set[int] = set()
        chat_ids: set[int] = set()

        for m in messages:
            if isinstance(m, Message) and getattr(m, "out", False):
                # Skip outgoing regular messages
                continue

            filtered_messages.append(m)
            peer = getattr(m, "peer_id", None)
            if peer is not None:
                uid = getattr(peer, "user_id", None)
                if isinstance(uid, int):
                    user_ids.add(uid)
                cid = getattr(peer, "channel_id", None)
                if isinstance(cid, int):
                    channel_ids.add(cid)
                gid = getattr(peer, "chat_id", None)
                if isinstance(gid, int):
                    chat_ids.add(gid)

        for u in users:
            if getattr(u, "id", None) is not None:
                user_ids.add(u.id)

        for c in chats:
            name = c.__class__.__name__
            if name == "Channel":
                channel_ids.add(c.id)
            elif name == "Chat":
                chat_ids.add(c.id)

        # Fetch full user information
        full_users: List[Any] = []
        if user_ids:
            for batch in _chunked(sorted(user_ids), 100):
                fetched = await app.get_users(batch)
                if not isinstance(fetched, list):
                    fetched = [fetched]
                full_users.extend(fetched)

        # Fetch full chat/channel information
        full_chats: List[Any] = []
        for cid in sorted(channel_ids):
            chat_id = _channel_to_chat_id(cid)
            try:
                full_chats.append(await app.get_chat(chat_id))
            except Exception:
                continue

        for gid in sorted(chat_ids):
            chat_id = _basicgroup_to_chat_id(gid)
            try:
                full_chats.append(await app.get_chat(chat_id))
            except Exception:
                continue

        result = {
            "_": "types.updates.Difference",
            "new_messages": [_tl_to_dict(m) for m in filtered_messages],
            "new_encrypted_messages": [_tl_to_dict(m) for m in new_encrypted],
            "other_updates": [_tl_to_dict(u) for u in other_updates],
            "chats": [_tl_to_dict(c) for c in full_chats],
            "users": [_tl_to_dict(u) for u in full_users],
            "state": _tl_to_dict(state),
        }

        return uid, result


# ---------------------------------------------------------------------------
# Public API

async def get_updates_async(token: str, save_to_json: bool) -> Optional[Dict[str, Any]]:
    """Fetch updates for ``token``.

    If ``save_to_json`` is ``True`` the result is written to
    ``out/<uid>.json`` and ``None`` is returned.  Otherwise the parsed
    dictionary is returned directly.
    """

    _ensure_dirs()
    uid, data = await _collect_difference(token)

    if save_to_json:
        path = os.path.join(OUT_DIR, f"{uid}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return None

    return data


def get_updates(token: str, save_to_json: bool) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper for :func:`get_updates_async`."""

    try:
        return asyncio.run(get_updates_async(token, save_to_json))
    except RuntimeError as e:  # pragma: no cover - helper for running loops
        if "asyncio.run" in str(e):
            raise RuntimeError(
                "An asyncio event loop is already running. Use "
                "`await get_updates_async(token, save_to_json)` instead."
            ) from e
        raise


__all__ = ["get_updates", "get_updates_async", "APP_ID", "APP_HASH", "OUT_DIR", "WORK_DIR"]

