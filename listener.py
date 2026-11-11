import asyncio
import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from telethon import TelegramClient, events

# Force Windows stdout/stderr to utf-8
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        elif sys.stdout is not None:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        elif sys.stderr is not None:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import config
from extractor import extract_urls_from_message, filter_target_platform_urls
from processor import process_new_job
import approval_bot

# Configure Structured Logging (Console + Rotating Log File)
LOGS_DIR = Path(__file__).resolve().parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

file_handler = RotatingFileHandler(
    LOGS_DIR / "atrees.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
console_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[file_handler, console_handler],
)
logger = logging.getLogger("atrees.listener")


def ensure_single_instance() -> None:
    """Ensures only one instance of listener.py runs at a time to prevent TelegramConflictError."""
    try:
        import psutil
        current = psutil.Process()
        ignore_pids = {current.pid}
        try:
            ignore_pids.update(p.pid for p in current.parents())
        except Exception:
            pass

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = p.info["pid"]
                if pid in ignore_pids:
                    continue
                cmdline = " ".join(p.info["cmdline"] or [])
                if "listener.py" in cmdline:
                    logger.warning("Terminating existing listener instance (PID %s) to prevent conflict...", pid)
                    p.kill()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Single instance check skipped: %s", exc)


def create_telegram_client() -> TelegramClient:
    """Initializes and returns the Telethon client instance."""
    if not config.tg_api_id or not config.tg_api_hash:
        logger.error(
            "Missing Telegram credentials! Please set TG_API_ID and TG_API_HASH in .env"
        )
        sys.exit(1)

    return TelegramClient(
        session=config.tg_session_name,
        api_id=config.tg_api_id,
        api_hash=config.tg_api_hash,
    )


async def main() -> None:
    ensure_single_instance()
    logger.info("Starting Atrees System (Telethon Listener + Approval Bot)...")
    logger.info("Target channels configured: %s", config.target_channels or "ALL CHANNELS")

    client = create_telegram_client()

    # Determine chats filter
    chats_filter = config.target_channels if config.target_channels else None

    @client.on(events.NewMessage(chats=chats_filter))
    async def new_message_handler(event: events.NewMessage.Event) -> None:
        try:
            message = event.message
            raw_text = message.raw_text or ""

            # Ignore completely empty messages (e.g. service messages without media/text)
            if not raw_text and not message.media:
                return

            # Extract URLs
            all_urls = extract_urls_from_message(message)
            target_urls = filter_target_platform_urls(all_urls)

            # Metadata extraction
            chat = await event.get_chat()
            chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(event.chat_id)

            job_data = {
                "message_id": message.id,
                "chat_id": event.chat_id,
                "chat_title": chat_title,
                "timestamp": message.date.isoformat() if message.date else None,
                "text": raw_text,
                "urls": all_urls,
                "target_urls": target_urls,
            }

            # Forward to complete processing pipeline
            await process_new_job(job_data)

        except Exception as exc:
            logger.exception("Error handling incoming message (ID %s): %s", getattr(event.message, "id", "unknown"), exc)

    # Start the userbot client
    await client.start()
    me = await client.get_me()
    logger.info("Telethon Userbot logged in as: %s (@%s)", me.first_name, me.username or "no_username")

    # Prepare concurrent tasks: Telethon userbot listener + Aiogram approval bot polling
    tasks = [client.run_until_disconnected()]

    async def run_bot_polling_with_reconnect():
        """Keeps the approval bot polling alive and auto-reconnects on temporary network drops."""
        while True:
            try:
                await approval_bot.dp.start_polling(approval_bot.bot, handle_signals=False)
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.warning(
                    "Approval bot network interruption (%s). Reconnecting in 5 seconds...", err
                )
                await asyncio.sleep(5)

    if approval_bot.bot:
        logger.info("Approval Bot initialized. Starting bot polling alongside userbot...")
        tasks.append(run_bot_polling_with_reconnect())
    else:
        logger.warning(
            "Approval Bot disabled (BOT_TOKEN missing in .env). Only Userbot listener is running."
        )

    logger.info("Atrees is fully active and listening. Press Ctrl+C to stop.")

    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down Atrees services...")
    finally:
        if approval_bot.bot:
            await approval_bot.bot.session.close()
        await client.disconnect()
        logger.info("All services disconnected cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
