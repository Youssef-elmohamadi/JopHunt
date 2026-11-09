import asyncio
import pprint
from pathlib import Path
from playwright.async_api import async_playwright

SESSION_DIR = Path(__file__).resolve().parent / "browser_session"

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
"""

async def dump_form():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 850},
            locale="ar-EG",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await ctx.add_init_script(STEALTH_SCRIPT)
        try:
            await page.goto("https://nafezly.com/project/57905", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            
            data = await page.evaluate("""() => {
                const forms = Array.from(document.querySelectorAll('form')).map(f => ({
                    id: f.id,
                    action: f.action,
                    method: f.method,
                    elements: Array.from(f.elements).map(e => ({
                        tag: e.tagName,
                        id: e.id,
                        name: e.name,
                        type: e.type,
                        value: (e.value || '').substring(0, 50),
                        required: e.required,
                        min: e.min,
                        max: e.max,
                        minLength: e.minLength,
                        maxLength: e.maxLength,
                        className: e.className
                    }))
                }));
                const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]')).map(b => ({
                    tag: b.tagName,
                    id: b.id,
                    className: b.className,
                    type: b.type,
                    text: (b.innerText || '').trim(),
                    formId: b.form ? b.form.id : null
                }));
                return { forms: forms, buttons: buttons };
            }""")
            pprint.pprint(data)
        finally:
            await ctx.close()

if __name__ == "__main__":
    asyncio.run(dump_form())
