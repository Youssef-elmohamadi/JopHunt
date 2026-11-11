"""
Mostaql Auto-Submitter with Exact HTML Element Mapping & Dynamic Question AI Answering.
Engineered precisely from Mostaql's live DOM:
  - Form ID: form#project__bid
  - Main Proposal: textarea#bid__details (name="details")
  - Cost/Budget: input#bid__cost (name="cost")
  - Period/Days: input#bid__period (name="period")
  - Submit Button: button#bid__submit
  - Dynamic Questions: textarea[name^="answers["] (id="question__answer_XXXXX") with label.control-label
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.async_api import Page, Locator

from ai_engine import ai_engine, _clean_json_markdown
from config import config

logger = logging.getLogger("atrees.mostaql_submitter")
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"


async def fill_field_and_trigger(locator: Locator, value: str) -> None:
    """
    Fills an input/textarea and dispatches essential browser events
    so that Mostaql's frontend validation (and realCost calculator) updates cleanly.
    """
    await locator.scroll_into_view_if_needed()
    await locator.click()
    await locator.fill(str(value))
    await locator.dispatch_event("input")
    await locator.dispatch_event("change")
    await locator.dispatch_event("keyup")
    await locator.dispatch_event("blur")


async def generate_answers_for_questions(questions: List[str], project_context: str = "") -> List[str]:
    """Uses Gemini / Groq to answer Mostaql's specific questions professionally."""
    if not questions:
        return []

    profile = ai_engine.profile
    title = profile.get("title", "Senior Full-Stack Developer")
    tech_stack = ", ".join(profile.get("tech_stack", [".NET Core", "React", "Next.js"]))

    formatted_q = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
    prompt = f"""أنت {title} ومطور ويب أول (المهارات: {tech_stack}).
قام صاحب المشروع في منصة مستقل بطرح هذه الأسئلة الإلزامية للمتقدمين:

{formatted_q}

سياق المشروع إن وجد:
\"\"\"
{project_context[:600]}
\"\"\"

المطلوب:
أجب عن كل سؤال من هذه الأسئلة بأسلوب احترافي، مقنع، واثق، وبشري تماماً بدون كليشيهات.
كل إجابة يجب أن تكون مباشرة ومختصرة (سطر إلى سطرين كحد أقصى لكل سؤال).
يجب إرجاع النتيجة بتنسيق JSON حصراً يحتوي على مصفوفة answers بنفس ترتيب الأسئلة تماماً."""

    system_instruction = 'Output strictly valid JSON with format: {"answers": ["الإجابة 1", "الإجابة 2", ...]}'

    # Try Gemini first
    if ai_engine.gemini_client:
        try:
            from google.genai import types
            resp = await ai_engine.gemini_client.aio.models.generate_content(
                model=ai_engine.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
            if resp.text:
                parsed = json.loads(_clean_json_markdown(resp.text))
                answers = parsed.get("answers", [])
                if len(answers) == len(questions):
                    return answers
        except Exception as exc:
            logger.warning("Gemini failed to answer Mostaql questions: %s. Trying Groq...", exc)

    # Fallback to Groq
    if ai_engine.groq_key or ai_engine.groq_api_key:
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=ai_engine.groq_api_key)
            completion = await client.chat.completions.create(
                model=ai_engine.groq_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = completion.choices[0].message.content or ""
            parsed = json.loads(_clean_json_markdown(raw))
            answers = parsed.get("answers", [])
            if len(answers) == len(questions):
                return answers
        except Exception as exc:
            logger.warning("Groq failed to answer Mostaql questions: %s", exc)

    # Safe fallback
    return ["نعم، لدي خبرة عملية قوية ومثبتة في تنفيذ وإدارة هذا المتطلب بأعلى معايير الجودة."] * len(questions)


async def handle_dynamic_questions(page: Page, project_context: str = "") -> int:
    """
    Finds all question textareas `textarea[name^='answers[']` and their `label.control-label`,
    generates contextual AI answers, and fills them.
    """
    logger.info("[Mostaql] Detecting dynamic questions matching textarea[name^='answers[']...")

    question_textareas = page.locator("form#project__bid textarea[name^='answers[']")
    count = await question_textareas.count()

    if count == 0:
        # Fallback locator if form id slightly differs
        question_textareas = page.locator("textarea[name^='answers['], textarea.answer_input")
        count = await question_textareas.count()

    if count == 0:
        logger.info("[Mostaql] No dynamic question textareas found.")
        return 0

    logger.info("[Mostaql] Detected %d dynamic question(s) on page!", count)

    questions_text = []
    locators_to_fill = []

    for i in range(count):
        ta = question_textareas.nth(i)
        # Find preceding label.control-label
        q_label = ""
        try:
            # Mostaql structure: <label class="control-label">Question Text</label> ... <textarea ...>
            lbl = ta.locator("xpath=preceding::label[contains(@class, 'control-label')][1]")
            if await lbl.count() > 0:
                q_label = (await lbl.inner_text()).strip()
        except Exception:
            pass

        if not q_label:
            q_label = f"السؤال رقم {i+1}"

        questions_text.append(q_label)
        locators_to_fill.append(ta)

    logger.info("[Mostaql] Questions extracted: %s", questions_text)
    answers = await generate_answers_for_questions(questions_text, project_context)

    for i, loc in enumerate(locators_to_fill):
        ans = answers[i] if i < len(answers) else answers[0]
        logger.info("[Mostaql] Answering Q%d ('%s'): %s", i + 1, questions_text[i][:35], ans[:50])
        await fill_field_and_trigger(loc, ans)
        await page.wait_for_timeout(200)

    return len(locators_to_fill)


async def submit_mostaql_offer(
    page: Page,
    job_url: str,
    period_days: int,
    proposed_cost: int,
    proposal_text: str,
    project_context: str = "",
) -> Dict[str, Any]:
    """
    Submits or fills a proposal on Mostaql with 100% exact DOM selectors:
      - form#project__bid
      - textarea#bid__details
      - input#bid__cost
      - input#bid__period
      - textarea[name^='answers[']
      - button#bid__submit
    """
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("[Mostaql] Navigating to project: %s", job_url)

    if not page.url.startswith(job_url):
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)

    # 1. Expand bid panel if collapsed
    add_bid_btn = page.locator("a[href='#add-bid'], button[data-target='#add-bid'], a:has-text('أضف عرضك')")
    if await add_bid_btn.count() > 0 and await add_bid_btn.first.is_visible():
        try:
            await add_bid_btn.first.click()
            await page.wait_for_timeout(1000)
        except Exception:
            pass

    # 2. Check if Form exists
    form_loc = page.locator("form#project__bid, form[name='project__bid'], form[action*='/bid']")
    if await form_loc.count() == 0:
        raise RuntimeError(
            "Could not find Mostaql bid form (form#project__bid). "
            "Please ensure you are logged into Mostaql and your account is eligible to bid on this project."
        )

    # 3. Fill Dynamic Questions FIRST (if any exist)
    questions_count = await handle_dynamic_questions(page, project_context=project_context or proposal_text)
    if questions_count > 0:
        logger.info("[Mostaql] ✅ Answered %d dynamic question(s) successfully!", questions_count)

    # 4. Fill Cost (input#bid__cost)
    cost_input = page.locator("input#bid__cost, input[name='cost']")
    if await cost_input.count() > 0:
        # Detect dynamic minimum cost required by Mostaql (min attribute, data-min, or window.costValidationMinValue)
        min_cost = 25
        try:
            js_min = await page.evaluate("() => typeof costValidationMinValue !== 'undefined' ? parseInt(costValidationMinValue) : null")
            if js_min and js_min > 0:
                min_cost = js_min
            else:
                min_attr = await cost_input.first.get_attribute("min") or await cost_input.first.get_attribute("data-min")
                if min_attr:
                    min_cost = int(min_attr)
        except Exception:
            pass

        final_cost = max(proposed_cost, min_cost)
        await fill_field_and_trigger(cost_input.first, str(final_cost))
        logger.info("[Mostaql] Filled proposed cost: $%d (min allowed: $%d)", final_cost, min_cost)
    else:
        logger.warning("[Mostaql] Could not find input#bid__cost!")

    # 5. Fill Duration (input#bid__period)
    period_input = page.locator("input#bid__period, input[name='period']")
    if await period_input.count() > 0:
        final_period = max(1, period_days)
        await fill_field_and_trigger(period_input.first, str(final_period))
        logger.info("[Mostaql] Filled delivery duration: %d days", final_period)
    else:
        logger.warning("[Mostaql] Could not find input#bid__period!")

    # 6. Fill Main Proposal Details (textarea#bid__details)
    details_textarea = page.locator("textarea#bid__details, textarea[name='details']")
    if await details_textarea.count() > 0:
        logger.info("[Mostaql] Filling main proposal textarea (textarea#bid__details)...")
        # Ensure proposal meets Mostaql's minimum character requirement (min_length: 200 chars)
        clean_proposal = proposal_text.strip()
        if len(clean_proposal) < 220:
            clean_proposal += (
                "\n\nسأقوم بتنفيذ المشروع وفق أعلى معايير الجودة والـ Clean Code، "
                "مع توفير دعم فني وتوثيق كامل للملفات لضمان سهولة الإدارة والتطوير مستقبلاً."
            )
        await fill_field_and_trigger(details_textarea.first, clean_proposal)
    else:
        raise RuntimeError("Could not find main proposal textarea (textarea#bid__details) on Mostaql.")

    await page.wait_for_timeout(1000)

    # 7. Take Before-Submit Screenshot
    before_screenshot = str(SCREENSHOTS_DIR / "mostaql_before_submit.png")
    await page.screenshot(path=before_screenshot, full_page=False)

    # 8. Check auto-submit mode
    if not config.auto_submit_confirm:
        logger.info(
            "[Mostaql] AUTO_SUBMIT_CONFIRM is False. All fields & %d questions filled. Pausing for human review.",
            questions_count,
        )
        return {
            "success": True,
            "message": f"تم تعبئة تفاصيل العرض والإجابة على {questions_count} أسئلة بنجاح! المتصفح جاهز لمراجعتك.",
            "before_screenshot": before_screenshot,
            "after_screenshot": before_screenshot,
            "clamped_cost": proposed_cost,
        }

    # 9. Click Submit Button (button#bid__submit)
    logger.info("[Mostaql] AUTO_SUBMIT_CONFIRM is True. Clicking button#bid__submit...")
    submit_btn = page.locator("button#bid__submit, button[type='submit']:has-text('أضف عرضك')")
    if await submit_btn.count() > 0:
        await submit_btn.first.scroll_into_view_if_needed()
        await submit_btn.first.click()
    else:
        # Direct form submit
        await page.evaluate("() => { const f = document.querySelector('form#project__bid'); if (f) f.requestSubmit(); }")

    await page.wait_for_timeout(4000)

    # 10. Take After-Submit Screenshot
    after_screenshot = str(SCREENSHOTS_DIR / "mostaql_after_submit.png")
    await page.screenshot(path=after_screenshot, full_page=False)

    return {
        "success": True,
        "message": f"تم تقديم العرض بنجاح على منصة مستقل بعد الإجابة على {questions_count} أسئلة!",
        "before_screenshot": before_screenshot,
        "after_screenshot": after_screenshot,
        "clamped_cost": proposed_cost,
    }
