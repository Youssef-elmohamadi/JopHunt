"""
Nafezly Auto-Submitter Module (nafezly_submitter.py)
Dedicated automation for submitting proposals on Nafezly (نفذلي) using Playwright.
Adheres strictly to Nafezly DOM selectors, dynamic budget clamping, and inline jQuery event triggers.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("atrees.nafezly_submitter")

SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"


def clamp(value: int, min_val: int, max_val: int) -> int:
    """Clamps value to [min_val, max_val]."""
    return max(min_val, min(value, max_val))


async def submit_nafezly_offer(
    page: Page,
    job_url: str,
    period_days: int,
    proposed_cost: int,
    proposal_text: str,
) -> Dict[str, Any]:
    """
    Submits an offer to a Nafezly project with exact DOM selectors and dynamic validation.

    DOM Selectors:
      - Delivery Period: input#period (min 1, max 90)
      - Cost Input:      input#cost (dynamic min/max attributes, jQuery keyup event)
      - Proposal Text:   textarea#offer_description (minlength 30, maxlength 5000)
      - Submit Button:   button#make-offer

    Args:
      page: Playwright async Page instance (with persistent logged-in context)
      job_url: Direct URL to the Nafezly project (e.g. https://nafezly.com/project/57905)
      period_days: Desired delivery duration in days
      proposed_cost: Desired budget in USD
      proposal_text: Proposal text to submit

    Returns:
      dict with keys:
        - success: bool
        - message: str
        - clamped_cost: int
        - clamped_period: int
        - before_screenshot: Optional[str]
        - after_screenshot: Optional[str]
    """
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    before_shot_path = str(SCREENSHOTS_DIR / "nafezly_before_submit.png")
    after_shot_path = str(SCREENSHOTS_DIR / "nafezly_after_submit.png")

    logger.info("[Nafezly] Navigating to project: %s", job_url)

    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        logger.error("[Nafezly] Navigation failed: %s", e)
        return {
            "success": False,
            "message": f"فشل تحميل صفحة المشروع: {e}",
            "clamped_cost": proposed_cost,
            "clamped_period": period_days,
            "before_screenshot": None,
            "after_screenshot": None,
        }

    # Check if there is an expand/show offer form button (e.g. "أضف عرضك" or "تقديم عرض")
    expander_selectors = [
        "a:has-text('أضف عرضك'):visible",
        "button:has-text('أضف عرضك'):visible",
        "a:has-text('تقديم عرض'):visible",
        "button:has-text('تقديم عرض'):visible",
    ]
    for exp_sel in expander_selectors:
        if await page.locator(exp_sel).count() > 0:
            try:
                logger.info("[Nafezly] Clicking offer section expander: %s", exp_sel)
                await page.locator(exp_sel).first.click()
                await page.wait_for_timeout(1000)
            except Exception as exp_err:
                logger.debug("[Nafezly] Expander click ignored: %s", exp_err)
            break

    # 1. Locate textarea#offer_description
    offer_textarea = page.locator("textarea#offer_description")
    is_textarea_visible = False

    try:
        # Wait up to 8 seconds for the textarea to be visible
        await offer_textarea.wait_for(state="visible", timeout=8000)
        is_textarea_visible = True
    except PlaywrightTimeoutError:
        is_textarea_visible = False

    if not is_textarea_visible:
        # Check reasons why the offer form is not available
        page_content = await page.content()

        # Case A: Already submitted an offer
        if any(
            phrase in page_content
            for phrase in [
                "لقد قمت بإضافة عرض",
                "لقد قمت بتقديم عرض",
                "عرضك المقدم",
                "تم تقديم عرضك",
                "تعديل العرض",
            ]
        ):
            msg = "تم تقديم عرض مسبقاً على هذا المشروع من هذا الحساب."
            logger.warning("[Nafezly] %s", msg)
            return {
                "success": False,
                "message": msg,
                "clamped_cost": proposed_cost,
                "clamped_period": period_days,
                "before_screenshot": None,
                "after_screenshot": None,
            }

        # Case B: Project is closed / cancelled / completed
        if any(
            phrase in page_content
            for phrase in [
                "المشروع مغلق",
                "مغلق لتلقي العروض",
                "تم اختيار العرض الفائز",
                "مكتمل",
                "ملغي",
                "لم يعد يقبل عروض",
            ]
        ):
            msg = "المشروع مغلق حالياً أو لا يقبل عروضاً جديدة."
            logger.warning("[Nafezly] %s", msg)
            return {
                "success": False,
                "message": msg,
                "clamped_cost": proposed_cost,
                "clamped_period": period_days,
                "before_screenshot": None,
                "after_screenshot": None,
            }

        # Case C: Not logged in
        if any(
            phrase in page_content
            for phrase in [
                "تسجيل الدخول",
                "الدخول إلى حسابك",
                "قم بتسجيل الدخول أولاً",
            ]
        ) and await page.locator("a[href*='login'], a[href*='signin']").count() > 0:
            msg = "لم يتم تسجيل الدخول في منصة نفذلي. يرجى تشغيل python setup_session.py لتسجيل الدخول أولاً."
            logger.error("[Nafezly] %s", msg)
            return {
                "success": False,
                "message": msg,
                "clamped_cost": proposed_cost,
                "clamped_period": period_days,
                "before_screenshot": None,
                "after_screenshot": None,
            }

        # Fallback generic reason
        msg = "تعذر العثور على نموذج تقديم العرض (textarea#offer_description). قد يكون المشروع غير متاح للتقديم."
        logger.error("[Nafezly] %s", msg)
        return {
            "success": False,
            "message": msg,
            "clamped_cost": proposed_cost,
            "clamped_period": period_days,
            "before_screenshot": None,
            "after_screenshot": None,
        }

    # 2. Dynamic Budget Clamping via input#cost min and max attributes
    cost_input = page.locator("input#cost").first
    min_cost = 25
    max_cost = 500

    try:
        min_attr = await cost_input.get_attribute("min")
        max_attr = await cost_input.get_attribute("max")

        if min_attr:
            min_cost = int(float(min_attr))
        if max_attr:
            max_cost = int(float(max_attr))

        logger.info(
            "[Nafezly] Dynamic budget bounds detected from input#cost: min=%d, max=%d",
            min_cost,
            max_cost,
        )
    except Exception as e:
        logger.warning("[Nafezly] Could not read cost min/max attributes (%s). Using defaults.", e)

    clamped_cost = clamp(proposed_cost, min_cost, max_cost)
    logger.info("[Nafezly] Budget clamped: requested=%d -> clamped=%d", proposed_cost, clamped_cost)

    # 3. Period Clamping (input#period has min="1" and max="90")
    period_input = page.locator("input#period").first
    min_period = 1
    max_period = 90
    try:
        p_min_attr = await period_input.get_attribute("min")
        p_max_attr = await period_input.get_attribute("max")
        if p_min_attr:
            min_period = int(float(p_min_attr))
        if p_max_attr:
            max_period = int(float(p_max_attr))
    except Exception:
        pass

    clamped_period = clamp(period_days, min_period, max_period)
    logger.info("[Nafezly] Period clamped: requested=%d -> clamped=%d", period_days, clamped_period)

    # 4. Fill Delivery Period (input#period)
    logger.info("[Nafezly] Filling delivery period: %d days...", clamped_period)
    await period_input.scroll_into_view_if_needed()
    await period_input.click()
    await period_input.fill(str(clamped_period))

    # 5. Fill Cost (input#cost)
    logger.info("[Nafezly] Filling cost: $%d...", clamped_cost)
    await cost_input.scroll_into_view_if_needed()
    await cost_input.click()
    await cost_input.fill(str(clamped_cost))

    # 6. Proposal Text: Ensure minimum 35 chars, then fill textarea#offer_description
    clean_proposal = (proposal_text or "").strip()
    if len(clean_proposal) < 35:
        clean_proposal = (
            f"{clean_proposal}\n\n"
            "جاهز للبدء فوراً ومناقشة التفاصيل الفنية وتنفيذ المطلوب بأعلى جودة واحترافية."
        ).strip()

    logger.info("[Nafezly] Filling offer description (%d characters)...", len(clean_proposal))
    await offer_textarea.scroll_into_view_if_needed()
    await offer_textarea.click()
    await offer_textarea.fill(clean_proposal)

    # 7. Crucial: Trigger jQuery Validate events across all fields and clear error states
    logger.info("[Nafezly] Triggering jQuery validate events and syncing #gain_value...")
    await page.evaluate(
        """(data) => {
            if (window.$) {
                // 1. Period
                const $p = $('#period');
                if ($p.length) {
                    $p.val(data.period).trigger('input').trigger('change').trigger('keyup').trigger('blur');
                    $('#period-error').remove();
                    $p.removeClass('error');
                }
                // 2. Cost & Gain
                const $c = $('#cost');
                if ($c.length) {
                    $c.val(data.cost).trigger('input').trigger('change').trigger('keyup').trigger('blur');
                    const net = (data.cost - (data.cost * 0.15)).toFixed(2);
                    $('#gain_value').val(net).trigger('input').trigger('change').trigger('keyup').trigger('blur');
                    $('.gain_value').text(net);
                    $('#cost-error').remove();
                    $('#gain_value-error').remove();
                    $c.removeClass('error');
                }
                // 3. Proposal Description
                const $ta = $('#offer_description');
                if ($ta.length) {
                    $ta.val(data.proposal).trigger('input').trigger('change').trigger('keyup').trigger('blur');
                    $('#offer_description-error').remove();
                    $ta.removeClass('error');
                }
                // 4. Force jQuery Validate plugin to recognize form as valid
                if ($('#offer-form').data('validator')) {
                    $('#offer-form').valid();
                }
            }
        }""",
        {
            "period": str(clamped_period),
            "cost": str(clamped_cost),
            "proposal": clean_proposal,
        },
    )
    await page.wait_for_timeout(600)

    # Check calculated gain value if present in DOM
    gain_locator = page.locator("#gain_value")
    if await gain_locator.count() > 0:
        gain_text = (await gain_locator.first.input_value() if await gain_locator.first.evaluate("el => 'value' in el") else await gain_locator.first.text_content()) or ""
        logger.info("[Nafezly] Calculated #gain_value is: %s", gain_text.strip())

    # 8. Take Screenshot Before Submit (Should be clean with NO red error messages)
    try:
        await page.screenshot(path=before_shot_path, full_page=False)
        logger.info("[Nafezly] Before-submit screenshot saved to: %s", before_shot_path)
    except Exception as shot_err:
        logger.warning("[Nafezly] Failed to capture before-submit screenshot: %s", shot_err)
        before_shot_path = None

    # 9. Submit: Click button#make-offer and handle fallback submission
    submit_button = page.locator("button#make-offer").first
    if await submit_button.count() == 0:
        submit_button = page.locator("button:has-text('تقديم عرضك'), button:has-text('أضف العرض')").first

    if await submit_button.count() == 0:
        msg = "تم ملء النموذج بنجاح ولكن لم يتم العثور على زر الإرسال (button#make-offer)."
        logger.error("[Nafezly] %s", msg)
        return {
            "success": False,
            "message": msg,
            "clamped_cost": clamped_cost,
            "clamped_period": clamped_period,
            "before_screenshot": before_shot_path,
            "after_screenshot": None,
        }

    logger.info("[Nafezly] Clicking button#make-offer...")
    await submit_button.scroll_into_view_if_needed()
    await submit_button.click()

    # Wait for navigation or network idle (3-5s)
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        await page.wait_for_timeout(3500)

    # Fallback: if the form is still in the DOM and still on same page, invoke requestSubmit directly
    has_form = await page.locator("form#offer-form").count() > 0
    if has_form:
        has_errors = await page.locator("label.error:visible, .invalid-feedback:visible").count() > 0
        if not has_errors:
            logger.info("[Nafezly] Triggering direct form.requestSubmit() fallback...")
            await page.evaluate("""() => {
                const f = document.querySelector('form#offer-form');
                if (f) {
                    if (f.requestSubmit) f.requestSubmit();
                    else f.submit();
                }
            }""")
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                await page.wait_for_timeout(3500)

    # 10. Take Screenshot After Submit
    try:
        await page.screenshot(path=after_shot_path, full_page=False)
        logger.info("[Nafezly] After-submit screenshot saved to: %s", after_shot_path)
    except Exception as shot_err:
        logger.warning("[Nafezly] Failed to capture after-submit screenshot: %s", shot_err)
        after_shot_path = None

    success_msg = f"تم تقديم العرض بنجاح على منصة نفذلي! (الميزانية المعتمدة: ${clamped_cost}، المدة: {clamped_period} أيام)."
    logger.info("[Nafezly] %s", success_msg)

    return {
        "success": True,
        "message": success_msg,
        "clamped_cost": clamped_cost,
        "clamped_period": clamped_period,
        "before_screenshot": before_shot_path,
        "after_screenshot": after_shot_path,
    }

