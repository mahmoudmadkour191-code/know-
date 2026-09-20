from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from .browser import BrowserAgent
from .db import Database
from .email_agent import EmailAgent
from .prompt import SYSTEM_PROMPT
from .telegram_user import TelegramUser


class QuotaSleep(Exception):
    pass


class GeminiAgent:
    def __init__(
        self,
        api_key: str,
        model: str,
        telegram: TelegramUser,
        db: Database,
        max_steps: int = 5,
        data_dir: str = "data",
    ):
        self.client = genai.Client(api_key=api_key, vertexai=False)
        self.model = model
        self.telegram = telegram
        self.db = db
        self.max_steps = max_steps
        self._lock = asyncio.Lock()
        self.on_activity: Callable[[str], Awaitable[None]] | None = None
        self._history: list[types.Content] = []
        self.browser = BrowserAgent(data_dir, on_event=self._notify)
        self.email = EmailAgent()
        self.daily_token_budget = max(
            int(os.getenv("GEMINI_DAILY_TOKEN_BUDGET", "50000")),
            1000,
        )
        self.quota_sleep_seconds = max(
            int(os.getenv("GEMINI_QUOTA_SLEEP_SECONDS", "21600")),
            300,
        )

    def _tool_specs(self) -> list[types.Tool]:
        declarations = [
            {
                "name": "telegram_global_search",
                "description": "Search visible Telegram messages for legitimate public opportunities or context.",
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
                "name": "telegram_discover_groups",
                "description": "Discover Telegram groups related to a specific topic or task. Do not use for mass/random group hunting.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "telegram_join_group",
                "description": "Join one relevant Telegram public group or invite link when it is directly useful to the current task. Never mass-join groups.",
                "parameters": {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                },
            },
            {
                "name": "telegram_leave_group",
                "description": "Leave a Telegram group when it is no longer useful or the user requests it.",
                "parameters": {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                },
            },
            {
                "name": "telegram_recent_messages",
                "description": "Read recent messages in a known Telegram chat before responding.",
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
                "name": "browser_open",
                "description": "Open a normal public HTTPS/HTTP webpage in the persistent browser.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
            {
                "name": "browser_snapshot",
                "description": "Read the current browser page, including visible text and links.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_click",
                "description": "Click a visible button, link, text target, or CSS selector on the current browser page.",
                "parameters": {
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                },
            },
            {
                "name": "browser_type",
                "description": "Fill a normal webpage input identified by CSS selector, label, or placeholder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["target", "text"],
                },
            },
            {
                "name": "browser_press",
                "description": "Press a normal keyboard key in the current webpage.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            },
            {
                "name": "browser_wait",
                "description": "Wait briefly for the current page to update.",
                "parameters": {
                    "type": "object",
                    "properties": {"seconds": {"type": "number", "minimum": 0.2, "maximum": 30}},
                    "required": ["seconds"],
                },
            },
            {
                "name": "browser_back",
                "description": "Go back one page in the persistent browser.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_current",
                "description": "Get the current browser URL and title.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "email_latest_messages",
                "description": "Read recent messages from the owner-controlled IMAP mailbox configured for the experiment.",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 15}},
                },
            },
            {
                "name": "email_find_verification_code",
                "description": "Find a likely verification code in the owner-controlled IMAP mailbox. Only use a mailbox explicitly configured by the owner.",
                "parameters": {
                    "type": "object",
                    "properties": {"hint": {"type": "string"}},
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

    def _sleep_until(self) -> float:
        try:
            return float(self.db.get("gemini_sleep_until", "0") or "0")
        except ValueError:
            return 0.0

    def is_sleeping(self) -> bool:
        return time.time() < self._sleep_until()

    def sleep_remaining(self) -> int:
        return max(0, int(self._sleep_until() - time.time()))

    def _set_sleep(self, seconds: int, reason: str) -> None:
        until = time.time() + max(seconds, 300)
        self.db.set("gemini_sleep_until", str(until))
        self.db.log(f"Gemini sleep mode for {max(seconds, 300)}s: {reason}", "WARN")

    def _sleep_until_next_pacific_midnight(self) -> int:
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=5,
            microsecond=0,
        )
        return max(300, int((tomorrow - now).total_seconds()))

    def _ensure_token_day(self) -> None:
        today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
        if self.db.get("gemini_token_day") != today:
            self.db.set("gemini_token_day", today)
            self.db.set("gemini_tokens_today_reset", "0")

    def _usage_tokens(self, response) -> int:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return 0
        for name in ("total_token_count", "totalTokenCount"):
            value = getattr(usage, name, None)
            if value:
                return int(value)
        return 0

    async def _call_model(self, contents: list[types.Content]):
        if self.is_sleeping():
            raise QuotaSleep("Gemini is in sleep mode to preserve quota.")

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=self._tool_specs(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "429" in message or "resource_exhausted" in lowered or "quota_exceeded" in lowered:
                if "quota_exceeded" in lowered or "daily" in lowered or "quota" in lowered:
                    seconds = self._sleep_until_next_pacific_midnight()
                else:
                    seconds = self.quota_sleep_seconds
                self._set_sleep(seconds, "API quota/rate-limit response")
                raise QuotaSleep(message) from exc
            raise

        self._ensure_token_day()
        tokens = self._usage_tokens(response)
        if tokens:
            self.db.incr("gemini_tokens_total", tokens)
            self.db.incr("gemini_tokens_today", tokens)
        self.db.incr("gemini_requests")

        total_today = self.db.stat("gemini_tokens_today")
        if total_today >= self.daily_token_budget:
            self._set_sleep(self._sleep_until_next_pacific_midnight(), "application token safety budget reached")

        return response

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "telegram_global_search":
            result = await self.telegram.search_global(args["query"], args.get("limit", 10))
            self.db.incr("jobs_found", len(result))
            return {"results": result}
        if name == "telegram_discover_groups":
            return {"groups": await self.telegram.discover_groups(args["query"], args.get("limit", 10))}
        if name == "telegram_join_group":
            return await self.telegram.join_chat(args["target"])
        if name == "telegram_leave_group":
            return await self.telegram.leave_chat(args["target"])
        if name == "telegram_recent_messages":
            return {"messages": await self.telegram.recent(args["chat_id"], args.get("limit", 15))}
        if name == "send_telegram_message":
            sent = await self.telegram.send(args["chat_id"], args["text"], args.get("reply_to"))
            self.db.incr("messages_sent")
            self.db.incr("jobs_contacted")
            return {"ok": True, "message_id": getattr(sent, "id", None)}
        if name == "browser_open":
            url = str(args["url"]).strip()
            if not url.startswith(("https://", "http://")):
                return {"ok": False, "error": "Only HTTP(S) URLs are allowed."}
            return await self.browser.open(url)
        if name == "browser_snapshot":
            return await self.browser.snapshot()
        if name == "browser_click":
            return await self.browser.click(args["target"])
        if name == "browser_type":
            return await self.browser.type_text(args["target"], args["text"])
        if name == "browser_press":
            return await self.browser.press(args["key"])
        if name == "browser_wait":
            return await self.browser.wait(args["seconds"])
        if name == "browser_back":
            return await self.browser.back()
        if name == "browser_current":
            return await self.browser.current()
        if name == "email_latest_messages":
            return {"messages": self.email.latest_messages(args.get("limit", 10))}
        if name == "email_find_verification_code":
            return self.email.find_verification_code(args.get("hint", ""))
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

    def _function_response_part(self, call: types.FunctionCall, result: dict[str, Any]) -> types.Part:
        response = types.FunctionResponse(
            name=call.name,
            response={"result": result},
            id=getattr(call, "id", None),
        )
        return types.Part(function_response=response)

    async def run(self, user_input: str, context: dict[str, Any] | None = None) -> str:
        async with self._lock:
            if self.is_sleeping():
                raise QuotaSleep("Gemini sleep mode is active.")

            text = user_input
            if context:
                text += "\n\nCURRENT CONTEXT:\n" + json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                )
            if len(self._history) > 12:
                self._history = self._history[-12:]
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
                    return (
                        response.text
                        or "تمام، هراجع الموضوع وأتحرك لما يكون عندي خطوة مفيدة."
                    )[:4000]

                await self._notify(
                    "Tool calls: " + ", ".join(getattr(c, "name", "?") for c in calls)
                )

                for call in calls:
                    try:
                        args = dict(call.args or {})
                        result = await self._execute_tool(call.name, args)
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}

                    payload = json.dumps(result, ensure_ascii=False, default=str)
                    if len(payload) > 9000:
                        payload = payload[:9000] + "...[truncated]"
                        result = {"truncated_tool_result": payload}

                    self._history.append(
                        types.Content(
                            role="user",
                            parts=[self._function_response_part(call, result)],
                        )
                    )

            return "تمام، هكمل الخطوة التالية لما يكون عندي فرصة مناسبة."
