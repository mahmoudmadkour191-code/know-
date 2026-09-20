from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class SurvivalAgent:
    def __init__(
        self,
        telegram,
        gemini,
        db,
        interval: int = 60,
        group_mentions: bool = True,
        allow_outbound: bool = True,
    ):
        self.telegram = telegram
        self.gemini = gemini
        self.db = db
        self.interval = interval
        self.group_mentions = group_mentions
        self.allow_outbound = allow_outbound
        self.running = False
        self.task: asyncio.Task | None = None
        self.started_at = 0.0
        self.status = "IDLE"
        self.last_action = "—"
        self.control_notifier: Callable[[str], Awaitable[None]] | None = None
        self.gemini.on_activity = self._activity

    async def _activity(self, text: str) -> None:
        self.last_action = text[:180]
        if self.control_notifier:
            await self.control_notifier(self.last_action)

    async def _incoming(self, event) -> None:
        if not self.running:
            return

        text = (event.raw_text or "").strip()
        if not text:
            return

        if event.is_private:
            await self._reply_to_event(event)
            return

        if self.group_mentions:
            me = self.telegram.me
            username = getattr(me, "username", None)
            mention = f"@{username}" if username else ""
            replied = bool(event.is_reply)

            if (mention and mention.lower() in text.lower()) or replied:
                await self._reply_to_event(event)

    async def _reply_to_event(self, event) -> None:
        sender = await event.get_sender()
        sender_name = (
            getattr(sender, "first_name", None)
            or getattr(sender, "username", None)
            or "there"
        )

        chat_id = event.chat_id
        self.status = "RESPONDING"

        context = {
            "mode": "incoming_message",
            "sender_name": sender_name,
            "chat_id": chat_id,
            "message_id": event.message.id,
            "message": event.raw_text[:5000],
        }

        try:
            answer = await self.gemini.run(
                "Respond naturally to this Telegram message. "
                "Keep the response concise and useful. "
                "Use a tool only when genuinely necessary. "
                "Never invent facts or actions.\n\n"
                f"Message from {sender_name}: {event.raw_text}",
                context,
            )

            if answer:
                await self.telegram.send(
                    chat_id,
                    answer,
                    reply_to=event.message.id,
                )
                self.db.incr("messages_sent")

        except Exception as exc:
            self.db.log(f"Reply failure: {exc}", "ERROR")
        finally:
            self.status = "RUNNING"

    async def start(self) -> None:
        if self.running:
            return

        if not self.telegram.client:
            raise RuntimeError("Link a Telegram user account first")

        self.running = True
        self.started_at = time.time()
        self.status = "RUNNING"
        self.task = asyncio.create_task(
            self._loop(),
            name="survival-agent-loop",
        )
        self.db.log("Agent started")

    async def stop(self) -> None:
        self.running = False
        self.status = "STOPPED"

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

        self.db.log("Agent stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(2)

        while self.running:
            try:
                self.status = "THINKING"

                snapshot = self.db.snapshot()
                recent = [
                    dict(row)
                    for row in self.db.recent_events(8)
                ]

                instruction = (
                    "Act autonomously for the survival experiment. "
                    "Review the current state, then take at most one "
                    "high-value step this cycle. Search for legitimate "
                    "opportunities if useful. Do not spam or mass-DM. "
                    "If there is no concrete action worth taking, wait. "
                    "Do not invent income or outcomes.\n\n"
                    f"STATE={snapshot}\n"
                    f"RECENT_EVENTS={recent}\n"
                    f"OUTBOUND_ALLOWED={self.allow_outbound}"
                )

                if not self.allow_outbound:
                    instruction += (
                        "\nDo not send outbound prospecting messages "
                        "in this mode."
                    )

                answer = await self.gemini.run(
                    instruction,
                    {
                        "mode": "autonomous_cycle",
                        "state": snapshot,
                    },
                )

                self.last_action = answer[:180]
                self.status = "RUNNING"

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                self.status = "ERROR"
                self.db.log(
                    f"Agent loop error: {exc}",
                    "ERROR",
                )
                await asyncio.sleep(10)

            await asyncio.sleep(self.interval)
