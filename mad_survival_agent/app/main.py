from __future__ import annotations

import asyncio

from .agent import SurvivalAgent
from .config import Settings
from .control_bot import ControlBot
from .crypto import SecretBox
from .db import Database
from .gemini_agent import GeminiAgent
from .telegram_user import TelegramUser


async def main() -> None:
    settings = Settings.from_env()
    db = Database(f"{settings.data_dir}/agent.sqlite3")
    secret_box = SecretBox(settings.session_encryption_key)

    async def on_incoming(event):
        await agent._incoming(event)

    async def on_flood_wait(seconds: int):
        db.log(f"Telegram FloodWait: backing off for {seconds}s", "WARN")

    telegram = TelegramUser(
        settings.telegram_api_id,
        settings.telegram_api_hash,
        db,
        secret_box,
        on_incoming=on_incoming,
        on_flood_wait=on_flood_wait,
    )
    gemini = GeminiAgent(
        settings.gemini_api_key,
        settings.gemini_model,
        telegram,
        db,
        settings.max_agent_steps,
        data_dir=settings.data_dir,
    )
    agent = SurvivalAgent(
        telegram,
        gemini,
        db,
        interval=settings.autonomous_interval_seconds,
        group_mentions=settings.respond_to_group_mentions,
        allow_outbound=settings.allow_autonomous_outbound,
    )
    control = ControlBot(settings.control_bot_token, settings.owner_id, db, telegram, agent)

    try:
        await control.run()
    finally:
        await agent.stop()
        await telegram.disconnect()
        await gemini.browser.close()


if __name__ == "__main__":
    asyncio.run(main())
