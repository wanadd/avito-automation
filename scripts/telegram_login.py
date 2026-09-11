import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.core.config import get_settings


async def main() -> None:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError as exc:
        raise SystemExit("Telethon is not installed. Install project dependencies first.") from exc

    settings = get_settings()
    if settings.telegram_api_id is None or not settings.telegram_api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in local environment or .env first.")

    session_path = Path(settings.telegram_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    phone = input("Telegram phone: ").strip()
    client = TelegramClient(str(session_path), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = input("Telegram login code: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass.getpass("Telegram 2FA password: ")
                await client.sign_in(password=password)
        if os.name != "nt":
            session_file = session_path.with_suffix(".session")
            if session_file.exists():
                session_file.chmod(0o600)
        print("Telegram session created under configured runtime directory.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
