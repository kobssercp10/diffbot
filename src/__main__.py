import asyncio
from typing import Any, Callable, Dict, List

from .loader import load_difference

TOKEN = "7592149177:AAF1kLRe-7w1TKNtoNN9WUpDpITfvc021qU"  # bot token
NEW = True  # set False to use cached data


def _print_items(
    items: List[Dict[str, Any]], type_name: str, formatter: Callable[[Dict[str, Any]], str]
) -> None:
    for i, item in enumerate(items, start=1):
        details = formatter(item)
        print(f"{i}. {type_name}: {details}")
    print(f"Total {type_name.lower()}s: {len(items)}")


async def main() -> None:
    diff = await load_difference(TOKEN, new=NEW)

    messages = diff.get("new_messages", [])
    chats = diff.get("chats", [])
    users = diff.get("users", [])

    service_messages = [
        m for m in messages if m.get("action") or m.get("__type__") != "Message"
    ]
    _print_items(
        service_messages,
        "Service message",
        lambda m: f"{m.get('id')} {m.get('message') or m.get('action', {}).get('__type__', '')}".strip(),
    )

    groups = [c for c in chats if c.get("type") in ("group", "supergroup")]
    channels = [c for c in chats if c.get("type") == "channel"]

    def format_chat(c: Dict[str, Any]) -> str:
        cid = c.get("id", "")
        title = c.get("title") or ""
        username = c.get("username")
        uname = f"@{username}" if username else ""
        return f"{cid} {title} {uname}".strip()

    _print_items(groups, "Group", format_chat)
    _print_items(channels, "Channel", format_chat)

    def format_user(u: Dict[str, Any]) -> str:
        uid = u.get("id", "")
        name = " ".join(filter(None, [u.get("first_name"), u.get("last_name")]))
        username = u.get("username")
        uname = f"@{username}" if username else ""
        return f"{uid} {name} {uname}".strip()

    _print_items(users, "User", format_user)


if __name__ == "__main__":
    asyncio.run(main())

