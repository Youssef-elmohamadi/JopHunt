import os
import logging
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Base Directory & Env loading
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("atrees.config")


def _parse_target_channels(channels_str: str) -> list[str | int]:
    """
    Parses comma-separated channel identifiers.
    Converts numeric string IDs to integers (required by Telethon for raw channel/group IDs).
    Keeps usernames (e.g. '@channel' or 'channel') as strings.
    """
    if not channels_str:
        return []

    channels: list[str | int] = []
    for raw in channels_str.split(","):
        cleaned = raw.strip()
        if not cleaned:
            continue

        # Check if integer ID (positive or negative channel ID like -100...)
        if (cleaned.startswith("-") and cleaned[1:].isdigit()) or cleaned.isdigit():
            channels.append(int(cleaned))
        else:
            channels.append(cleaned)
    return channels


def _str_to_bool(val: str, default: bool = False) -> bool:
    if not val:
        return default
    return val.strip().lower() in ("true", "1", "yes", "y", "on")


@dataclass(frozen=True)
class Config:
    # Telegram Userbot credentials
    tg_api_id: int
    tg_api_hash: str
    tg_session_name: str
    target_channels: list[str | int]

    # AI & Alerts
    gemini_api_key: str
    groq_api_key: str
    ollama_host: str
    gemini_model: str
    groq_model: str
    ollama_model: str
    bot_token: str
    my_chat_id: int | str

    # Submitter & Automation settings
    browser_headless: bool
    auto_submit_confirm: bool

    @classmethod
    def load(cls) -> "Config":
        raw_api_id = os.getenv("TG_API_ID", "").strip()
        tg_api_hash = os.getenv("TG_API_HASH", "").strip()
        tg_session_name = os.getenv("TG_SESSION_NAME", "atrees_userbot").strip()
        raw_channels = os.getenv("TARGET_CHANNELS", "").strip()

        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
        gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3").strip()
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        raw_chat_id = os.getenv("MY_CHAT_ID", "").strip()

        browser_headless = _str_to_bool(os.getenv("BROWSER_HEADLESS", "false"), default=False)
        auto_submit_confirm = _str_to_bool(os.getenv("AUTO_SUBMIT_CONFIRM", "true"), default=True)

        # Validate essential userbot credentials
        if not raw_api_id or not tg_api_hash:
            logger.warning(
                "TG_API_ID or TG_API_HASH is missing. Please ensure your .env file is properly configured."
            )

        try:
            tg_api_id = int(raw_api_id) if raw_api_id else 0
        except ValueError:
            raise ValueError(f"TG_API_ID must be a valid integer, got: {raw_api_id!r}")

        parsed_channels = _parse_target_channels(raw_channels)

        # Parse chat ID
        my_chat_id: int | str
        if (raw_chat_id.startswith("-") and raw_chat_id[1:].isdigit()) or raw_chat_id.isdigit():
            my_chat_id = int(raw_chat_id)
        else:
            my_chat_id = raw_chat_id

        return cls(
            tg_api_id=tg_api_id,
            tg_api_hash=tg_api_hash,
            tg_session_name=tg_session_name,
            target_channels=parsed_channels,
            gemini_api_key=gemini_api_key,
            groq_api_key=groq_api_key,
            ollama_host=ollama_host,
            gemini_model=gemini_model,
            groq_model=groq_model,
            ollama_model=ollama_model,
            bot_token=bot_token,
            my_chat_id=my_chat_id,
            browser_headless=browser_headless,
            auto_submit_confirm=auto_submit_confirm,
        )


config = Config.load()
