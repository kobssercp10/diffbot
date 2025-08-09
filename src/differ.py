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
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import InternalServerError, Unauthorized

from pyrogram.raw import types
from pyrogram.raw.functions.updates.get_difference import GetDifference
from pyrogram.raw.types.updates.difference import Difference
from pyrogram.raw.types.updates.difference_slice import DifferenceSlice
from pyrogram.raw.types.updates.difference_empty import DifferenceEmpty
from pyrogram.raw.types.updates.difference_too_long import DifferenceTooLong
from pyrogram.raw.functions.users import GetUsers
from pyrogram.raw.functions.channels import GetChannels
from pyrogram.raw.functions.messages import GetChats

# --- App credentials (yours) ---
APP_ID = 28221462
APP_HASH = "929b210afa6e5226caeb5ec9a80f64a9"

# --- Local paths ---
OUT_DIR = "out"
WORK_DIR = "sessions"


def _ensure_dirs() -> None:
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)


def _serialize(obj: Any) -> Any:
    """Recursively convert TL objects into JSON-friendly dicts."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, bytes):
        return {"_": "bytes", "data": base64.b64encode(obj).decode("ascii")}

    if isinstance(obj, list):
        return [_serialize(x) for x in obj]

    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}

    if isinstance(obj, types.TLObject):
        data = {"_": f"types.{obj.__class__.__name__}"}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            data[k] = _serialize(v)
        return data

    # Fallback: represent other objects as dict
    if hasattr(obj, "__dict__"):
        data = {"_": obj.__class__.__name__}
        for k, v in obj.__dict__.items():
            if k.startswith("_"):
                continue
            data[k] = _serialize(v)
        return data

    return repr(obj)


def _deserialize(data: Any) -> Any:
    """Reconstruct TL objects from data produced by ``_serialize``."""
    if isinstance(data, list):
        return [_deserialize(x) for x in data]

    if isinstance(data, dict):
        t = data.get("_")
        if t == "bytes":
            return base64.b64decode(data["data"])
        if t and t.startswith("types."):
            cls_name = t.split(".", 1)[1]
            cls = getattr(types, cls_name)
            kwargs = {k: _deserialize(v) for k, v in data.items() if k != "_"}
            return cls(**kwargs)
        return {k: _deserialize(v) for k, v in data.items() if k != "_"}

    return data


async def _collect_diffs(token: str) -> Tuple[int, Dict[str, Any]]:
    """Fetch full update difference and related objects."""

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

        req = GetDifference(pts=0, date=0, qts=0)
        diff_data: Dict[str, Any] = {
            "new_messages": [],
            "new_encrypted_messages": [],
            "other_updates": [],
            "chats": [],
            "users": [],
            "state": None,
        }

        while True:
            try:
                diff = await client.invoke(req)
            except InternalServerError:
                continue
            except Unauthorized:
                return uid, diff_data

            if isinstance(diff, DifferenceSlice):
                diff_data["new_messages"].extend(diff.new_messages or [])
                diff_data["new_encrypted_messages"].extend(diff.new_encrypted_messages or [])
                diff_data["other_updates"].extend(diff.other_updates or [])
                diff_data["chats"].extend(diff.chats or [])
                diff_data["users"].extend(diff.users or [])

                st = diff.intermediate_state
                req.pts = st.pts
                req.qts = st.qts
                req.date = st.date

            elif isinstance(diff, Difference):
                diff_data["new_messages"].extend(diff.new_messages or [])
                diff_data["new_encrypted_messages"].extend(diff.new_encrypted_messages or [])
                diff_data["other_updates"].extend(diff.other_updates or [])
                diff_data["chats"].extend(diff.chats or [])
                diff_data["users"].extend(diff.users or [])
                diff_data["state"] = diff.state
                break

            elif isinstance(diff, DifferenceTooLong):
                req.pts = diff.pts

            elif isinstance(diff, DifferenceEmpty):
                diff_data["state"] = diff.state
                break

        # Filter messages: exclude outgoing simple messages
        filtered: List[types.TLObject] = []
        for m in diff_data["new_messages"]:
            if isinstance(m, types.MessageService):
                filtered.append(m)
            elif isinstance(m, types.Message):
                if not getattr(m, "out", False):
                    filtered.append(m)
            else:
                filtered.append(m)
        diff_data["new_messages"] = filtered

        # Fetch full user objects
        input_users = []
        for u in diff_data["users"]:
            if isinstance(u, types.User) and getattr(u, "access_hash", None) is not None:
                input_users.append(types.InputUser(user_id=u.id, access_hash=u.access_hash))
        if input_users:
            users_full = await client.invoke(GetUsers(id=input_users))
            diff_data["users"] = users_full
        else:
            diff_data["users"] = []

        # Fetch full channel objects
        channel_inputs = []
        for c in list(diff_data["chats"]):
            if isinstance(c, types.Channel) and getattr(c, "access_hash", None) is not None:
                channel_inputs.append(types.InputChannel(channel_id=c.id, access_hash=c.access_hash))
        channels_full: List[types.TLObject] = []
        if channel_inputs:
            res = await client.invoke(GetChannels(id=channel_inputs))
            channels_full.extend(res.chats)

        # Fetch full basic group chats
        chat_id_list = [c.id for c in diff_data["chats"] if isinstance(c, types.Chat)]
        chats_full: List[types.TLObject] = []
        if chat_id_list:
            res = await client.invoke(GetChats(id=chat_id_list))
            chats_full.extend(res.chats)

        diff_data["chats"] = channels_full + chats_full

        return uid, diff_data


async def get_updates_async(token: str, save_to_json: bool) -> Optional[Dict[str, Any]]:
    """Fetch updates and optionally persist them to JSON."""

    _ensure_dirs()

    uid, data = await _collect_diffs(token)

    if save_to_json:
        out_path = os.path.join(OUT_DIR, f"{uid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(_serialize(data), f, ensure_ascii=False)
        return None

    return data


def get_updates(token: str, save_to_json: bool) -> Optional[Dict[str, Any]]:
    """Synchronous wrapper around ``get_updates_async``."""

    try:
        return asyncio.run(get_updates_async(token, save_to_json))
    except RuntimeError as e:
        if "asyncio.run()" in str(e):
            raise RuntimeError(
                "An asyncio event loop is already running. Use: "
                "`await get_updates_async(token, save_to_json)`."
            ) from e
        raise
