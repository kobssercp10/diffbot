# list_users_from_messages.py
import asyncio
from collections import defaultdict
from typing import Iterable, List

from pyrogram import Client
from .loader import load_messages
from .differ import APP_ID, APP_HASH, WORK_DIR  # reuse your constants

TOKEN = "7592149177:AAF1kLRe-7w1TKNtoNN9WUpDpITfvc021qU"  # <-- your bot token here
new = True  # load new messages

def chunked(it: Iterable[int], size: int) -> Iterable[List[int]]:
    it = list(it)
    for i in range(0, len(it), size):
        yield it[i:i + size]

def channel_to_chat_id(channel_id: int) -> int:
    # Telegram supergroup/channel chat_id is -100<channel_id> (concatenation, not multiplication)
    return int(f"-100{channel_id}")

def basicgroup_to_chat_id(chat_id: int) -> int:
    # Basic group chat_id is the negative of its id
    return -int(chat_id)

async def main():
    # 1) Load & reconstruct messages
    msgs = await load_messages(TOKEN, new)

    # 2) Inspect and collect
    checked_messages = 0
    user_ids = set()                # incoming users only (m.out == False)
    channel_ids = set()             # raw channel_id from peer_id
    chat_ids = set()                # raw chat_id (basic groups)
    service_action_counts = defaultdict(int)
    other_types_counts = defaultdict(int)

    for m in msgs:
        checked_messages += 1

        # Peer classification: users, channels, chats
        peer = getattr(m, "peer_id", None)
        if peer is not None:
            uid = getattr(peer, "user_id", None)
            if isinstance(uid, int):
                if not getattr(m, "out", False):
                    user_ids.add(uid)
            cid = getattr(peer, "channel_id", None)
            if isinstance(cid, int):
                channel_ids.add(cid)
            gid = getattr(peer, "chat_id", None)
            if isinstance(gid, int):
                chat_ids.add(gid)

        # Message kind classification
        cls = m.__class__.__name__
        if cls == "MessageService":
            action = getattr(m, "action", None)
            action_name = action.__class__.__name__ if action else "UnknownAction"
            service_action_counts[action_name] += 1
        elif cls not in ("Message",):
            # Track other unusual message kinds (MessageEmpty, etc.)
            other_types_counts[cls] += 1

    # Quick summary
    print(f"Found {len(user_ids)} unique incoming user IDs.")
    print(f"Found {len(channel_ids)} unique channels.")
    print(f"Found {len(chat_ids)} unique basic groups (chats).")
    total_service = sum(service_action_counts.values())
    print(f"Found {total_service} service messages.")

    if other_types_counts:
        print("Other message types:", ", ".join(f"{k}={v}" for k, v in other_types_counts.items()))

    # 3) Fetch and print users, channels, and chats
    session_name = str(TOKEN).split(":", 1)[0]
    async with Client(
        session_name,
        bot_token=TOKEN,
        api_id=APP_ID,
        api_hash=APP_HASH,
        workdir=WORK_DIR,
        workers=1,
        no_updates=True,
    ) as app:
        # Users
        if user_ids:
            print("\n== Incoming users ==")
            for batch in chunked(sorted(user_ids), 100):
                users = await app.get_users(batch)
                if not isinstance(users, list):
                    users = [users]
                for u in users:
                    full_name = " ".join(filter(None, [u.first_name, u.last_name])) or "(no name)"
                    username = f"@{u.username}" if u.username else "(no username)"
                    print(f"USER {u.id}: {full_name} {username}")

        # Channels / Supergroups
        if channel_ids:
            print("\n== Channels / Supergroups ==")
            for ch in sorted(channel_ids):
                chat_id = channel_to_chat_id(ch)
                try:
                    c = await app.get_chat(chat_id)
                    title = getattr(c, "title", None) or getattr(c, "first_name", "") or "(no title)"
                    username = f"@{c.username}" if getattr(c, "username", None) else "(no username)"
                    print(f"CHANNEL {c.id}: {title} {username}")
                except Exception as e:
                    print(f"CHANNEL -100{ch}: <unavailable> ({type(e).__name__})")

        # Basic groups (legacy chats)
        if chat_ids:
            print("\n== Basic groups (chats) ==")
            for gid in sorted(chat_ids):
                chat_id = basicgroup_to_chat_id(gid)
                try:
                    c = await app.get_chat(chat_id)
                    title = getattr(c, "title", None) or "(no title)"
                    username = f"@{c.username}" if getattr(c, "username", None) else "(no username)"
                    print(f"CHAT {c.id}: {title} {username}")
                except Exception as e:
                    print(f"CHAT -{gid}: <unavailable> ({type(e).__name__})")

    # 4) End-of-run stats
    if service_action_counts:
        print("\n== Service messages by action ==")
        for name, count in sorted(service_action_counts.items()):
            print(f"{name}: {count}")

    print(f"\nTotal messages checked: {checked_messages}")

if __name__ == "__main__":
    asyncio.run(main())
