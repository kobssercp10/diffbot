# loader.py
import os
import json
from typing import Any, Dict, List

from .differ import OUT_DIR, get_updates_async, _deserialize

def bot_uid_from_token(token: str) -> str:
    t = token.strip()
    if t.startswith("bot"):
        t = t[3:]
    return t.split(":", 1)[0]

async def load_difference(token: str, new: bool = False) -> Dict[str, Any]:
    """Load previously dumped updates for a bot token."""

    uid = bot_uid_from_token(token)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, f"{uid}.json")

    if not os.path.isfile(json_path) or new:
        await get_updates_async(token, save_to_json=True)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return _deserialize(data)


async def load_messages(token: str, new: bool = False) -> List[Any]:
    """Convenience wrapper returning only ``new_messages``."""

    diff = await load_difference(token, new)
    return diff.get("new_messages", [])
