import os
import json
from typing import Any, Dict

from .differ import get_updates_async, OUT_DIR


def bot_uid_from_token(token: str) -> str:
    t = token.strip()
    if t.startswith("bot"):
        t = t[3:]
    return t.split(":", 1)[0]


async def load_difference(token: str, new: bool = False) -> Dict[str, Any]:
    """Load saved updates for the given bot token.

    If no cached JSON exists or ``new`` is True, fetches data from Telegram
    using :func:`get_updates_async` and writes it to disk first.
    Returns the parsed JSON dictionary.
    """
    uid = bot_uid_from_token(token)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, f"{uid}.json")

    if not os.path.isfile(json_path) or new:
        await get_updates_async(token, save_to_json=True)

    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)
