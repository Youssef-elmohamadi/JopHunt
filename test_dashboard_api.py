"""
Test Suite for Atrees Local Web Dashboard API
Validates all endpoints using FastAPI TestClient (httpx).
"""

import json
from pathlib import Path
from fastapi.testclient import TestClient
from dashboard_api import app, PROFILE_FILE, ENV_FILE

client = TestClient(app)


def test_index_page():
    print("Testing GET / (Index HTML)...")
    response = client.get("/")
    assert response.status_code == 200
    assert "Atrees" in response.text
    assert "لوحة تحكم عريس" in response.text
    print("✅ Index HTML served successfully.")


def test_profile_endpoints():
    print("Testing Profile endpoints...")
    # 1. GET Profile
    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()
    assert "name" in data
    assert "title" in data
    assert "tech_stack" in data
    assert "tech_stack_str" in data
    original_title = data.get("title", "")

    # 2. POST Profile
    update_payload = {
        "name": "Test Freelancer",
        "title": "Senior Cloud Solutions Architect",
        "years_of_experience": 7,
        "tech_stack": "Python, React, FastAPI, Docker",
        "custom_instructions": "Focus on clean architecture and high performance.",
    }
    post_res = client.post("/api/profile", json=update_payload)
    assert post_res.status_code == 200
    assert post_res.json()["success"] is True

    # 3. Verify in file
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        saved_profile = json.load(f)
    assert saved_profile["name"] == "Test Freelancer"
    assert saved_profile["title"] == "Senior Cloud Solutions Architect"
    assert saved_profile["years_of_experience"] == 7
    assert "FastAPI" in saved_profile["tech_stack"]

    # 4. Restore original profile title if needed
    update_payload["title"] = original_title or "Senior Full-Stack Web Developer & Solutions Engineer"
    client.post("/api/profile", json=update_payload)
    print("✅ Profile GET and POST passed.")


def test_env_endpoints():
    print("Testing Environment (.env) endpoints...")
    # 1. GET Env
    res = client.get("/api/env")
    assert res.status_code == 200
    data = res.json()
    assert "TG_API_ID" in data
    assert "TARGET_CHANNELS" in data
    assert "GEMINI_MODEL" in data
    assert "GROQ_MODEL" in data

    # 2. POST Env (Update Target Channels safely)
    original_channels = data.get("TARGET_CHANNELS", "")
    update_payload = {
        "TARGET_CHANNELS": "@nafezly,@KhamsatRequests,@MostaqlDevelopment",
        "BROWSER_HEADLESS": "false",
        "AUTO_SUBMIT_CONFIRM": "false",
    }
    post_res = client.post("/api/env", json=update_payload)
    assert post_res.status_code == 200
    assert post_res.json()["success"] is True

    # 3. Verify updated value
    verify_res = client.get("/api/env")
    assert verify_res.json()["BROWSER_HEADLESS"] == "false"
    assert verify_res.json()["AUTO_SUBMIT_CONFIRM"] == "false"
    print("✅ Environment GET and POST passed.")


def test_bot_status_and_logs():
    print("Testing Bot Status and Logs endpoints...")
    # Status
    res = client.get("/api/bot/status")
    assert res.status_code == 200
    status_data = res.json()
    assert "running" in status_data
    assert isinstance(status_data["running"], bool)

    # Logs
    log_res = client.get("/api/bot/logs?lines=20")
    assert log_res.status_code == 200
    log_data = log_res.json()
    assert "lines" in log_data
    assert isinstance(log_data["lines"], list)
    assert "status" in log_data
    print("✅ Bot Status and Logs endpoints passed.")


if __name__ == "__main__":
    test_index_page()
    test_profile_endpoints()
    test_env_endpoints()
    test_bot_status_and_logs()
    print("\n🎉 ALL LOCAL WEB DASHBOARD TESTS PASSED!")

