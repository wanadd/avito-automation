import asyncio
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.integrations.telegram.types import TelegramAuthError, TelegramNetworkError, TelegramRateLimitError


TOKEN_PATH_RE = re.compile(r"/bot[^/\s]+/")


def redact_telegram_token(value: str, token: str | None = None) -> str:
    redacted = TOKEN_PATH_RE.sub("/bot[redacted]/", value)
    if token:
        redacted = redacted.replace(token, "[redacted]")
    return redacted


@dataclass(frozen=True)
class TelegramBotApiClient:
    token: str
    base_url: str = "https://api.telegram.org"
    request_timeout_seconds: int = 35

    def method_url(self, method: str) -> str:
        return f"{self.base_url.rstrip('/')}/bot{self.token}/{method}"

    def sanitized_method_url(self, method: str) -> str:
        return redact_telegram_token(self.method_url(method), self.token)

    async def request(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._request_sync, method, payload or {})

    def _request_sync(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.method_url(method),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout_seconds) as response:
                raw = response.read()
                body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retry_after = exc.headers.get("Retry-After")
            if exc.code == 429:
                raise TelegramRateLimitError(int(retry_after or 0)) from exc
            if exc.code in {401, 403}:
                raise TelegramAuthError("Telegram Bot API authentication failed") from exc
            if 500 <= exc.code <= 599:
                raise TelegramNetworkError(f"Telegram Bot API transient HTTP {exc.code}") from exc
            raise TelegramNetworkError(f"Telegram Bot API HTTP {exc.code}") from exc
        except (OSError, TimeoutError) as exc:
            raise TelegramNetworkError("Telegram Bot API request failed") from exc
        except json.JSONDecodeError as exc:
            raise TelegramNetworkError("Telegram Bot API returned malformed JSON") from exc

        if not isinstance(body, dict) or body.get("ok") is not True:
            description = str(body.get("description", "Telegram Bot API request failed")) if isinstance(body, dict) else "Telegram Bot API request failed"
            retry_after = None
            if isinstance(body, dict):
                parameters = body.get("parameters")
                if isinstance(parameters, dict):
                    retry_after = parameters.get("retry_after")
            if retry_after is not None:
                raise TelegramRateLimitError(int(retry_after))
            raise TelegramNetworkError(redact_telegram_token(description, self.token))
        result = body.get("result")
        return result if isinstance(result, dict) else {"result": result}

    async def get_me(self) -> dict[str, Any]:
        return await self.request("getMe")

    async def get_updates(self, *, offset: int | None, timeout: int, limit: int) -> list[dict[str, Any]]:
        result = await self.request("getUpdates", {"offset": offset, "timeout": timeout, "limit": limit})
        updates = result.get("result")
        return updates if isinstance(updates, list) else []

    async def send_message(self, *, chat_id: int, text: str) -> None:
        await self.request("sendMessage", {"chat_id": chat_id, "text": text})

    async def get_file(self, *, file_id: str) -> dict[str, Any]:
        return await self.request("getFile", {"file_id": file_id})


def build_telegram_prices_bot_client() -> TelegramBotApiClient:
    settings = get_settings()
    if not settings.telegram_prices_bot_token:
        raise TelegramAuthError("Telegram prices bot token is not configured")
    return TelegramBotApiClient(
        token=settings.telegram_prices_bot_token,
        base_url=settings.telegram_api_base_url,
        request_timeout_seconds=settings.telegram_prices_poll_timeout_seconds + 5,
    )
