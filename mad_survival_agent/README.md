# MAD Survival Agent v1

Lightweight Telegram-control + Telegram-user-account autonomous agent using Gemini 3.8 Flash.

## Run

Python 3.11+:
python -m pip install -r requirements.txt
python run.py

## Features

- Owner-only Telegram control bot.
- Telegram user login: phone -> code -> optional 2FA.
- Login messages are deleted after receipt.
- Encrypted Telethon StringSession in SQLite.
- Natural private-chat replies while running.
- Group replies on mentions/replies by default.
- Autonomous opportunity-discovery loop.
- Gemini Google Search + URL Context.
- Telegram search, recent messages, targeted messaging, cash ledger.
- SQLite logs and stats.

Do not commit .env or Telegram session data.
