# differ.py
# -----------------------------------------------------------
# Single-call API:
#   get_updates(token: str, save_to_json: bool) -> Optional[list]
#
# If save_to_json=True:
#   - writes JSON to out/<uid>.json
#   - returns None
#
# If save_to_json=False:
#   - returns a list of Pyrogram TL objects (raw messages)
#   - does not write any files
#
# Requires: pyrogram
# -----------------------------------------------------------

import os
import json
import base64
import asyncio
from typing import Any, List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import InternalServerError, Unauthorized

from pyrogram.raw.functions.updates.get_difference import GetDifference
from pyrogram.raw.types.updates.difference import Difference
from pyrogram.raw.types.updates.difference_slice import DifferenceSlice
from pyrogram.raw.types.updates.difference_empty import DifferenceEmpty
from pyrogram.raw.types.updates.difference_too_long import DifferenceTooLong

# --- App credentials (yours) ---
APP_ID = 28221462
APP_HASH = "929b210afa6e5226caeb5ec9a80f64a9"

# --- Local paths ---
OUT_DIR = "out"
WORK_DIR = "sessions"


def _ensure_dirs() -> None:
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)


def _to_jsonable(obj: Any) -> Any:
    """
    Best-effort conversion of Pyrogram raw TLObjects (and nested structures)
    into JSON-serializable data. Bytes are base64-encoded. Adds '__type__'
    to preserve the original class name for objects.
    """
    from datetime import datetime
    from enum import Enum

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, bytes):
        return {"__bytes__": base64.b64encode(obj).decode("ascii")}

    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(x) for x in obj]

    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return obj.name

    # Try a dict-like view of custom objects (e.g., TLObjects)
    # Keep only public attributes, annotate with type
    if hasattr(obj, "__dict__"):
        d = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        d["__type__"] = obj.__class__.__name__
        return _to_jsonable(d)

    # Fallback: string representation
    return repr(obj)


async def _collect_diffs(token: str) -> Tuple[int, List[Any]]:
    """
    Connect with a bot token, page through GetDifference, and collect
    all new_messages across slices.
    Returns (uid, messages_list).
    """
    # Use the numeric bot ID as the session name to avoid collisions
    session_name = str(token).split(":")[0]

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
        collected: List[Any] = []

        while True:
            try:
                diff = await client.invoke(req)
                print(diff)
                print(type(diff))
                print("--------------")
            except InternalServerError:
                # Transient server hiccup; just retry current req
                continue
            except Unauthorized:
                # Token revoked or invalid; return nothing for this uid
                return uid, []

            if isinstance(diff, DifferenceSlice):
                # Accumulate messages
                if diff.new_messages:
                    collected.extend(diff.new_messages)

                # Advance state
                st = diff.intermediate_state
                req.pts = st.pts
                req.qts = st.qts
                req.date = st.date

            elif isinstance(diff, Difference):
                if diff.new_messages:
                    collected.extend(diff.new_messages)
                break

            elif isinstance(diff, DifferenceTooLong):
                # Server tells us to jump to a newer pts
                req.pts = diff.pts

            elif isinstance(diff, DifferenceEmpty):
                # Nothing more to do
                break

        return uid, collected


async def get_updates_async(token: str, save_to_json: bool) -> Optional[List[Any]]:
    """
    Async entrypoint. If save_to_json=True, writes to OUT_DIR/<uid>.json and returns None.
    Otherwise returns a list of raw Pyrogram TLObjects.
    """
    _ensure_dirs()

    uid, messages = await _collect_diffs(token)

    if save_to_json:
        # Serialize once at the end to avoid partial/corrupt files
        out_path = os.path.join(OUT_DIR, f"{uid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(_to_jsonable(messages), f, ensure_ascii=False)
        return None

    # Return the raw Pyrogram objects (variables/objects in memory)
    return messages


def get_updates(token: str, save_to_json: bool) -> Optional[List[Any]]:
    """
    Sync wrapper. Call this from another script with only (token, bool).
    If an event loop is already running, import and use `await get_updates_async(...)`.
    """
    try:
        return asyncio.run(get_updates_async(token, save_to_json))
    except RuntimeError as e:
        # Helpful message if called from within a running loop (e.g., FastAPI, Jupyter)
        if "asyncio.run()" in str(e):
            raise RuntimeError(
                "An asyncio event loop is already running. "
                "Use: `await get_updates_async(token, save_to_json)`."
            ) from e
        raise
