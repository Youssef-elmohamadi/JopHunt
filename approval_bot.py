import asyncio
import html
import logging
from typing import Optional
from pathlib import Path
import socket
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    FSInputFile,
)
from aiogram.client.session.aiohttp import AiohttpSession
from config import config
import database
from submitter import submit_proposal, SubmissionResult

logger = logging.getLogger("atrees.approval_bot")


class IPv4AiohttpSession(AiohttpSession):
    """Configures robust connection parameters for Windows to prevent WinError 121 timeouts."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._connector_init["family"] = socket.AF_INET
        self._connector_init["happy_eyeballs_delay"] = 0.2


# Initialize Bot and Dispatcher
bot: Optional[Bot] = None
dp = Dispatcher()

if config.bot_token and not config.bot_token.startswith("your_"):
    try:
        session = IPv4AiohttpSession(timeout=60.0)
        bot = Bot(
            token=config.bot_token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    except Exception as exc:
        logger.warning("Invalid BOT_TOKEN format (%s). Approval bot disabled until a valid token is set.", exc)
        bot = None
else:
    logger.warning("BOT_TOKEN is not configured or still a placeholder. Approval bot will not send messages.")


def get_platform_name(url: str) -> str:
    """Detects friendly platform name from URL."""
    lowered = (url or "").lower()
    if "mostaql.com" in lowered:
        return "مستقل (Mostaql)"
    elif "khamsat.com" in lowered:
        return "خمسات (Khamsat)"
    elif "nafezly.com" in lowered:
        return "نفذلي (Nafezly)"
    return "تيليجرام / منصة أخرى"


def build_approval_keyboard(job_id: int, job_url: str = "") -> InlineKeyboardMarkup:
    """Builds the inline keyboard with 'قدّم', 'تخطي', and optional direct job link."""
    buttons = []
    
    # Action buttons: Submit or Skip
    action_row = [
        InlineKeyboardButton(text="✅ قدّم", callback_data=f"submit_{job_id}"),
        InlineKeyboardButton(text="❌ تخطي", callback_data=f"skip_{job_id}"),
    ]
    buttons.append(action_row)

    # Optional Link button
    if job_url:
        buttons.append([InlineKeyboardButton(text="🌐 عرض تفاصيل المشروع", url=job_url)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_job_message(job: dict) -> str:
    """Formats the HTML alert message for a job."""
    safe_platform = html.escape(job.get("platform") or "منصة عمل حر")
    safe_url = html.escape(job.get("url") or "")
    safe_summary = html.escape(job.get("summary") or "مشروع مطابق لمهاراتك")
    safe_budget = html.escape(job.get("estimated_budget") or "حسب الاتفاق")
    safe_proposal = html.escape(job.get("proposal") or "")
    status = job.get("status", "pending")

    # Calculate exact duration and budget that will be submitted
    from submitter import extract_numeric_duration_and_budget
    duration_days, budget_amount = extract_numeric_duration_and_budget(
        job.get("estimated_budget", ""),
        job.get("estimated_budget", ""),
        job.get("job_text", ""),
    )

    status_tag = ""
    if status == "approved":
        status_tag = "<b>[الحالة: تم القبول وجاري الإرسال ⏳]</b>\n"
    elif status == "submitting":
        status_tag = "<b>[الحالة: جاري فتح المنصة وتعبئة العرض 🤖]</b>\n"
    elif status == "submitted":
        status_tag = f"<b>[الحالة: تم التقديم بنجاح بمبلغ ${budget_amount} ومدة {duration_days} أيام 🚀]</b>\n"
    elif status == "skipped":
        status_tag = "<b>[الحالة: تم التخطي ❌]</b>\n"
    elif status == "failed":
        status_tag = "<b>[الحالة: تعذر التقديم التلقائي ⚠️]</b>\n"

    lines = [
        "🔥 <b>مشروع عمل حر جديد مطابق لخبراتك!</b>",
        status_tag,
        f"🏢 <b>المنصة:</b> {safe_platform}",
    ]

    if safe_url:
        lines.append(f"🔗 <b>الرابط:</b> <a href=\"{safe_url}\">{safe_url}</a>")

    lines.extend([
        f"💡 <b>الملخص:</b> {safe_summary}",
        f"💰 <b>ميزانية المشروع:</b> {safe_budget}",
        f"🎯 <b>بيانات التقديم التلقائي:</b> السعر: <b>${budget_amount}</b> | المدة: <b>{duration_days} أيام</b>",
        "",
        "✍️ <b>العرض المقترح (انقر لنسخه):</b>",
        f"<code>{safe_proposal}</code>",
        "",
    ])

    if status in ("failed", "skipped"):
        lines.append("<i>💡 يمكنك الضغط على 'قدّم' أدناه لإعادة محاولة التقديم التلقائي.</i>")
    elif status == "pending":
        lines.append("<i>💡 يمكنك الرد على هذه الرسالة بنص معدل لتعديل العرض قبل الضغط على 'قدّم'.</i>")

    return "\n".join(lines)


async def send_job_for_approval(job_id: int) -> Optional[int]:
    """
    Sends a formatted approval request message to MY_CHAT_ID and links bot_message_id.
    """
    if not bot or not config.my_chat_id:
        logger.warning("Bot is not configured (missing BOT_TOKEN or MY_CHAT_ID).")
        return None

    job = database.get_job_by_id(job_id)
    if not job:
        logger.error("Job ID %s not found in database.", job_id)
        return None

    text = format_job_message(job)
    keyboard = build_approval_keyboard(job_id, job.get("url") or "")

    for attempt in range(1, 4):
        try:
            sent_msg = await bot.send_message(
                chat_id=config.my_chat_id,
                text=text,
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
            database.link_bot_message_id(job_id, sent_msg.message_id)
            logger.info("Sent job #%s for approval. Telegram MsgID: %s", job_id, sent_msg.message_id)
            return sent_msg.message_id
        except Exception as exc:
            logger.warning(
                "Attempt %d/3 failed to send approval message for job #%s: %s",
                attempt,
                job_id,
                exc,
            )
            if attempt < 3:
                await asyncio.sleep(2)
            else:
                logger.error("Failed to send approval message for job #%s after 3 attempts: %s", job_id, exc)
                return None


# -----------------------------------------------------------------------------
# Handlers: Callbacks & Replies
# -----------------------------------------------------------------------------

@dp.callback_query(F.data.startswith("submit_"))
async def handle_submit_callback(callback: CallbackQuery):
    """
    Handles the '✅ قدّم' button click.
    Triggers the Auto-Submitter (Playwright) to fill and submit the proposal.
    """
    try:
        job_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("خطأ في معرف الوظيفة.", show_alert=True)
        return

    job = database.get_job_by_id(job_id)
    if not job:
        await callback.answer("لم يتم العثور على الوظيفة في قاعدة البيانات.", show_alert=True)
        return

    job_url = job.get("url", "")
    if not job_url:
        # Automatic fallback: extract URL from job_text if it was missed previously
        from extractor import extract_urls_from_message, filter_target_platform_urls
        raw_content = job.get("job_text", "") or ""
        candidates = filter_target_platform_urls(extract_urls_from_message(raw_content))
        if candidates:
            job_url = candidates[0]
            platform = get_platform_name(job_url)
            with database.get_connection() as conn:
                conn.cursor().execute(
                    "UPDATE jobs SET url = ?, platform = ? WHERE id = ?",
                    (job_url, platform, job_id),
                )
                conn.commit()
            job = database.get_job_by_id(job_id) or job
            logger.info("Auto-recovered missing URL '%s' for job #%s", job_url, job_id)
        else:
            await callback.answer("لا يوجد رابط معتمد للمشروع لتقديمه تلقائياً.", show_alert=True)
            return

    # 1. Update status to 'submitting'
    database.update_job_status(job_id, "submitting")
    updated_job = database.get_job_by_id(job_id) or job

    try:
        await callback.answer("⏳ جاري فتح المنصة وتعبئة العرض تلقائياً...", show_alert=False)
    except Exception as e:
        logger.warning("Could not answer callback query immediately (%s). Proceeding with submission.", e)

    # 2. Update message in chat
    if callback.message:
        try:
            await callback.message.edit_text(
                text=format_job_message(updated_job),
                reply_markup=None,
                disable_web_page_preview=False,
            )
        except Exception as e:
            logger.warning("Could not update message to submitting status: %s", e)

    # 3. Launch Auto-Submitter asynchronously
    async def run_submission():
        logger.info("Starting auto-submission for Job #%s (%s)...", job_id, job_url)
        result: SubmissionResult = await submit_proposal(
            job_url=job_url,
            proposal_text=job.get("proposal", ""),
            duration=job.get("estimated_budget", ""),
            budget=job.get("estimated_budget", ""),
            job_text=job.get("job_text", ""),
        )

        if result.success:
            database.update_job_status(job_id, "submitted")
            final_job = database.get_job_by_id(job_id) or job

            # Edit message to reflect submitted
            if callback.message:
                try:
                    fail_keyboard = build_approval_keyboard(job_id, job_url)
                    await callback.message.edit_text(
                        text=format_job_message(final_job),
                        reply_markup=fail_keyboard,
                        disable_web_page_preview=False,
                    )
                except Exception:
                    pass

            # Send screenshot to Telegram
            if bot and config.my_chat_id and result.screenshot_path and Path(result.screenshot_path).exists():
                photo_file = FSInputFile(result.screenshot_path)
                cost_info = f"\n💰 <b>الميزانية المعتمدة:</b> ${result.clamped_cost}" if getattr(result, "clamped_cost", None) else ""
                caption = (
                    f"🚀 <b>تم تقديم العرض بنجاح!</b>\n"
                    f"🏢 <b>المنصة:</b> {result.platform}\n"
                    f"🔢 <b>معرف الوظيفة:</b> #{job_id}"
                    f"{cost_info}\n"
                    f"🔗 <a href=\"{job_url}\">رابط المشروع</a>"
                )
                await bot.send_photo(
                    chat_id=config.my_chat_id,
                    photo=photo_file,
                    caption=caption,
                )
            logger.info("Submission for Job #%s COMPLETED successfully.", job_id)

        else:
            database.update_job_status(job_id, "failed")
            final_job = database.get_job_by_id(job_id) or job
            if callback.message:
                try:
                    fail_keyboard = build_approval_keyboard(job_id, job_url)
                    await callback.message.edit_text(
                        text=format_job_message(final_job),
                        reply_markup=fail_keyboard,
                        disable_web_page_preview=False,
                    )
                except Exception:
                    pass

            if bot and config.my_chat_id:
                err_text = (
                    f"⚠️ <b>تعذر التقديم التلقائي للمشروع #{job_id}</b>\n"
                    f"🏢 <b>المنصة:</b> {result.platform}\n"
                    f"❌ <b>الخطأ:</b> {html.escape(result.message)}\n\n"
                    f"💡 <i>نصيحة: تأكد من تشغيل <code>python setup_session.py</code> وتسجيل الدخول، أو قدّم يدوياً عبر:</i>\n"
                    f"👉 <a href=\"{job_url}\">{job_url}</a>"
                )
                # If error screenshot captured, send photo
                if result.screenshot_path and Path(result.screenshot_path).exists():
                    photo_file = FSInputFile(result.screenshot_path)
                    await bot.send_photo(
                        chat_id=config.my_chat_id,
                        photo=photo_file,
                        caption=err_text,
                    )
                else:
                    await bot.send_message(
                        chat_id=config.my_chat_id,
                        text=err_text,
                        disable_web_page_preview=False,
                    )

    # Schedule submission in background
    import asyncio
    asyncio.create_task(run_submission())


@dp.callback_query(F.data.startswith("skip_"))
async def handle_skip_callback(callback: CallbackQuery):
    """Handles the '❌ تخطي' button click."""
    try:
        job_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("خطأ في معرف الوظيفة.", show_alert=True)
        return

    job = database.get_job_by_id(job_id)
    if not job:
        await callback.answer("لم يتم العثور على الوظيفة في قاعدة البيانات.", show_alert=True)
        return

    # Update database status
    database.update_job_status(job_id, "skipped")
    updated_job = database.get_job_by_id(job_id) or job

    try:
        await callback.answer("تم تخطي المشروع ❌", show_alert=False)
    except Exception as e:
        logger.warning("Could not answer skip callback immediately (%s).", e)

    # Update the original message text to reflect skipped status
    try:
        new_text = format_job_message(updated_job)
        if callback.message:
            await callback.message.edit_text(
                text=new_text,
                reply_markup=None,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.warning("Could not edit message after skip: %s", e)

    logger.info("Job #%s SKIPPED by user.", job_id)


@dp.message(F.reply_to_message)
async def handle_proposal_tweak_reply(message: Message):
    """
    Handles user replying to an alert message with edited text or a direct project URL.
    Updates the proposal or URL/platform in the database and refreshes the message.
    """
    reply = message.reply_to_message
    if not reply:
        return

    # Look up the job linked to this bot message ID
    job = database.get_job_by_bot_message_id(reply.message_id)
    if not job:
        return

    reply_text = (message.text or message.caption or "").strip()
    if not reply_text:
        await message.reply("الرجاء إرسال نص العرض الجديد أو رابط المشروع المعتمد.")
        return

    job_id = job["id"]
    from extractor import extract_urls_from_message, filter_target_platform_urls
    extracted_urls = filter_target_platform_urls(extract_urls_from_message(reply_text))

    updated_fields_msg = []
    if extracted_urls:
        new_url = extracted_urls[0]
        new_plat = get_platform_name(new_url)
        with database.get_connection() as conn:
            conn.cursor().execute(
                "UPDATE jobs SET url = ?, platform = ? WHERE id = ?",
                (new_url, new_plat, job_id),
            )
            conn.commit()
        updated_fields_msg.append(f"🔗 الرابط: {new_url} ({new_plat})")

    # If the reply contains text other than the URL, treat it as updated proposal
    text_without_urls = reply_text
    for u in extracted_urls:
        text_without_urls = text_without_urls.replace(u, "").strip()

    if text_without_urls:
        database.update_job_proposal(job_id, text_without_urls)
        updated_fields_msg.append("✏️ نص العرض")

    updated_job = database.get_job_by_id(job_id) or job

    # Refresh the original alert message with the updated proposal and buttons
    try:
        updated_text = format_job_message(updated_job)
        keyboard = build_approval_keyboard(job_id, updated_job.get("url") or "")
        await reply.edit_text(
            text=updated_text,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
    except Exception as exc:
        logger.warning("Failed to refresh original alert message: %s", exc)

    details = " و ".join(updated_fields_msg) if updated_fields_msg else "البيانات"
    await message.reply(
        f"✅ <b>تم تحديث {details} للمشروع #{job_id}!</b>\n"
        "يمكنك الآن النقر على '✅ قدّم' في الرسالة السابقة لتنفيذ التقديم التلقائي.",
    )
    logger.info("Job #%s updated via user reply (%s).", job_id, details)


# -----------------------------------------------------------------------------
# Admin & Utility Commands (/start, /status, /pending, /profile, /test)
# -----------------------------------------------------------------------------

@dp.message(F.text == "/start")
@dp.message(F.text == "/help")
async def cmd_start_help(message: Message):
    """Sends greeting, status overview and command instructions."""
    help_text = (
        "🤖 <b>أهلاً بك في نظام عتريس (Atrees) لصيد مشاريع العمل الحر!</b>\n\n"
        "النظام يعمل في الخلفية لمراقبة قنوات ومجموعات التيليجرام لحظياً، "
        "وتقييم المشاريع باستخدام Gemini AI، وصياغة عروض مقنعة بمجرد رصد وظيفة مطابقة لخبرتك.\n\n"
        "📋 <b>الأوامر المتاحة:</b>\n"
        "• /status أو /stats : إحصائيات المشاريع المرصودة وحالاتها.\n"
        "• /pending : عرض المشاريع المعلقة التي تنتظر موافقتك.\n"
        "• /profile : عرض مهاراتك والتقنيات النشطة في الفلترة.\n"
        "• /test : إرسال مشروع تجريبي لفحص النظام والتأكد من عمل البوت.\n\n"
        "💡 <i>عند وصول أي تنبيه، اضغط '✅ قدّم' للتقديم التلقائي، أو '❌ تخطي'، أو قم بالرد على الرسالة لتعديل العرض!</i>"
    )
    await message.reply(help_text)


@dp.message(F.text.in_({"/status", "/stats"}))
async def cmd_status(message: Message):
    """Displays current system and job statistics from database."""
    stats = database.get_jobs_stats()
    text = (
        "📊 <b>إحصائيات نظام عتريس (Atrees):</b>\n\n"
        f"🔹 <b>إجمالي المشاريع المسجلة:</b> {stats['total']}\n"
        f"⏳ <b>المشاريع المعلقة (بانتظار قرارك):</b> {stats['pending']}\n"
        f"🚀 <b>المشاريع المقدمة بنجاح:</b> {stats['submitted']}\n"
        f"✅ <b>المشاريع المعتمدة:</b> {stats['approved']}\n"
        f"❌ <b>المشاريع التي تم تخطيها:</b> {stats['skipped']}\n"
        f"⚠️ <b>محاولات تقديم متعثرة:</b> {stats['failed']}\n\n"
        "🟢 <b>حالة النظام:</b> متصل ويتنصت لحظياً على القنوات."
    )
    await message.reply(text)


@dp.message(F.text == "/pending")
async def cmd_pending(message: Message):
    """Retrieves and displays recent pending jobs with approval buttons."""
    pending_jobs = database.get_pending_jobs(limit=5)
    if not pending_jobs:
        await message.reply("🎉 <b>رائع! لا توجد أي مشاريع معلقة حالياً.</b>\nسيصلك إشعار فور رصد مشروع جديد مطابق.")
        return

    await message.reply(f"⏳ <b>لديك {len(pending_jobs)} مشاريع معلقة تنتظر قرارك:</b>")
    for job in pending_jobs:
        text = format_job_message(job)
        kb = build_approval_keyboard(job["id"], job.get("url") or "")
        await message.answer(text, reply_markup=kb, disable_web_page_preview=False)


@dp.message(F.text == "/profile")
async def cmd_profile(message: Message):
    """Displays active tech stack from my_profile.json."""
    from ai_engine import ai_engine
    p = ai_engine.profile
    title = p.get("title", "Full-Stack Engineer")
    skills = "\n• " + "\n• ".join(p.get("tech_stack", [])[:7])
    years = p.get("years_of_experience", 5)

    text = (
        f"👤 <b>ملف المطور والمهارات النشطة:</b>\n\n"
        f"💼 <b>المسمى:</b> {title}\n"
        f"⏳ <b>سنوات الخبرة:</b> {years} سنوات\n\n"
        f"🛠 <b>أبرز المهارات في الفلترة:</b>{skills}\n\n"
        "💡 <i>يمكنك تعديل أي من هذه المهارات بسهولة عبر ملف <code>my_profile.json</code></i>."
    )
    await message.reply(text)


@dp.message(F.text == "/test")
async def cmd_test(message: Message):
    """Injects a sample job to test the entire pipeline end-to-end."""
    await message.reply("🧪 <b>جارٍ إدخال مشروع تجريبي لاختبار التقييم وصياغة العرض...</b>")
    from processor import process_new_job
    import asyncio

    test_job = {
        "message_id": 99999,
        "chat_id": "test_channel",
        "chat_title": "قناة مشاريع برمجية (تجربة)",
        "timestamp": "2026-11-09T14:00:00Z",
        "text": (
            "مطلوب مهندس محترف لبناء نظام متكامل لإدارة الطلبات والمخزون.\n"
            "- الـ Backend: .NET Core 8 Web API مع Entity Framework Core وقاعدة بيانات SQL Server.\n"
            "- الـ Frontend: Next.js مع React و TypeScript و Tailwind CSS.\n"
            "- يشمل نظام التوثيق ولوحة تحكم تفاعلية وتقارير مبيعات سريعة.\n"
            "رابط المشروع: https://mostaql.com/projects/77788899"
        ),
        "urls": ["https://mostaql.com/projects/77788899"],
        "target_urls": ["https://mostaql.com/projects/77788899"],
    }
    asyncio.create_task(process_new_job(test_job))


@dp.message(~F.text.startswith("/"), ~F.reply_to_message)
async def handle_direct_project_submission(message: Message):
    """
    Allows the user to paste any real project link or description directly to the bot.
    Atrees will scrape it, evaluate it with Gemini, and return the approval card!
    """
    raw_text = (message.text or message.caption or "").strip()
    if not raw_text:
        return

    from extractor import extract_urls_from_message, filter_target_platform_urls
    from processor import process_new_job
    import asyncio
    import time

    all_urls = extract_urls_from_message(message)
    target_urls = filter_target_platform_urls(all_urls)

    try:
        await message.reply(
            "🔎 <b>تم استلام المشروع!</b>\n"
            "جارٍ سحب التفاصيل من المنصة والتقييم عبر AI..."
        )
    except Exception as exc:
        logger.warning("Could not send immediate receipt reply (%s). Continuing processing...", exc)

    fake_job_data = {
        "message_id": int(time.time()),
        "chat_id": message.chat.id,
        "chat_title": "إرسال يدوي مباشر",
        "timestamp": message.date.isoformat() if message.date else None,
        "text": raw_text,
        "urls": all_urls,
        "target_urls": target_urls,
    }

    asyncio.create_task(process_new_job(fake_job_data))


