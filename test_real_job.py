"""
CLI Helper to Test Atrees on a Real Project URL or Text.
Usage:
  python test_real_job.py "https://mostaql.com/projects/XXXXXX"
  python test_real_job.py "نص المشروع هنا..."
"""

import asyncio
import sys
import time
from extractor import extract_urls_from_message, filter_target_platform_urls
from processor import process_new_job


class MockTelegramMsg:
    def __init__(self, text: str):
        self.raw_text = text
        self.entities = []


async def main():
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:]).strip()
    else:
        print("=" * 60)
        print("🎯 [تجربة مشروع حقيقي على نظام عريس]")
        print("=" * 60)
        user_input = input("👉 ضع رابط المشروع (مستقل / نفذلي) أو نص المشروع واضغط Enter:\n> ").strip()

    if not user_input:
        print("❌ لم يتم إدخال أي رابط أو نص.")
        return

    # Extract URLs if present
    mock_msg = MockTelegramMsg(user_input)
    urls = extract_urls_from_message(mock_msg)
    target_urls = filter_target_platform_urls(urls)

    job_data = {
        "message_id": int(time.time()),
        "chat_id": "manual_test",
        "chat_title": "تجربة مشروع حقيقي (CLI)",
        "timestamp": "2026-11-09T14:30:00Z",
        "text": user_input,
        "urls": urls,
        "target_urls": target_urls,
    }

    print("\n⏳ جارٍ المعالجة وسحب البيانات والتقييم بـ Gemini...")
    await process_new_job(job_data)
    print("✅ تم الانتهاء! تحقق من الـ Terminal ورسائل البوت على تيليجرام.")


if __name__ == "__main__":
    asyncio.run(main())

