from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class TelegramChatInfo:
    external_chat_id: int
    title: str | None = None
    username: str | None = None
    latest_message_id: int | None = None


@dataclass(frozen=True)
class TelegramMessage:
    message_id: int
    date: datetime
    text: str | None = None
    edit_date: datetime | None = None
    sender_id: int | None = None
    reply_to_message_id: int | None = None
    forward: dict | None = None
    has_media: bool = False
    media_type: str | None = None
    caption: str | None = None
    service: bool = False


class TelegramClientAdapter(Protocol):
    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_chat(self, *, external_chat_id: int | None = None, username: str | None = None) -> TelegramChatInfo: ...

    async def fetch_messages(self, chat_id: int, *, limit: int) -> list[TelegramMessage]: ...

    async def fetch_messages_after(self, chat_id: int, *, after_message_id: int | None, limit: int) -> list[TelegramMessage]: ...

    async def get_message(self, chat_id: int, message_id: int) -> TelegramMessage | None: ...


class TelegramCollectorError(Exception):
    pass


class TelegramAuthError(TelegramCollectorError):
    pass


class TelegramAccessError(TelegramCollectorError):
    pass


class TelegramNetworkError(TelegramCollectorError):
    pass


class TelegramRateLimitError(TelegramCollectorError):
    def __init__(self, wait_seconds: int):
        super().__init__(f"Telegram rate limit: retry after {wait_seconds}s")
        self.wait_seconds = wait_seconds
