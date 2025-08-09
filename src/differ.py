# differ.py
"""
Fetch and persist all updates for a bot using MTProto GetDifference.
Collects messages (excluding outgoing Message but including service messages),
users, groups and channels with full information.
"""

import os
import json
import base64
import asyncio
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pyrogram import Client
from pyrogram.errors import InternalServerError, Unauthorized
from pyrogram.raw.functions.updates.get_difference import GetDifference
from pyrogram.raw.types import Message
from pyrogram.raw.types.updates.difference import Difference
from pyrogram.raw.types.updates.difference_slice import DifferenceSlice
from pyrogram.raw.types.updates.difference_empty import DifferenceEmpty
from pyrogram.raw.types.updates.difference_too_long import DifferenceTooLong

# --- App credentials ---
APP_ID = 28221462
APP_HASH = "929b210afa6e5226caeb5ec9a80f64a9"

# --- Local paths ---
OUT_DIR = "out"
WORK_DIR = "sessions"


def _ensure_dirs() -> None:
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)


def _jsonable(obj: Any) -> Any:
    """Convert arbitrary objects (including TLObjects) into JSONable data."""
    from datetime import datetime
    from enum import Enum

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return {"__bytes__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.name
    if hasattr(obj, "__dict__"):
        d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        d["__type__"] = obj.__class__.__name__
        return _jsonable(d)
    return repr(obj)


def _chunked(seq: Iterable[int], size: int) -> Iterable[List[int]]:
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _channel_to_chat_id(channel_id: int) -> int:
    return int(f"-100{channel_id}")


def _basicgroup_to_chat_id(chat_id: int) -> int:
    return -int(chat_id)


async def _fetch_diff(token: str) -> Tuple[int, Dict[str, Any]]:
    session_name = str(token).split(":", 1)[0]
    async with Client(
        session_name,
        bot_token=token,
        api_id=APP_ID,
        api_hash=APP_HASH,
        workdir=WORK_DIR,
        workers=1,
        no_updates=True,
    ) as client:
        me = await client.get_me()
        uid = me.id

        req = GetDifference(pts=1, date=1, qts=0)
        messages: List[Any] = []
        new_encrypted: List[Any] = []
        other_updates: List[Any] = []
        chats_raw: List[Any] = []
        users_raw: List[Any] = []
        state = None

        while True:
            try:
                diff = await client.invoke(req)
            except InternalServerError:
                continue
            except Unauthorized:
                return uid, {}

            if isinstance(diff, DifferenceSlice):
                messages.extend(diff.new_messages or [])
                new_encrypted.extend(diff.new_encrypted_messages or [])
                other_updates.extend(diff.other_updates or [])
                chats_raw.extend(diff.chats or [])
                users_raw.extend(diff.users or [])
                st = diff.intermediate_state
                req.pts = st.pts
                req.qts = st.qts
                req.date = st.date
            elif isinstance(diff, Difference):
                messages.extend(diff.new_messages or [])
                new_encrypted.extend(diff.new_encrypted_messages or [])
                other_updates.extend(diff.other_updates or [])
                chats_raw.extend(diff.chats or [])
                users_raw.extend(diff.users or [])
                state = diff.state
                break
            elif isinstance(diff, DifferenceTooLong):
                req.pts = diff.pts
            elif isinstance(diff, DifferenceEmpty):
                state = getattr(diff, "state", None)
                break

        # filter messages: remove outgoing simple messages
        filtered: List[Any] = []
        for m in messages:
            if isinstance(m, Message) and m.out:
                continue
            filtered.append(m)

        # collect ids to fetch full info
        user_ids: Set[int] = set()
        channel_ids: Set[int] = set()
        chat_ids: Set[int] = set()

        for msg in filtered:
            peer = getattr(msg, "peer_id", None)
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

        for u in users_raw:
            user_ids.add(getattr(u, "id", 0))
        for c in chats_raw:
            cid = getattr(c, "id", None)
            if isinstance(cid, int):
                if getattr(c, "megagroup", False) or getattr(c, "gigagroup", False) or getattr(c, "broadcast", False):
                    channel_ids.add(cid)
                else:
                    chat_ids.add(cid)

        # fetch full users
        full_users: List[Any] = []
        for chunk in _chunked(sorted(user_ids), 100):
            if not chunk:
                continue
            res = await client.get_users(chunk)
            if not isinstance(res, list):
                res = [res]
            for u in res:
                if hasattr(u, "_client"):
                    delattr(u, "_client")
                full_users.append(u)

        # fetch full chats/channels
        full_chats: List[Any] = []
        for cid in sorted(channel_ids):
            chat_id = _channel_to_chat_id(cid)
            try:
                c = await client.get_chat(chat_id)
                if hasattr(c, "_client"):
                    delattr(c, "_client")
                full_chats.append(c)
            except Exception:
                continue
        for gid in sorted(chat_ids):
            chat_id = _basicgroup_to_chat_id(gid)
            try:
                c = await client.get_chat(chat_id)
                if hasattr(c, "_client"):
                    delattr(c, "_client")
                full_chats.append(c)
            except Exception:
                continue

        result = {
            "_": "types.updates.Difference",
            "new_messages": [_jsonable(m) for m in filtered],
            "new_encrypted_messages": [_jsonable(m) for m in new_encrypted],
            "other_updates": [_jsonable(u) for u in other_updates],
            "chats": [_jsonable(c) for c in full_chats],
            "users": [_jsonable(u) for u in full_users],
            "state": _jsonable(state),
        }

        return uid, result


async def get_updates_async(token: str, save_to_json: bool = True) -> Dict[str, Any]:
    _ensure_dirs()
    uid, diff = await _fetch_diff(token)
    if save_to_json and diff:
        out_path = os.path.join(OUT_DIR, f"{uid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(diff, f, ensure_ascii=False)
    return diff


def get_updates(token: str, save_to_json: bool = True) -> Dict[str, Any]:
    try:
        return asyncio.run(get_updates_async(token, save_to_json))
    except RuntimeError as e:
        if "asyncio.run()" in str(e):
            raise RuntimeError(
                "An asyncio event loop is already running. Use: `await get_updates_async(token, save_to_json)`."
            ) from e
        raise
