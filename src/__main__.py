"""Simple command line entry point.

Running ``python -m diffbot`` downloads the latest updates for the token
stored in the ``TOKEN`` constant below and prints a short summary.  The
JSON result is saved to ``out/<bot_id>.json``.
"""

from __future__ import annotations

import asyncio

from .loader import load_updates

# Replace this with the token of the bot you want to inspect.
TOKEN = "7592149177:AAF1kLRe-7w1TKNtoNN9WUpDpITfvc021qU"


async def main() -> None:
    data = await load_updates(TOKEN, new=True)
    print(f"Loaded {len(data.get('new_messages', []))} messages")
    print(f"Loaded {len(data.get('users', []))} users")
    print(f"Loaded {len(data.get('chats', []))} chats")


if __name__ == "__main__":
    asyncio.run(main())

