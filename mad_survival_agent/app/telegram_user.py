from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import StringSession

from .crypto import SecretBox
from .db import Database


@dataclass(slots=True)
class PendingLogin:
    client: TelegramClient
    phone: str
    phone_code_hash: str


class TelegramUser:
    def __init__(self, api_id: int, api_hash: str, db: Database, secret_box: SecretBox,
                 on_incoming: Callable[[object], Awaitable[None]],
                 on_flood_wait: Callable[[int], Awaitable[None]]):
        self.api_id = api_id
        self.api_hash = api_hash
        self.db = db
        self.secret_box = secret_box
        self.on_incoming = on_incoming
        self.on_flood_wait = on_flood_wait
        self.client: TelegramClient | None = None
        self.pending: PendingLogin | None = None
        self.me = None

    def _new_client(self, session: str = "") -> TelegramClient:
        return TelegramClient(StringSession(session), self.api_id, self.api_hash)

    async def restore(self) -> bool:
        encrypted = self.db.get("telegram_session")
        if not encrypted:
            return False
        session = self.secret_box.decrypt(encrypted)
        client = self._new_client(session)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            self.db.delete("telegram_session")
            return False
        self.client = client
        self._register_handlers()
        self.me = await client.get_me()
        self.db.log(f"Restored Telegram session for {getattr(self.me, 'username', None) or self.me.id}")
        return True

    async def start_login(self, phone: str) -> None:
        if self.pending:
            raise RuntimeError("A login is already in progress")
        client = self._new_client()
        await client.connect()
        sent = await client.send_code_request(phone)
        self.pending = PendingLogin(client, phone, sent.phone_code_hash)

    async def complete_code(self, code: str) -> bool:
        if not self.pending:
            raise RuntimeError("No login is waiting for a code")
        pending = self.pending
        try:
            await pending.client.sign_in(phone=pending.phone, code=code, phone_code_hash=pending.phone_code_hash)
        except SessionPasswordNeededError:
            return False
        await self._finish_pending()
        return True

    async def complete_2fa(self, password: str) -> None:
        if not self.pending:
            raise RuntimeError("No login is waiting for 2FA")
        await self.pending.client.sign_in(password=password)
        await self._finish_pending()

    async def cancel_login(self) -> None:
        if self.pending:
            await self.pending.client.disconnect()
        self.pending = None

    async def _finish_pending(self) -> None:
        assert self.pending
        client = self.pending.client
        session = StringSession.save(client.session)
        self.db.set("telegram_session", self.secret_box.encrypt(session))
        self.client = client
        self._register_handlers()
        self.me = await client.get_me()
        self.db.log("Telegram user session linked")
        self.pending = None

    def _register_handlers(self) -> None:
        assert self.client
        self.client.remove_event_handler(self._event_handler)
        self.client.add_event_handler(self._event_handler, events.NewMessage(incoming=True))

    async def _event_handler(self, event) -> None:
        try:
            await self.on_incoming(event)
        except FloodWaitError as exc:
            await self.on_flood_wait(exc.seconds)
        except Exception as exc:
            self.db.log(f"Incoming handler error: {exc}", "ERROR")

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
        self.client = None
        self.me = None

    async def send(self, chat_id, text: str, reply_to: int | None = None):
        if not self.client:
            raise RuntimeError("Telegram account is not linked")
        try:
            return await self.client.send_message(chat_id, text, reply_to=reply_to)
        except FloodWaitError as exc:
            await self.on_flood_wait(exc.seconds)
            raise

    async def search_global(self, query: str, limit: int = 10) -> list[dict]:
        if not self.client:
            raise RuntimeError("Telegram account is not linked")
        results = []
        async for msg in self.client.iter_messages(None, search=query, limit=min(max(limit, 1), 25)):
            text = (msg.raw_text or "").strip().replace("\n", " ")
            if not text:
                continue
            chat = await msg.get_chat()
            results.append({
                "message_id": msg.id,
                "chat_id": msg.chat_id,
                "chat_title": getattr(chat, "title", None) or getattr(chat, "username", None),
                "date": msg.date.isoformat() if msg.date else None,
                "text": text[:800],
                "sender_id": msg.sender_id,
            })
        return results

    async def recent(self, chat_id, limit: int = 15) -> list[dict]:
        if not self.client:
            raise RuntimeError("Telegram account is not linked")
        messages = await self.client.get_messages(chat_id, limit=min(max(limit, 1), 30))
        return [{
            "id": m.id,
            "date": m.date.isoformat() if m.date else None,
            "out": bool(m.out),
            "text": (m.raw_text or "")[:1200],
            "sender_id": m.sender_id,
        } for m in messages if (m.raw_text or "").strip()]
