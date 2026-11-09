"""
Setup Persistent Browser Session for Atrees Auto-Submitter.
Opens Real Google Chrome with anti-detection flags so you can log in
with Google OAuth or direct credentials to Mostaql, Nafezly, and Khamsat.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

SESSION_DIR = Path(__file__).resolve().parent / "browser_session"

# Anti-detection stealth script to remove navigator.webdriver
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


async def main():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("🚀 [Atrees Session Setup] Starting Google Chrome in Stealth Mode...")
    print(f"📁 Session Storage Path: {SESSION_DIR}")
    print("=" * 65)
    print("💡 نصائح لتسجيل الدخول بنجاح:")
    print("1. تم تفعيل متصفح Google Chrome الحقيقي وإخفاء إشارات الأتمتة لتجاوز حظر جوجل.")
    print("2. يُفضل تسجيل الدخول بالبريد الإلكتروني وكلمة المرور مباشرة لحساب حسوب/مستقل/نفذلي.")
    print("3. إذا أردت استخدام 'تسجيل الدخول بجوجل'، سيعمل معك الآن بعد تفعيل وضع التخفي.")
    print("4. بعد الانتهاء من تسجيل الدخول في المنصات، ارجع هنا واضغط [Enter].")
    print("=" * 65)

    async with async_playwright() as p:
        # Launch persistent context using genuine Chrome with stealth flags
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            channel="chrome",  # Uses real installed Google Chrome
            headless=False,
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

        # Apply stealth script to all current and future pages
        await context.add_init_script(STEALTH_SCRIPT)

        # Open tabs for platforms
        page_mostaql = context.pages[0] if context.pages else await context.new_page()
        print("🌐 Opening Mostaql (https://mostaql.com/login)...")
        try:
            await page_mostaql.goto("https://mostaql.com/login", timeout=30000)
        except Exception as e:
            print(f"⚠️ Could not load Mostaql login page: {e}")

        page_nafezly = await context.new_page()
        print("🌐 Opening Nafezly (https://nafezly.com/login)...")
        try:
            await page_nafezly.goto("https://nafezly.com/login", timeout=30000)
        except Exception as e:
            print(f"⚠️ Could not load Nafezly login page: {e}")

        page_khamsat = await context.new_page()
        print("🌐 Opening Khamsat (https://khamsat.com)...")
        try:
            await page_khamsat.goto("https://khamsat.com", timeout=30000)
        except Exception as e:
            print(f"⚠️ Could not load Khamsat page: {e}")

        print("\n✅ تم فتح المتصفح. يمكنك الآن تسجيل الدخول في حساباتك.")

        # Wait for user confirmation in terminal
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, input, "\n👉 اضغط [Enter] هنا في الـ Terminal بعد الانتهاء من تسجيل الدخول: "
        )

        print("\n💾 جارٍ حفظ الجلسة والكوكيز في browser_session...")
        await context.close()
        print("🎉 تم حفظ الجلسة بنجاح! المتصفح أصبح مهيأً ومعتمداً لتقديم العروض.")


if __name__ == "__main__":
    asyncio.run(main())
