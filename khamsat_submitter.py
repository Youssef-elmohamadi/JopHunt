"""
Khamsat Auto-Submitter for Community Requests (khamsat.com/community/requests/...).
Engineered with exact DOM selectors from Khamsat:
  - Form ID: form#commentable_form (action^="/community/requests/")
  - Textarea: textarea[name="content"], textarea.c-form__control
  - Confirm Checkbox: input#confirm, input[name="confirm"] (يجب تفعيله للموافقة على شروط خمسات)
  - Submit Button: button#commentable_submit, button.c-button--primary
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict
from playwright.async_api import Page

from config import config

logger = logging.getLogger("atrees.khamsat_submitter")
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"


async def submit_khamsat_offer(
    page: Page,
    job_url: str,
    proposal_text: str,
) -> Dict[str, Any]:
    """
    Submits a proposal/comment to a Khamsat community request:
    1. Navigates to request URL.
    2. Locates form#commentable_form.
    3. Fills textarea[name="content"].
    4. Checks input#confirm (شروط خمسات).
    5. Submits or pauses for review based on config.auto_submit_confirm.
    """
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("[Khamsat] Navigating to request: %s", job_url)

    if not page.url.startswith(job_url):
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)

    # 1. Locate textarea (textarea[name="content"] or form#commentable_form textarea)
    TEXTAREA_SELECTORS = [
        "form#commentable_form textarea[name='content']:visible",
        "textarea[name='content']:visible",
        "textarea.c-form__control:visible",
        "textarea:visible",
    ]
    textarea = None
    for sel in TEXTAREA_SELECTORS:
        if await page.locator(sel).count() > 0:
            textarea = page.locator(sel).first
            break

    if not textarea:
        raise RuntimeError(
            "Could not find comment textarea on Khamsat. "
            "Please ensure you are logged into Khamsat and the request is still open for comments."
        )

    logger.info("[Khamsat] Filling proposal text (%d characters)...", len(proposal_text))
    await textarea.scroll_into_view_if_needed()
    await textarea.click()
    await textarea.fill(proposal_text)
    await textarea.dispatch_event("input")
    await textarea.dispatch_event("change")
    await textarea.dispatch_event("blur")
    await page.wait_for_timeout(300)

    # 2. Check the Terms Checkbox (input#confirm)
    CHECKBOX_SELECTORS = [
        "input#confirm:visible",
        "input[name='confirm']:visible",
        "label[for='confirm']",
    ]
    for sel in CHECKBOX_SELECTORS:
        if await page.locator(sel).count() > 0:
            cb = page.locator(sel).first
            try:
                # If it's the input element, check it
                if await cb.is_visible() and not await cb.is_checked():
                    await cb.check()
                elif not await cb.is_visible():
                    # Click parent label
                    parent_label = page.locator("label[for='confirm']").first
                    await parent_label.click()
            except Exception:
                await page.evaluate("() => { const c = document.querySelector('input#confirm'); if (c) { c.checked = true; c.dispatchEvent(new Event('change')); } }")
            logger.info("[Khamsat] Checked terms confirmation checkbox.")
            break

    await page.wait_for_timeout(500)

    # 3. Take Before-Submit Screenshot
    before_screenshot = str(SCREENSHOTS_DIR / "khamsat_before_submit.png")
    await page.screenshot(path=before_screenshot, full_page=False)

    # 4. Check auto-submit mode
    if not config.auto_submit_confirm:
        logger.info(
            "[Khamsat] AUTO_SUBMIT_CONFIRM is False. Proposal filled. Pausing for human review."
        )
        return {
            "success": True,
            "message": "تمت كتابة العرض وتحديد خانة الشروط بنجاح في خمسات! المتصفح مفتوح بانتظار مراجعتك.",
            "before_screenshot": before_screenshot,
            "after_screenshot": before_screenshot,
        }

    # 5. Click Submit Button (button#commentable_submit)
    logger.info("[Khamsat] AUTO_SUBMIT_CONFIRM is True. Clicking button#commentable_submit...")
    SUBMIT_SELECTORS = [
        "button#commentable_submit:visible",
        "button.c-button--primary:has-text('أرسل'):visible",
        "form#commentable_form button[type='submit']:visible",
    ]
    submitted = False
    for sel in SUBMIT_SELECTORS:
        if await page.locator(sel).count() > 0:
            submit_btn = page.locator(sel).first
            await submit_btn.scroll_into_view_if_needed()
            await submit_btn.click()
            submitted = True
            break

    if not submitted:
        # Fallback to direct form.requestSubmit()
        try:
            await page.evaluate("() => { const f = document.querySelector('form#commentable_form'); if (f) f.requestSubmit(); }")
            submitted = True
        except Exception:
            pass

    if not submitted:
        raise RuntimeError("Could not find the submit button on Khamsat.")

    await page.wait_for_timeout(4000)

    # 6. After-Submit Screenshot
    after_screenshot = str(SCREENSHOTS_DIR / "khamsat_after_submit.png")
    await page.screenshot(path=after_screenshot, full_page=False)

    return {
        "success": True,
        "message": "تم تقديم العرض بنجاح على منصة خمسات!",
        "before_screenshot": before_screenshot,
        "after_screenshot": after_screenshot,
    }

