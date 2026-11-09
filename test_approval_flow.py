import asyncio
import database
from approval_bot import (
    build_approval_keyboard,
    format_job_message,
    get_platform_name,
)


def test_database_and_approval_flow():
    print("Testing Database Schema & CRUD Operations...")
    database.init_db()
    import time
    test_ts = int(time.time() * 1000)
    test_url = f"https://mostaql.com/projects/{test_ts}"
    test_bot_msg_id = test_ts % 100000000

    # 1. Insert Job
    job_id = database.insert_job(
        platform="مستقل (Mostaql)",
        url=test_url,
        channel_title="مشاريع مستقل برمجية",
        channel_id="-1001928374",
        message_id=test_ts,
        job_text="مطلوب مهندس دوت نت كور ورياكت لبناء منصة إدارة عيادات طبية.",
        summary="مشروع متطابق مع خبرتك في .NET Core و React.",
        estimated_budget="$500 - $800 / 7 أيام",
        proposal="مرحباً بك، اطلعت على متطلبات منصة العيادات. سأقوم بتنفيذ الـ Backend باستخدام ASP.NET Core وفق Clean Architecture...",
        status="pending",
    )
    assert job_id > 0, "Job ID should be generated"
    print(f"✅ Job inserted successfully with ID: {job_id}")

    # 2. Check deduplication check
    assert database.is_job_url_seen(test_url) is True
    assert database.is_job_url_seen("https://mostaql.com/projects/999999999") is False
    print("✅ Deduplication check passed.")

    # 3. Link bot message id
    database.link_bot_message_id(job_id, bot_message_id=test_bot_msg_id)
    job_by_bot_msg = database.get_job_by_bot_message_id(test_bot_msg_id)
    assert job_by_bot_msg is not None
    assert job_by_bot_msg["id"] == job_id
    print("✅ Bot message linking passed.")

    # 4. Simulate user editing the proposal by replying
    new_text = "مرحباً، هذه مسودة معدلة: سأبدأ فوراً ببناء الـ APIs وقواعد البيانات SQL Server..."
    assert database.update_job_proposal(job_id, new_text) is True
    updated_job = database.get_job_by_id(job_id)
    assert updated_job["proposal"] == new_text
    print("✅ Proposal edit via reply simulation passed.")

    # 5. Check formatting & inline keyboard
    formatted_msg = format_job_message(updated_job)
    assert "مستقل (Mostaql)" in formatted_msg
    assert test_url in formatted_msg
    assert new_text in formatted_msg

    kb = build_approval_keyboard(job_id, updated_job["url"])
    assert len(kb.inline_keyboard) == 2  # Action buttons row + URL button row
    assert kb.inline_keyboard[0][0].callback_data == f"submit_{job_id}"
    assert kb.inline_keyboard[0][1].callback_data == f"skip_{job_id}"
    print("✅ Message formatting and inline keyboard verification passed.")

    # 6. Simulate Approval
    assert database.update_job_status(job_id, "approved") is True
    approved_job = database.get_job_by_id(job_id)
    assert approved_job["status"] == "approved"
    print("✅ Status update to 'approved' passed.")

    # 7. Simulate Skip
    assert database.update_job_status(job_id, "skipped") is True
    skipped_job = database.get_job_by_id(job_id)
    assert skipped_job["status"] == "skipped"
    print("✅ Status update to 'skipped' passed.")

    print("\n🎉 ALL APPROVAL BOT & DATABASE TESTS PASSED!")


if __name__ == "__main__":
    test_database_and_approval_flow()

