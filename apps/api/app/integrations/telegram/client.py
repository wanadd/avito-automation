from pathlib import Path

from app.core.config import get_settings
from app.integrations.telegram.types import (
    TelegramAccessError,
    TelegramAuthError,
    TelegramChatInfo,
    TelegramClientAdapter,
    TelegramCollectorError,
    TelegramMessage,
    TelegramNetworkError,
    TelegramRateLimitError,
)


class TelethonTelegramClientAdapter:
    def __init__(self, *, session_path: str, api_id: int, api_hash: str):
        self.session_path = session_path
        self.api_id = api_id
        self.api_hash = api_hash
        self._client = None

    async def connect(self) -> None:
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyError, SessionPasswordNeededError, UnauthorizedError
        except ImportError as exc:
            raise TelegramAuthError("Telethon is not installed") from exc

        try:
            Path(self.session_path).parent.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(self.session_path, self.api_id, self.api_hash)
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise TelegramAuthError("Telegram session is not authorized")
        except (AuthKeyError, SessionPasswordNeededError, UnauthorizedError) as exc:
            raise TelegramAuthError("Telegram session is not authorized") from exc
        except OSError as exc:
            raise TelegramNetworkError("Telegram connection failed") from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()

    async def get_chat(self, *, external_chat_id: int | None = None, username: str | None = None) -> TelegramChatInfo:
        try:
            entity = await self._client.get_entity(external_chat_id if external_chat_id is not None else username)
            latest = await self._client.get_messages(entity, limit=1)
        except Exception as exc:
            raise _map_telethon_error(exc) from exc
        return TelegramChatInfo(
            external_chat_id=int(entity.id),
            title=getattr(entity, "title", None),
            username=getattr(entity, "username", None),
            latest_message_id=latest[0].id if latest else None,
        )

    async def fetch_messages(self, chat_id: int, *, limit: int) -> list[TelegramMessage]:
        try:
            messages = await self._client.get_messages(chat_id, limit=limit)
        except Exception as exc:
            raise _map_telethon_error(exc) from exc
        return [_to_message(message) for message in messages]

    async def fetch_messages_after(self, chat_id: int, *, after_message_id: int | None, limit: int) -> list[TelegramMessage]:
        messages = await self.fetch_messages(chat_id, limit=limit)
        if after_message_id is None:
            return messages
        return [message for message in messages if message.message_id > after_message_id]

    async def get_message(self, chat_id: int, message_id: int) -> TelegramMessage | None:
        try:
            message = await self._client.get_messages(chat_id, ids=message_id)
        except Exception as exc:
            raise _map_telethon_error(exc) from exc
        return _to_message(message) if message is not None else None


def build_telegram_adapter() -> TelegramClientAdapter:
    settings = get_settings()
    if settings.telegram_api_id is None or not settings.telegram_api_hash:
        raise TelegramAuthError("Telegram API credentials are not configured")
    return TelethonTelegramClientAdapter(
        session_path=settings.telegram_session_path,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
    )


def _to_message(message) -> TelegramMessage:
    text = getattr(message, "message", None)
    media = getattr(message, "media", None)
    forward = getattr(message, "fwd_from", None)
    reply_to = getattr(message, "reply_to", None)
    sender_id = getattr(message, "sender_id", None)
    return TelegramMessage(
        message_id=message.id,
        date=message.date,
        text=text,
        edit_date=getattr(message, "edit_date", None),
        sender_id=int(sender_id) if sender_id is not None else None,
        reply_to_message_id=getattr(reply_to, "reply_to_msg_id", None) if reply_to else None,
        forward={"raw": str(forward)} if forward else None,
        has_media=media is not None,
        media_type=type(media).__name__ if media is not None else None,
        caption=text if media is not None and text else None,
        service=bool(getattr(message, "action", None)),
    )


def _map_telethon_error(exc: Exception) -> TelegramCollectorError:
    name = exc.__class__.__name__
    if name in {"UnauthorizedError", "AuthKeyError", "SessionPasswordNeededError"}:
        return TelegramAuthError("Telegram session is not authorized")
    if name in {"ChannelPrivateError", "UserNotParticipantError", "UsernameInvalidError", "UsernameNotOccupiedError"}:
        return TelegramAccessError("Telegram chat is inaccessible")
    if name == "FloodWaitError":
        return TelegramRateLimitError(int(getattr(exc, "seconds", 0)))
    if isinstance(exc, OSError):
        return TelegramNetworkError("Telegram connection failed")
    return TelegramNetworkError("Telegram API request failed")
