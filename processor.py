import io
import html
import logging
import sys
from typing import Any
from config import config
from ai_engine import evaluate_and_draft, JobAnalysisResult
import database
import approval_bot
from approval_bot import send_job_for_approval, get_platform_name
from scraper import scraper

# Force stdout/stderr to UTF-8 on Windows to safely print emojis (🔥, 🏢, etc.)
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

logger = logging.getLogger("atrees.processor")


async def process_new_job(job_data: dict[str, Any]) -> None:
    """
    Complete Job Processing Pipeline:
    1. Deduplication check via SQLite Database.
    2. Scraping full job details (title, full description, budget, skills) from platform.
    3. AI evaluation & Arabic proposal drafting via Gemini.
    4. Filtering out irrelevant jobs.
    5. Saving to jobs.db in 'pending' status.
    6. Sending interactive Approval Telegram Bot Alert with 'قدّم' / 'تخطي' buttons.
    """
    text = job_data.get("text", "").strip()
    urls = job_data.get("urls", [])
    target_urls = job_data.get("target_urls", [])
    timestamp = job_data.get("timestamp")
    chat_id = job_data.get("chat_id")
    chat_title = job_data.get("chat_title", str(chat_id))
    msg_id = job_data.get("message_id")

    # Primary link of interest (Mostaql / Khamsat / Nafezly, or generic URL)
    primary_url = target_urls[0] if target_urls else (urls[0] if urls else "")

    # 1. Deduplication check via database (bypass for manual test submissions)
    is_manual = chat_title == "إرسال يدوي مباشر" or str(chat_id) in ("manual_test", "test_channel")
    if not is_manual and primary_url and database.is_job_url_seen(primary_url):
        logger.debug("Job URL %s already exists in database. Skipping duplicate.", primary_url)
        return

    logger.info("Processing incoming job from '%s' (Msg: %s)...", chat_title, msg_id)

    # 2. Enrich job details by scraping platform page if direct project URL exists
    evaluation_text = text
    if primary_url:
        scraped = await scraper.fetch_full_details(url=primary_url, fallback_text=text)
        evaluation_text = scraped.to_combined_text(original_text=text)

    # 3. Call Gemini evaluation with enriched text
    result: JobAnalysisResult | None = await evaluate_and_draft(
        job_text=evaluation_text,
        job_url=primary_url,
    )

    if not result:
        logger.warning(
            "Could not evaluate job %s (Gemini returned empty or is not configured).", msg_id
        )
        return

    # 4. Filter out irrelevant jobs
    if not result.is_relevant:
        logger.info(
            "❌ [SKIPPED / NOT RELEVANT] MsgID: %s | Reason: %s",
            msg_id,
            result.reason,
        )
        # If manually submitted for testing (or sent directly to bot), inform user of rejection reason
        target_chat = chat_id if (is_manual and chat_id and str(chat_id).isdigit()) else getattr(config, "my_chat_id", None)
        if is_manual and approval_bot.bot and target_chat:
            try:
                rejection_msg = (
                    f"⚠️ <b>المشروع غير مطابق لمعايير القبول (تم استبعاده):</b>\n\n"
                    f"💡 <b>سبب الرفض والفلترة:</b>\n{html.escape(result.reason)}"
                )
                await approval_bot.bot.send_message(
                    chat_id=target_chat,
                    text=rejection_msg,
                )
            except Exception as notify_err:
                logger.warning("Could not send rejection message to user: %s", notify_err)
        return

    # Detect platform name
    platform = get_platform_name(primary_url)

    # 5. Save job to SQLite Database in 'pending' status
    job_id = database.insert_job(
        platform=platform,
        url=primary_url,
        channel_title=chat_title,
        channel_id=str(chat_id),
        message_id=msg_id,
        job_text=evaluation_text,
        summary=result.reason,
        estimated_budget=result.estimated_budget,
        proposal=result.proposal_arabic,
        status="pending",
    )

    # 6. Print to Terminal
    separator = "=" * 65
    print(f"\n{separator}")
    try:
        print(f"🔥 [JOB MATCH DETECTED & SAVED: #{job_id}] 🔥")
        print(f"🏢 Platform: {platform}")
        print(f"📍 Source: {chat_title} (ID: {chat_id}) | MsgID: {msg_id}")
        print(f"🕒 Time: {timestamp}")
        if primary_url:
            print(f"🔗 Project Link: {primary_url}")
        print(f"💡 Fit Reason: {result.reason}")
        print(f"💰 Suggested Budget/Timeline: {result.estimated_budget}")
        print(f"{'-' * 65}")
        print("✍️ Tailored Proposal (Arabic):")
        print(result.proposal_arabic)
        print(f"{separator}\n")
    except Exception as print_exc:
        logger.warning("Console print warning (non-critical): %s", print_exc)

    # 7. Send Approval Alert to Telegram with Inline Keyboard ('قدّم' / 'تخطي')
    bot_msg_id = await send_job_for_approval(job_id)
    if bot_msg_id:
        logger.info(
            "🚀 Job #%s sent to Telegram for approval (Bot MsgID: %s)",
            job_id,
            bot_msg_id,
        )
    else:
        logger.info(
            "Job #%s stored in database. Approval alert pending Telegram bot configuration.",
            job_id,
        )
