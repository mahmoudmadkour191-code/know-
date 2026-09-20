from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from google import genai

from .db import Database
from .prompt import SYSTEM_PROMPT
from .telegram_user import TelegramUser


class GeminiAgent:
    def __init__(self, api_key: str, model: str, telegram: TelegramUser, db: Database, max_steps: int = 8):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.telegram = telegram
        self.db = db
        self.max_steps = max_steps
        self._interaction_id: str | None = None
        self._lock = asyncio.Lock()
        self.on_activity: Callable[[str], Awaitable[None]] | None = None

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [
            {"type": "google_search"},
            {"type": "url_context"},
            {"type": "function", "name": "telegram_global_search",
             "description": "Search messages visible to this Telegram account across Telegram for legitimate public opportunities or context.",
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}
             }, "required": ["query"]}},
            {"type": "function", "name": "telegram_recent_messages",
             "description": "Read recent messages in a known chat before responding.",
             "parameters": {"type": "object", "properties": {
                 "chat_id": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}
             }, "required": ["chat_id"]}},
            {"type": "function", "name": "send_telegram_message",
             "description": "Send one targeted Telegram message to a specific chat. Use only when useful and appropriate.",
             "parameters": {"type": "object", "properties": {
                 "chat_id": {"type": "integer"}, "text": {"type": "string"}, "reply_to": {"type": "integer"}
             }, "required": ["chat_id", "text"]}},
            {"type": "function", "name": "record_income",
             "description": "Record legitimate received income. Never invent a payment.",
             "parameters": {"type": "object", "properties": {
                 "amount": {"type": "number"}, "note": {"type": "string"}
             }, "required": ["amount", "note"]}},
            {"type": "function", "name": "record_expense",
             "description": "Record a legitimate experiment expense. Never invent an expense.",
             "parameters": {"type": "object", "properties": {
                 "amount": {"type": "number"}, "note": {"type": "string"}
             }, "required": ["amount", "note"]}},
        ]

    async def _notify(self, text: str) -> None:
        self.db.log(text)
        if self.on_activity:
            try:
                await self.on_activity(text)
            except Exception:
                pass

    async def _call_model(self, **kwargs):
        return await asyncio.to_thread(self.client.interactions.create, **kwargs)

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "telegram_global_search":
            result = await self.telegram.search_global(args["query"], args.get("limit", 10))
            self.db.incr("jobs_found", len(result))
            return {"results": result}
        if name == "telegram_recent_messages":
            return {"messages": await self.telegram.recent(args["chat_id"], args.get("limit", 15))}
        if name == "send_telegram_message":
            sent = await self.telegram.send(args["chat_id"], args["text"], args.get("reply_to"))
            self.db.incr("messages_sent")
            self.db.incr("jobs_contacted")
            return {"ok": True, "message_id": getattr(sent, "id", None)}
        if name == "record_income":
            amount = float(args["amount"])
            if amount <= 0:
                return {"ok": False, "error": "Income amount must be positive."}
            self.db.incr("cash", amount)
            self.db.log(f"Income +${amount:.2f}: {args['note']}")
            self.db.incr("jobs_completed")
            return {"ok": True, "cash": self.db.stat("cash")}
        if name == "record_expense":
            amount = float(args["amount"])
            if amount <= 0 or amount > self.db.stat("cash"):
                return {"ok": False, "error": "Expense exceeds available experiment cash."}
            self.db.incr("cash", -amount)
            self.db.log(f"Expense -${amount:.2f}: {args['note']}")
            return {"ok": True, "cash": self.db.stat("cash")}
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def _extract_output_text(self, interaction) -> str:
        text = getattr(interaction, "output_text", None)
        if text:
            return text.strip()
        chunks: list[str] = []
        for step in getattr(interaction, "steps", []) or []:
            if getattr(step, "type", None) == "model_output":
                for content in getattr(step, "content", []) or []:
                    if getattr(content, "type", None) == "text":
                        chunks.append(getattr(content, "text", ""))
        return "\n".join(x for x in chunks if x).strip()

    async def run(self, user_input: str, context: dict[str, Any] | None = None) -> str:
        async with self._lock:
            payload = user_input
            if context:
                payload += "\n\nCURRENT CONTEXT:\n" + json.dumps(context, ensure_ascii=False, default=str)
            kwargs: dict[str, Any] = {
                "model": self.model, "input": payload,
                "tools": self._tool_specs(), "system_instruction": SYSTEM_PROMPT,
            }
            if self._interaction_id:
                kwargs["previous_interaction_id"] = self._interaction_id
            interaction = await self._call_model(**kwargs)

            for _ in range(self.max_steps):
                calls = [
                    s for s in (getattr(interaction, "steps", []) or [])
                    if getattr(s, "type", None) == "function_call"
                ]
                self._interaction_id = interaction.id
                if not calls:
                    break
                await self._notify("Tool calls: " + ", ".join(getattr(c, "name", "?") for c in calls))
                results = []
                for call in calls:
                    try:
                        args = getattr(call, "arguments", {}) or {}
                        result = await self._execute_tool(call.name, args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                    results.append({
                        "type": "function_result",
                        "name": call.name,
                        "call_id": call.id,
                        "result": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                    })
                interaction = await self._call_model(
                    model=self.model,
                    previous_interaction_id=self._interaction_id,
                    input=results,
                    tools=self._tool_specs(),
                    system_instruction=SYSTEM_PROMPT,
                )

            self._interaction_id = getattr(interaction, "id", self._interaction_id)
            text = self._extract_output_text(interaction)
            return (text or "تمام، هراجع الموضوع وأتحرك لما يكون عندي خطوة مفيدة.")[:4000]
