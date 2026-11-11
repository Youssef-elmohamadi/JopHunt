"""
Auto-Submitter Engine using Playwright with Persistent Context & Stealth Chrome.
Bypasses Cloudflare and login screens by using saved session cookies from ./browser_session.
"""

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse
from playwright.async_api import Page, async_playwright

from config import config
from nafezly_submitter import submit_nafezly_offer
from mostaql_submitter import submit_mostaql_offer
from khamsat_submitter import submit_khamsat_offer

logger = logging.getLogger("atrees.submitter")

SESSION_DIR = Path(__file__).resolve().parent / "browser_session"
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"

# Lock to ensure only one browser process accesses the persistent profile directory at a time
_browser_lock = asyncio.Lock()

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};
"""


@dataclass
class SubmissionResult:
    success: bool
    platform: str
    message: str
    screenshot_path: Optional[str] = None
    before_screenshot: Optional[str] = None
    after_screenshot: Optional[str] = None
    clamped_cost: Optional[int] = None
    submitted_at: Optional[float] = None


# -----------------------------------------------------------------------------
# Helper Utilities
# -----------------------------------------------------------------------------

def extract_numeric_duration_and_budget(
    duration_raw: str, budget_raw: str, job_text: str = ""
) -> Tuple[int, int]:
    """
    Intelligently extracts:
      - duration_days: delivery period in days, strictly matching client's requested timeline.
      - budget_amount: proposed cost in USD, calculated slightly above average (65% of client's budget range).
    """
    dur_text = str(duration_raw or "")
    bud_text = str(budget_raw or "")
    combined = f"{dur_text} {bud_text} {job_text}".strip()

    # --- 1. DURATION (DAYS) ---
    duration_days = None

    # A. Search for explicit duration range: e.g. "1-3 أيام" or "3-5 days"
    d_range = re.search(
        r"(\d+)\s*(?:-|إلى|to)\s*(\d+)\s*(?:يوم|أيام|ايام|يوما|يوماً|days?)\b",
        combined,
        re.IGNORECASE,
    )
    if d_range:
        # Take the upper bound of the duration range (e.g. 3 from 1-3 days)
        duration_days = int(d_range.group(2))
    else:
        # B. Search for single duration: e.g. "3 أيام" or "5 days"
        d_single = re.search(
            r"(\d+)\s*(?:يوم|أيام|ايام|يوما|يوماً|days?)\b",
            combined,
            re.IGNORECASE,
        )
        if d_single:
            duration_days = int(d_single.group(1))
        elif "يومان" in combined or "يومين" in combined:
            duration_days = 2
        elif "يوم واحد" in combined:
            duration_days = 1
        elif "أسبوعين" in combined or "اسبوعين" in combined:
            duration_days = 14
        elif "أسبوع" in combined or "اسبوع" in combined:
            duration_days = 7
        elif "شهر" in combined:
            duration_days = 30

    # --- 2. BUDGET (USD) ---
    budget_amount = None

    # A. Search for budget range: e.g. "$10 - $25", "100$ - 250$", "10 - 25 دولار", "1000.00 - 2500.00"
    b_range = re.search(
        r"(?:\$|USD\s*)?(\d+(?:\.\d+)?)(?:\$|USD)?\s*(?:-|إلى|to)\s*(?:\$|USD\s*)?(\d+(?:\.\d+)?)(?:\$|دولار|USD)?",
        bud_text or combined,
        re.IGNORECASE,
    )
    if b_range:
        min_b = float(b_range.group(1))
        max_b = float(b_range.group(2))
        if max_b > min_b and max_b >= 10:
            # 65% of the range (slightly above average)
            val = min_b + 0.65 * (max_b - min_b)
            if val >= 500:
                budget_amount = int(round(val / 50.0) * 50)
            elif val >= 100:
                budget_amount = int(round(val / 10.0) * 10)
            elif val >= 50:
                budget_amount = int(round(val / 5.0) * 5)
            else:
                budget_amount = int(round(val))
            budget_amount = int(max(min_b, min(budget_amount, max_b)))

    if not budget_amount:
        # B. Single amount: e.g. "$150" or "150 دولار"
        b_single = re.search(
            r"(?:\$|USD\s*)(\d+)|(\d+)\s*(?:\$|دولار|USD)",
            bud_text or combined,
            re.IGNORECASE,
        )
        if b_single:
            budget_amount = int(b_single.group(1) or b_single.group(2))
        else:
            all_b_nums = [int(n) for n in re.findall(r"\d+", bud_text)]
            if all_b_nums:
                budget_amount = max(all_b_nums)

    if not budget_amount or budget_amount < 5:
        budget_amount = 25

    # --- 3. DURATION FALLBACK (If no explicit days mentioned) ---
    if not duration_days or duration_days <= 0:
        if budget_amount <= 50:
            duration_days = 2
        elif budget_amount <= 150:
            duration_days = 3
        elif budget_amount <= 300:
            duration_days = 5
        elif budget_amount <= 1000:
            duration_days = 14
        else:
            duration_days = 30

    # Clamp duration to standard freelance bounds [1, 90]
    duration_days = max(1, min(duration_days, 90))

    return duration_days, budget_amount


async def human_type(element, text: str) -> None:
    """Simulates realistic human typing with micro-delays between keystrokes."""
    await element.click()
    await asyncio.sleep(0.3)
    
    lines = text.split("\n")
    for i, line in enumerate(lines):
        for char in line:
            await element.type(char, delay=random.randint(10, 30))
        if i < len(lines) - 1:
            await element.press("Enter")
            await asyncio.sleep(random.uniform(0.1, 0.25))


# -----------------------------------------------------------------------------
# Platform Handlers (Configured with easy-to-update CSS Selectors)
# -----------------------------------------------------------------------------

class MostaqlHandler:
    """Handler for mostaql.com projects."""

    NAME = "مستقل (Mostaql)"

    PROPOSAL_TEXTAREA_SELECTORS = [
        "form#add-proposal textarea:visible",
        "form[action*='proposal'] textarea:visible",
        "textarea[name='comment']:visible",
        "textarea#comment:visible",
        "textarea#add-proposal-body:visible",
        "textarea:visible:not(#hidden_report_reason):not([name='reason'])",
    ]
    DURATION_INPUT_SELECTORS = [
        "input[name='duration']:visible",
        "input#duration:visible",
        "input[type='number'][name='duration']:visible",
    ]
    BUDGET_INPUT_SELECTORS = [
        "input[name='cost']:visible",
        "input#cost:visible",
        "input[name='budget']:visible",
    ]
    SUBMIT_BUTTON_SELECTORS = [
        "button#add-proposal-submit:visible",
        "button[type='submit']:has-text('أضف عرضك'):visible",
        "button[type='submit']:visible",
        "input[type='submit']:visible",
    ]

    @classmethod
    async def fill_and_submit(
        cls, page: Page, proposal: str, duration: int, budget: int
    ) -> None:
        logger.info("[%s] Locating proposal textarea...", cls.NAME)

        # Check for expander button
        for btn_sel in ("a:has-text('أضف عرضك'):visible", "button:has-text('أضف عرضك'):visible"):
            if await page.locator(btn_sel).count() > 0:
                try:
                    await page.locator(btn_sel).first.click()
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass
                break

        textarea = None
        for sel in cls.PROPOSAL_TEXTAREA_SELECTORS:
            if await page.locator(sel).count() > 0:
                textarea = page.locator(sel).first
                break

        if not textarea:
            raise RuntimeError(
                f"Could not find proposal textarea on {cls.NAME}. "
                "Please verify you are logged in via setup_session.py and the project is open for bids."
            )

        await textarea.scroll_into_view_if_needed()
        await human_type(textarea, proposal)

        # Fill duration
        for sel in cls.DURATION_INPUT_SELECTORS:
            if await page.locator(sel).count() > 0:
                dur_input = page.locator(sel).first
                await dur_input.fill("")
                await dur_input.fill(str(duration))
                break

        # Fill budget
        for sel in cls.BUDGET_INPUT_SELECTORS:
            if await page.locator(sel).count() > 0:
                cost_input = page.locator(sel).first
                await cost_input.fill("")
                await cost_input.fill(str(budget))
                break

        await asyncio.sleep(0.5)


class NafezlyHandler:
    """Handler for nafezly.com projects."""

    NAME = "نفذلي (Nafezly)"

    PROPOSAL_TEXTAREA_SELECTORS = [
        "textarea#offer_description:visible",
        "textarea#offer_description",
        "form#proposal-form textarea:visible",
        "textarea:visible:not(#hidden_report_reason):not([name='reason'])",
    ]
    DURATION_INPUT_SELECTORS = [
        "input#period:visible",
        "input#period",
        "input[name='execution_days']:visible",
        "input[name='duration']:visible",
    ]
    BUDGET_INPUT_SELECTORS = [
        "input#cost:visible",
        "input#cost",
        "input[name='budget']:visible",
    ]
    SUBMIT_BUTTON_SELECTORS = [
        "button#make-offer:visible",
        "button#make-offer",
        "button[type='submit']:visible",
    ]

    @classmethod
    async def fill_and_submit(
        cls, page: Page, proposal: str, duration: int, budget: int
    ) -> None:
        logger.info("[%s] Delegating to submit_nafezly_offer...", cls.NAME)
        res = await submit_nafezly_offer(
            page=page,
            job_url=page.url,
            period_days=duration,
            proposed_cost=budget,
            proposal_text=proposal,
        )
        if not res["success"]:
            raise RuntimeError(res["message"])


class KhamsatHandler:
    """Handler for khamsat.com community requests."""

    NAME = "خمسات (Khamsat)"

    PROPOSAL_TEXTAREA_SELECTORS = [
        "textarea[name='comment']",
        "textarea#comment",
        "textarea.form-control",
    ]
    SUBMIT_BUTTON_SELECTORS = [
        "button[type='submit']",
        "input[type='submit']",
    ]

    @classmethod
    async def fill_and_submit(
        cls, page: Page, proposal: str, duration: int, budget: int
    ) -> None:
        logger.info("[%s] Locating comment textarea...", cls.NAME)

        textarea = None
        for sel in cls.PROPOSAL_TEXTAREA_SELECTORS:
            if await page.locator(sel).count() > 0:
                textarea = page.locator(sel).first
                break

        if not textarea:
            raise RuntimeError(f"Could not find proposal textarea on {cls.NAME}.")

        await human_type(textarea, proposal)
        await asyncio.sleep(0.5)


def get_platform_handler(url: str):
    """Detects platform handler from URL."""
    domain = urlparse(url).netloc.lower()
    if "mostaql.com" in domain:
        return MostaqlHandler
    elif "nafezly.com" in domain:
        return NafezlyHandler
    elif "khamsat.com" in domain:
        return KhamsatHandler
    return None


# -----------------------------------------------------------------------------
# Main Submitter Function
# -----------------------------------------------------------------------------

async def submit_proposal(
    job_url: str,
    proposal_text: str,
    duration: str = "",
    budget: str = "",
    job_text: str = "",
) -> SubmissionResult:
    """
    Navigates to job_url using persistent Google Chrome, fills in the proposal,
    captures a screenshot, and submits the proposal.
    """
    if not job_url:
        return SubmissionResult(
            success=False,
            platform="Unknown",
            message="No job URL provided for submission.",
        )

    handler = get_platform_handler(job_url)
    if not handler:
        return SubmissionResult(
            success=False,
            platform="Unsupported",
            message=f"Unsupported platform URL: {job_url}",
        )

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    duration_days, budget_amount = extract_numeric_duration_and_budget(duration, budget, job_text)

    logger.info(
        "Acquiring browser lock for %s (Duration: %d days, Budget: %d)...",
        handler.NAME,
        duration_days,
        budget_amount,
    )

    async with _browser_lock:
        async with async_playwright() as p:
            # Launch persistent context using genuine Chrome with anti-detection args
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                channel="chrome",  # Uses real installed Chrome
                headless=config.browser_headless,
                viewport={"width": 1280, "height": 850},
                locale="ar-EG",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                ],
                ignore_default_args=["--enable-automation"],
            )

            await context.add_init_script(STEALTH_SCRIPT)
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                # If Nafezly, delegate directly to dedicated submit_nafezly_offer module
                if handler == NafezlyHandler:
                    res = await submit_nafezly_offer(
                        page=page,
                        job_url=job_url,
                        period_days=duration_days,
                        proposed_cost=budget_amount,
                        proposal_text=proposal_text,
                    )
                    await context.close()
                    return SubmissionResult(
                        success=res["success"],
                        platform=handler.NAME,
                        message=res["message"],
                        screenshot_path=res.get("after_screenshot") or res.get("before_screenshot"),
                        before_screenshot=res.get("before_screenshot"),
                        after_screenshot=res.get("after_screenshot"),
                        clamped_cost=res.get("clamped_cost"),
                        submitted_at=time.time() if res["success"] else None,
                    )

                # If Mostaql, delegate to dedicated submit_mostaql_offer module with dynamic question answering
                if handler == MostaqlHandler:
                    res = await submit_mostaql_offer(
                        page=page,
                        job_url=job_url,
                        period_days=duration_days,
                        proposed_cost=budget_amount,
                        proposal_text=proposal_text,
                        project_context=job_text,
                    )
                    await context.close()
                    return SubmissionResult(
                        success=res["success"],
                        platform=handler.NAME,
                        message=res["message"],
                        screenshot_path=res.get("after_screenshot") or res.get("before_screenshot"),
                        before_screenshot=res.get("before_screenshot"),
                        after_screenshot=res.get("after_screenshot"),
                        clamped_cost=res.get("clamped_cost"),
                        submitted_at=time.time() if res["success"] else None,
                    )

                # If Khamsat, delegate to dedicated submit_khamsat_offer module
                if handler == KhamsatHandler:
                    res = await submit_khamsat_offer(
                        page=page,
                        job_url=job_url,
                        proposal_text=proposal_text,
                    )
                    await context.close()
                    return SubmissionResult(
                        success=res["success"],
                        platform=handler.NAME,
                        message=res["message"],
                        screenshot_path=res.get("after_screenshot") or res.get("before_screenshot"),
                        before_screenshot=res.get("before_screenshot"),
                        after_screenshot=res.get("after_screenshot"),
                        submitted_at=time.time() if res["success"] else None,
                    )

                logger.info("Navigating to: %s", job_url)
                await page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)

                # Fill platform-specific proposal form
                await handler.fill_and_submit(
                    page=page,
                    proposal=proposal_text,
                    duration=duration_days,
                    budget=budget_amount,
                )

                # Take a screenshot of the filled form
                timestamp = int(time.time())
                screenshot_path = str(SCREENSHOTS_DIR / f"proposal_{timestamp}.png")
                await page.screenshot(path=screenshot_path, full_page=False)
                logger.info("Screenshot of filled proposal saved to: %s", screenshot_path)

                # Click the Submit button
                submit_button = None
                for sel in handler.SUBMIT_BUTTON_SELECTORS:
                    if await page.locator(sel).count() > 0:
                        submit_button = page.locator(sel).first
                        break

                if submit_button:
                    logger.info("Clicking Submit button for %s...", handler.NAME)
                    await submit_button.click()
                    await page.wait_for_timeout(3500)
                else:
                    logger.warning("Submit button selector not found. Form was filled but not submitted.")

                await context.close()

                return SubmissionResult(
                    success=True,
                    platform=handler.NAME,
                    message="Proposal successfully filled and submitted!",
                    screenshot_path=screenshot_path,
                    submitted_at=time.time(),
                )

            except Exception as exc:
                logger.error("Submission failed on %s: %s", handler.NAME, exc, exc_info=True)
                err_shot = None
                try:
                    err_shot = str(SCREENSHOTS_DIR / f"error_{int(time.time())}.png")
                    await page.screenshot(path=err_shot)
                except Exception:
                    pass

                await context.close()
                return SubmissionResult(
                    success=False,
                    platform=handler.NAME,
                    message=str(exc),
                    screenshot_path=err_shot,
                )
