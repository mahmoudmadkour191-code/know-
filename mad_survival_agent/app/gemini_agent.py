from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from google import genai
from google.genai import types

from .db import Database
from .prompt import SYSTEM_PROMPT
from .telegram_user import TelegramUser


class GeminiAgent:
    def __init__(self, api_key: str, model: str, telegram: TelegramUser, db: Database, max_steps: int = 3):
        self.client = genai.Client(api_key=api_key, vertexai=False)
        self.model = model
        self.telegram = telegram
        self.db = db
        self.max_steps = max_steps
        self._lock = asyncio.Lock()
        self.on_activity: Callable[[str], Awaitable[None]] | None = None
        self._history: list[types.Content] = []

    def _tool_specs(self) -> list[types.Tool]:
        declarations = [
            {
                "name": "telegram_global_search",
                "description": "Search messages visible to this Telegram account across Telegram for legitimate public opportunities or context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "telegram_recent_messages",
                "description": "Read recent messages in a known chat before responding.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "integer"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                    },
                    "required": ["chat_id"],
                },
            },
            {
                "name": "send_telegram_message",
                "description": "Send one targeted Telegram message to a specific chat. Use only when useful and appropriate.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "integer"},
                        "text": {"type": "string"},
                        "reply_to": {"type": "integer"},
                    },
                    "required": ["chat_id", "text"],
                },
            },
            {
                "name": "record_income",
                "description": "Record legitimate received income. Never invent a payment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["amount", "note"],
                },
            },
            {
                "name": "record_expense",
                "description": "Record a legitimate experiment expense. Never invent an expense.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {"type": "number"},
                        "note": {"type": "string"},
                    },
                    "required": ["amount", "note"],
                },
            },
        ]
        return [types.Tool(function_declarations=declarations)]

    async def _notify(self, text: str) -> None:
        self.db.log(text)
        if self.on_activity:
            try:
                await self.on_activity(text)
            except Exception:
                pass

    async def _call_model(self, contents: list[types.Content]):
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=self._tool_specs(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        return await asyncio.to_thread(
            self.client.models.generate_content,
            model=self.model,
            contents=contents,
            config=config,
        )

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
            self.db.log("Income +$%.2f: %s" % (amount, args["note"]))
            self.db.incr("jobs_completed")
            return {"ok": True, "cash": self.db.stat("cash")}
        if name == "record_expense":
            amount = float(args["amount"])
            if amount <= 0 or amount > self.db.stat("cash"):
                return {"ok": False, "error": "Expense exceeds available experiment cash."}
            self.db.incr("cash", -amount)
            self.db.log("Expense -$%.2f: %s" % (amount, args["note"]))
            return {"ok": True, "cash": self.db.stat("cash")}
        return {"ok": False, "error": "Unknown tool: %s" % name}

    async def run(self, user_input: str, context: dict[str, Any] | None = None) -> str:
        async with self._lock:
            text = user_input
            if context:
                text += "\n\nCURRENT CONTEXT:\n" + json.dumps(
                    context, ensure_ascii=False, default=str
                )
            if len(self._history) > 20:
                self._history = self._history[-20:]
            self._history.append(types.Content(role="user", parts=[types.Part(text=text)]))

            for _ in range(self.max_steps):
                response = await self._call_model(self._history)
                if not response.candidates:
                    return "تمام، حصلت مشكلة مؤقتة في استجابة النموذج."

                model_content = response.candidates[0].content
                calls = [
                    part.function_call
                    for part in (model_content.parts or [])
                    if getattr(part, "function_call", None)
                ]
                self._history.append(model_content)

                if not calls:
                    return (response.text or "تمام، هراجع الموضوع وأتحرك لما يكون عندي خطوة مفيدة.")[:4000]

                await self._notify(
                    "Tool calls: " + ", ".join(getattr(c, "name", "?") for c in calls)
                )

                for call in calls:
                    try:
                        args = dict(call.args or {})
                        result = await self._execute_tool(call.name, args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}

                    fn_part = types.Part.from_function_response(
                        name=call.name,
                        response={"result": result},
                        id=call.id,
                    )
                    self._history.append(
                        types.Content(role="user", parts=[fn_part])
                    )

            return "تمام، هراجع الموضوع وأتحرك لما يكون عندي خطوة مفيدة."
