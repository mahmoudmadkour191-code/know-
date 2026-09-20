from __future__ import annotations

import asyncio
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


class LinkStates(StatesGroup):
    phone = State()
    code = State()
    twofa = State()


class ControlBot:
    def __init__(self, token: str, owner_id: int, db, telegram, agent):
        self.bot = Bot(token)
        self.dp = Dispatcher()
        self.owner_id = owner_id
        self.db = db
        self.telegram = telegram
        self.agent = agent
        self.dashboard_message_id: int | None = None
        self._last_dashboard = ""
        self._dashboard_task: asyncio.Task | None = None
        self._register()
        agent.control_notifier = self._set_activity

    def _register(self) -> None:
        self.dp.message.register(self.start_cmd, Command("start"))
        self.dp.callback_query.register(self.cb, F.data.startswith("a:"))
        self.dp.message.register(self.collect_phone, LinkStates.phone)
        self.dp.message.register(self.collect_code, LinkStates.code)
        self.dp.message.register(self.collect_2fa, LinkStates.twofa)

    def _authorized(self, user_id: int | None) -> bool:
        return user_id == self.owner_id

    async def start_cmd(self, message: Message, state: FSMContext) -> None:
        if not self._authorized(message.from_user.id if message.from_user else None):
            return
        await state.clear()
        await self.show_dashboard(message.chat.id)

    async def show_dashboard(self, chat_id: int) -> None:
        await self._render(chat_id=chat_id, force=True)

    def _keyboard(self) -> InlineKeyboardMarkup:
        linked = bool(self.db.get("telegram_session"))
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ تشغيل" if not self.agent.running else "⏹ إيقاف", callback_data="a:toggle"),
                InlineKeyboardButton(text="🔗 ربط الحساب", callback_data="a:link"),
            ],
            [
                InlineKeyboardButton(text="📊 الحالة", callback_data="a:status"),
                InlineKeyboardButton(text="📜 السجل", callback_data="a:logs"),
            ],
            [InlineKeyboardButton(text="🔌 فصل الجلسة" if linked else "ℹ️ مساعدة", callback_data="a:unlink")],
        ])

    async def _set_activity(self, _text: str) -> None:
        if self.dashboard_message_id:
            await self._render(force=False)

    def _dashboard_text(self) -> str:
        s = self.db.snapshot()
        linked = bool(self.db.get("telegram_session"))
        uptime = int(time.time() - self.agent.started_at) if self.agent.running else 0
        h, rem = divmod(uptime, 3600)
        m, sec = divmod(rem, 60)
        return (
            "🤖 MAD SURVIVAL AGENT\n\n"
            f"الحساب: {'✅ مربوط' if linked else '❌ غير مربوط'}\n"
            f"الحالة: {self.agent.status}\n"
            f"وقت التشغيل: {h:02d}:{m:02d}:{sec:02d}\n"
            f"💰 الرصيد: $${s['cash']:.2f}\n"
            f"🎯 فرص: {int(s['jobs_found'])} | تواصل: {int(s['jobs_contacted'])}\n"
            f"✅ مكتمل: {int(s['jobs_completed'])} | ❌ فشل: {int(s['jobs_failed'])}\n"
            f"📨 رسائل: {int(s['messages_sent'])}\n\n"
            f"آخر نشاط: {self.agent.last_action[:220]}"
        )

    async def _render(self, chat_id: int | None = None, force: bool = False) -> None:
        text = self._dashboard_text()
        if not force and text == self._last_dashboard:
            return
        self._last_dashboard = text
        try:
            if self.dashboard_message_id:
                await self.bot.edit_message_text(
                    chat_id=self.owner_id,
                    message_id=self.dashboard_message_id,
                    text=text,
                    reply_markup=self._keyboard(),
                    disable_web_page_preview=True,
                )
            else:
                msg = await self.bot.send_message(
                    chat_id or self.owner_id,
                    text,
                    reply_markup=self._keyboard(),
                    disable_web_page_preview=True,
                )
                self.dashboard_message_id = msg.message_id
        except Exception:
            pass

    async def _live_loop(self) -> None:
        while True:
            try:
                if self.dashboard_message_id:
                    await self._render(force=False)
            except Exception:
                pass
            await asyncio.sleep(3)

    async def cb(self, query: CallbackQuery, state: FSMContext) -> None:
        if not self._authorized(query.from_user.id):
            await query.answer()
            return
        await query.answer()
        data = query.data.split(":", 1)[1]
        if data == "toggle":
            try:
                if self.agent.running:
                    await self.agent.stop()
                else:
                    await self.agent.start()
                await self._render(force=True)
            except Exception as exc:
                await query.message.answer(f"❌ {exc}")
        elif data == "link":
            await state.set_state(LinkStates.phone)
            await query.message.answer("📱 ابعت رقم Telegram بصيغة دولية.")
        elif data == "status":
            await query.message.answer(self._dashboard_text())
        elif data == "logs":
            rows = self.db.recent_events(15)
            body = "\n".join(f"• {r['level']}: {r['message'][:180]}" for r in reversed(rows)) or "لا يوجد سجل بعد."
            await query.message.answer("📜 آخر الأحداث\n\n" + body)
        elif data == "unlink":
            if self.agent.running:
                await self.agent.stop()
            await self.telegram.disconnect()
            self.db.delete("telegram_session")
            await query.message.answer("🔌 تم فصل جلسة Telegram ومسحها.")
            await self._render(force=True)

    async def collect_phone(self, message: Message, state: FSMContext) -> None:
        if not self._authorized(message.from_user.id if message.from_user else None):
            return
        try:
            phone = (message.text or "").strip()
            await message.delete()
            await self.telegram.start_login(phone)
            await state.set_state(LinkStates.code)
            msg = await self.bot.send_message(self.owner_id, "🔐 تم إرسال كود Telegram. ابعته هنا، وهيتم حذف الرسالة.")
            await asyncio.sleep(1)
            await msg.delete()
        except Exception as exc:
            await state.clear()
            await self.telegram.cancel_login()
            await self.bot.send_message(self.owner_id, f"❌ فشل بدء الربط: {exc}")

    async def collect_code(self, message: Message, state: FSMContext) -> None:
        if not self._authorized(message.from_user.id if message.from_user else None):
            return
        code = (message.text or "").strip().replace(" ", "")
        try:
            await message.delete()
            done = await self.telegram.complete_code(code)
            if done:
                await state.clear()
                await self.bot.send_message(self.owner_id, "✅ تم ربط جلسة Telegram بنجاح.")
                await self._render(force=True)
            else:
                await state.set_state(LinkStates.twofa)
                await self.bot.send_message(self.owner_id, "🔐 الحساب عليه تحقق بخطوتين. ابعت كلمة مرور 2FA، وهيتم حذف الرسالة.")
        except Exception as exc:
            await state.clear()
            await self.telegram.cancel_login()
            await self.bot.send_message(self.owner_id, f"❌ فشل الكود: {exc}")

    async def collect_2fa(self, message: Message, state: FSMContext) -> None:
        if not self._authorized(message.from_user.id if message.from_user else None):
            return
        password = message.text or ""
        try:
            await message.delete()
            await self.telegram.complete_2fa(password)
            await state.clear()
            await self.bot.send_message(self.owner_id, "✅ تم ربط الحساب بنجاح.")
            await self._render(force=True)
        except Exception as exc:
            await state.clear()
            await self.telegram.cancel_login()
            await self.bot.send_message(self.owner_id, f"❌ فشل 2FA: {exc}")

    async def run(self) -> None:
        await self.telegram.restore()
        if self.telegram.client:
            self.db.log("Telegram session is connected")
        self._dashboard_task = asyncio.create_task(self._live_loop())
        await self._render(force=True)
        await self.dp.start_polling(self.bot)
