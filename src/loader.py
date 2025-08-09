# loader.py
import os
import json
import pyrogram
from typing import List, Any

from .differ import get_updates, get_updates_async, OUT_DIR  # re-use your module

def bot_uid_from_token(token: str) -> str:
    t = token.strip()
    if t.startswith("bot"):
        t = t[3:]
    return t.split(":", 1)[0]

async def load_messages(token: str, new=False) -> List[Any]:
    """
    Ensures JSON exists for the token (generates via get_updates if missing),
    loads it, then reconstructs TL objects via your eval(eval(...)) approach.
    Returns a flat list of TL objects (e.g., pyrogram.raw.types.Message).
    """
    uid = bot_uid_from_token(token)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, f"{uid}.json")

    if os.path.isfile(json_path) and not new:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        await get_updates_async(token, save_to_json=True)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    messages = []
    for item in (data or []):
        try:
            obj = eval(eval(json.dumps(item, ensure_ascii=False)))
            if isinstance(obj, list):
                messages.extend(obj)
            else:
                messages.append(obj)
        except Exception:
            print("***** Skipping invalid message *****")
            continue

    return messages
