import asyncio
from .loader import load_difference

TOKEN = "7592149177:AAF1kLRe-7w1TKNtoNN9WUpDpITfvc021qU"  # bot token
NEW = True  # set False to use cached data


async def main() -> None:
    diff = await load_difference(TOKEN, new=NEW)
    print(f"Messages: {len(diff.get('new_messages', []))}")
    print(f"Encrypted messages: {len(diff.get('new_encrypted_messages', []))}")
    print(f"Other updates: {len(diff.get('other_updates', []))}")
    print(f"Chats: {len(diff.get('chats', []))}")
    print(f"Users: {len(diff.get('users', []))}")


if __name__ == "__main__":
    asyncio.run(main())
