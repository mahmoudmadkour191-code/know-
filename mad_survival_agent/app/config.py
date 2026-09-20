from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    control_bot_token: str
    owner_id: int
    telegram_api_id: int
    telegram_api_hash: str
    gemini_api_key: str
    session_encryption_key: str
    gemini_model: str = DEFAULT_GEMINI_MODEL
    max_agent_steps: int = 5
    autonomous_interval_seconds: int = 600
    message_debounce_seconds: int = 3
    respond_to_group_mentions: bool = True
    allow_autonomous_outbound: bool = True
    browser_enabled: bool = True
    data_dir: str = "data"

    @classmethod
    def from_env(cls) -> "Settings":
        required = [
            "CONTROL_BOT_TOKEN",
            "OWNER_ID",
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "GEMINI_API_KEY",
            "SESSION_ENCRYPTION_KEY",
        ]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError("Missing environment variables: " + ", ".join(missing))

        return cls(
            control_bot_token=os.environ["CONTROL_BOT_TOKEN"],
            owner_id=int(os.environ["OWNER_ID"]),
            telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
            telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
            gemini_api_key=os.environ["GEMINI_API_KEY"],
            session_encryption_key=os.environ["SESSION_ENCRYPTION_KEY"],
            gemini_model=DEFAULT_GEMINI_MODEL,
            max_agent_steps=max(1, _int("MAX_AGENT_STEPS", 5)),
            autonomous_interval_seconds=max(_int("AUTONOMOUS_INTERVAL_SECONDS", 600), 600),
            message_debounce_seconds=_int("MESSAGE_DEBOUNCE_SECONDS", 3),
            respond_to_group_mentions=_bool("RESPOND_TO_GROUP_MENTIONS", True),
            allow_autonomous_outbound=_bool("ALLOW_AUTONOMOUS_OUTBOUND", True),
            browser_enabled=_bool("BROWSER_ENABLED", True),
            data_dir=os.getenv("DATA_DIR", "data").strip() or "data",
        )
