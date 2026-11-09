"""
Atrees Local Web Dashboard API (dashboard_api.py)
Lightweight FastAPI server to configure, control, and monitor the Atrees bot.
Zero-code interface for non-technical users.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import dotenv_values, set_key
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Base Directory & Paths
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"
PROFILE_FILE = BASE_DIR / "my_profile.json"
BOT_LOG_FILE = BASE_DIR / "bot.log"
ATREES_LOG_FILE = BASE_DIR / "logs" / "atrees.log"
STATIC_DIR = BASE_DIR / "static"
STATIC_INDEX = STATIC_DIR / "index.html"
BOT_SCRIPT = BASE_DIR / "listener.py"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [dashboard]: %(message)s")
logger = logging.getLogger("atrees.dashboard")


# -----------------------------------------------------------------------------
# Process Manager
# -----------------------------------------------------------------------------
def kill_all_listener_processes(exclude_pid: Optional[int] = None) -> List[int]:
    """Finds and terminates any running instances of listener.py to prevent Telegram conflict."""
    killed: List[int] = []
    try:
        import psutil
        current = psutil.Process()
        ignore_pids = {current.pid}
        if exclude_pid:
            ignore_pids.add(exclude_pid)
        try:
            ignore_pids.update(p.pid for p in current.parents())
        except Exception:
            pass

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = p.info["pid"]
                if pid in ignore_pids:
                    continue
                cmdline = " ".join(p.info["cmdline"] or [])
                if "listener.py" in cmdline:
                    p.kill()
                    killed.append(pid)
            except Exception:
                pass
    except Exception as e:
        logger.warning("psutil check failed: %s", e)
    return killed


class BotProcessManager:
    """Manages the background execution, termination, and logs of the Atrees bot."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.start_timestamp: Optional[float] = None
        self._log_file_handle = None

    def is_running(self) -> bool:
        if self.process is not None:
            if self.process.poll() is None:
                return True
            self._cleanup()

        # Check if any external process is running listener.py
        try:
            import psutil
            current_pid = os.getpid()
            for p in psutil.process_iter(["pid", "cmdline"]):
                try:
                    if p.info["pid"] == current_pid:
                        continue
                    cmd = " ".join(p.info["cmdline"] or [])
                    if "listener.py" in cmd:
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        return False

    def _cleanup(self):
        if self._log_file_handle and not self._log_file_handle.closed:
            try:
                self._log_file_handle.close()
            except Exception:
                pass
        self._log_file_handle = None
        self.process = None
        self.start_timestamp = None

    def get_status(self) -> Dict[str, Any]:
        running = self.is_running()
        uptime = None
        start_iso = None
        active_pid = self.process.pid if self.process else None

        if running and not active_pid:
            # Find PID from system
            try:
                import psutil
                for p in psutil.process_iter(["pid", "cmdline"]):
                    try:
                        cmd = " ".join(p.info["cmdline"] or [])
                        if "listener.py" in cmd:
                            active_pid = p.info["pid"]
                            break
                    except Exception:
                        pass
            except Exception:
                pass

        if running and self.start_timestamp:
            uptime = round(time.time() - self.start_timestamp, 1)
            start_iso = datetime.fromtimestamp(self.start_timestamp).strftime("%Y-%m-%d %H:%M:%S")

        return {
            "running": running,
            "pid": active_pid,
            "uptime_seconds": uptime,
            "started_at": start_iso,
        }

    def start(self) -> Dict[str, Any]:
        # Always terminate any existing orphan listener processes before starting fresh
        killed = kill_all_listener_processes()
        if killed:
            logger.info("Terminated orphan listener processes before start: %s", killed)
            time.sleep(0.5)

        if not BOT_SCRIPT.exists():
            raise HTTPException(
                status_code=500,
                detail=f"ملف تشغيل البوت غير موجود: {BOT_SCRIPT.name}",
            )

        # Open bot.log in append mode with UTF-8 encoding
        try:
            self._log_file_handle = open(BOT_LOG_FILE, "a", encoding="utf-8", buffering=1)
            self._log_file_handle.write(
                f"\n{'='*60}\n[DASHBOARD] Starting Atrees Bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}\n"
            )
            self._log_file_handle.flush()
        except Exception as e:
            logger.error("Failed to open bot.log: %s", e)
            self._log_file_handle = None

        cmd = [sys.executable, "-u", str(BOT_SCRIPT)]

        creationflags = 0
        if sys.platform == "win32":
            # Start in a new process group so signals don't propagate to/from the dashboard
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=self._log_file_handle or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                cwd=str(BASE_DIR),
                creationflags=creationflags,
                text=True,
            )
            self.start_timestamp = time.time()
            logger.info("Started Atrees bot process (PID: %s)", self.process.pid)

            # Wait 0.5s to ensure it didn't immediately crash
            time.sleep(0.5)
            if self.process.poll() is not None:
                exit_code = self.process.poll()
                self._cleanup()
                return {
                    "success": False,
                    "message": f"فشل تشغيل البوت (كود الخطأ: {exit_code}). تفقد التيرمينال أو السجلات للتفاصيل.",
                }

            return {
                "success": True,
                "message": "تم تشغيل البوت بنجاح!",
                "pid": self.process.pid,
            }
        except Exception as exc:
            self._cleanup()
            logger.exception("Failed to start bot process: %s", exc)
            return {"success": False, "message": f"حدث خطأ أثناء بدء التشغيل: {exc}"}

    def stop(self) -> Dict[str, Any]:
        logger.info("Stopping all Atrees bot instances...")
        killed = kill_all_listener_processes()

        if self.process:
            pid = self.process.pid
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], capture_output=True, check=False)
                else:
                    self.process.terminate()
            except Exception as exc:
                logger.warning("Error stopping process %s: %s", pid, exc)

        if self._log_file_handle and not self._log_file_handle.closed:
            self._log_file_handle.write(
                f"\n[DASHBOARD] Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            self._log_file_handle.flush()

        self._cleanup()
        return {"success": True, "message": "تم إيقاف البوت بنجاح."}

    def get_logs(self, max_lines: int = 50) -> List[str]:
        """Fetches the last N lines from bot.log, falling back to logs/atrees.log."""
        target_files = [BOT_LOG_FILE, ATREES_LOG_FILE]
        lines: List[str] = []

        for fpath in target_files:
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        file_lines = f.readlines()
                        if file_lines:
                            lines.extend([line.rstrip("\r\n") for line in file_lines])
                except Exception as e:
                    logger.warning("Error reading %s: %s", fpath, e)

        if not lines:
            return ["[INFO] لا توجد سجلات حتى الآن. اضغط على 'تشغيل البوت' لبدء العمل وسماع القنوات."]

        # Return the last `max_lines`
        return lines[-max_lines:]


bot_manager = BotProcessManager()


# -----------------------------------------------------------------------------
# Pydantic Request Models
# -----------------------------------------------------------------------------
class ProfileModel(BaseModel):
    name: str = Field(default="", description="Full name or developer identity")
    title: str = Field(default="", description="Professional job title")
    years_of_experience: Union[int, float, str] = Field(default=5, description="Years of experience")
    tech_stack: Union[List[str], str] = Field(default=[], description="List of skills or comma-separated string")
    custom_instructions: Optional[str] = Field(
        default="", description="Specific tone, preferred frameworks, or guidelines"
    )
    disliked_topics: Optional[List[str]] = Field(default=None)


class EnvModel(BaseModel):
    TG_API_ID: Optional[str] = ""
    TG_API_HASH: Optional[str] = ""
    TARGET_CHANNELS: Optional[str] = ""
    GEMINI_API_KEY: Optional[str] = ""
    GEMINI_MODEL: Optional[str] = "gemini-3.1-flash-lite"
    GROQ_API_KEY: Optional[str] = ""
    GROQ_MODEL: Optional[str] = "openai/gpt-oss-120b"
    BOT_TOKEN: Optional[str] = ""
    MY_CHAT_ID: Optional[str] = ""
    BROWSER_HEADLESS: Optional[str] = "false"
    AUTO_SUBMIT_CONFIRM: Optional[str] = "false"


# -----------------------------------------------------------------------------
# FastAPI App Definition
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Atrees Dashboard API",
    description="Local Management Dashboard API for Atrees Freelance Job Hunting Bot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Profile Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/profile")
def get_profile() -> Dict[str, Any]:
    """Reads my_profile.json and returns profile data."""
    if not PROFILE_FILE.exists():
        default_data = {
            "name": "Full-Stack Web Developer",
            "title": "Senior Web Developer",
            "years_of_experience": 5,
            "tech_stack": [".NET Core", "React", "Next.js", "Node.js", "Tailwind CSS"],
            "tone_of_voice": "Direct, confident, human senior developer. Clean Code.",
        }
        return {
            **default_data,
            "tech_stack_str": ", ".join(default_data["tech_stack"]),
            "custom_instructions": default_data.get("tone_of_voice", ""),
        }

    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        tech_stack = data.get("tech_stack", [])
        if isinstance(tech_stack, list):
            tech_stack_str = ", ".join(tech_stack)
        else:
            tech_stack_str = str(tech_stack)

        return {
            **data,
            "tech_stack": tech_stack if isinstance(tech_stack, list) else [s.strip() for s in tech_stack_str.split(",")],
            "tech_stack_str": tech_stack_str,
            "custom_instructions": data.get("custom_instructions") or data.get("tone_of_voice") or "",
        }
    except Exception as exc:
        logger.error("Failed to read profile: %s", exc)
        raise HTTPException(status_code=500, detail=f"فشل قراءة الملف الشخصي: {exc}")


@app.post("/api/profile")
def update_profile(profile: ProfileModel) -> Dict[str, Any]:
    """Updates my_profile.json with new freelancer details."""
    current_data = {}
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                current_data = json.load(f)
        except Exception:
            current_data = {}

    # Format tech_stack cleanly
    raw_stack = profile.tech_stack
    if isinstance(raw_stack, str):
        parsed_stack = [s.strip() for s in raw_stack.split(",") if s.strip()]
    elif isinstance(raw_stack, list):
        parsed_stack = []
        for item in raw_stack:
            if isinstance(item, str) and "," in item:
                parsed_stack.extend([s.strip() for s in item.split(",") if s.strip()])
            elif isinstance(item, str) and item.strip():
                parsed_stack.append(item.strip())
    else:
        parsed_stack = []

    try:
        exp = int(profile.years_of_experience)
    except Exception:
        exp = 5

    current_data["name"] = profile.name.strip()
    current_data["title"] = profile.title.strip()
    current_data["years_of_experience"] = exp
    current_data["tech_stack"] = parsed_stack
    if profile.custom_instructions:
        current_data["custom_instructions"] = profile.custom_instructions.strip()
        current_data["tone_of_voice"] = profile.custom_instructions.strip()

    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
        logger.info("Updated my_profile.json successfully.")
        return {"success": True, "message": "تم حفظ الملف الشخصي بنجاح!"}
    except Exception as exc:
        logger.error("Failed to save profile: %s", exc)
        raise HTTPException(status_code=500, detail=f"فشل حفظ الملف الشخصي: {exc}")


# -----------------------------------------------------------------------------
# Environment (.env) Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/env")
def get_env() -> Dict[str, Any]:
    """Reads .env variables and returns them for configuration."""
    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            # If .env does not exist yet, read .env.example as template
            vals = dotenv_values(ENV_EXAMPLE)
        else:
            vals = {}
    else:
        vals = dotenv_values(ENV_FILE)

    return {
        "TG_API_ID": vals.get("TG_API_ID", ""),
        "TG_API_HASH": vals.get("TG_API_HASH", ""),
        "TARGET_CHANNELS": vals.get("TARGET_CHANNELS", "@nafezly,@KhamsatRequests,@MostaqlDevelopment"),
        "GEMINI_API_KEY": vals.get("GEMINI_API_KEY", ""),
        "GEMINI_MODEL": vals.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "GROQ_API_KEY": vals.get("GROQ_API_KEY", ""),
        "GROQ_MODEL": vals.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        "BOT_TOKEN": vals.get("BOT_TOKEN", ""),
        "MY_CHAT_ID": vals.get("MY_CHAT_ID", ""),
        "BROWSER_HEADLESS": vals.get("BROWSER_HEADLESS", "false"),
        "AUTO_SUBMIT_CONFIRM": vals.get("AUTO_SUBMIT_CONFIRM", "false"),
    }


@app.post("/api/env")
def update_env(env_data: EnvModel) -> Dict[str, Any]:
    """Saves updated environment variables into the .env file using python-dotenv."""
    if not ENV_FILE.exists():
        ENV_FILE.touch()

    data_dict = env_data.model_dump(exclude_unset=False)

    try:
        for key, value in data_dict.items():
            if value is not None:
                # Set in .env file cleanly
                set_key(str(ENV_FILE), key, str(value).strip(), quote_mode="never")
                # Also update current process os.environ
                os.environ[key] = str(value).strip()

        logger.info("Updated .env file successfully.")
        return {"success": True, "message": "تم حفظ إعدادات المفاتيح والـ API بنجاح!"}
    except Exception as exc:
        logger.error("Failed to update .env: %s", exc)
        raise HTTPException(status_code=500, detail=f"فشل حفظ الإعدادات في ملف .env: {exc}")


# -----------------------------------------------------------------------------
# Bot Control & Status Endpoints
# -----------------------------------------------------------------------------
@app.get("/api/bot/status")
def get_bot_status() -> Dict[str, Any]:
    """Returns the live status, PID, and uptime of the bot process."""
    return bot_manager.get_status()


@app.post("/api/bot/start")
def start_bot() -> Dict[str, Any]:
    """Spawns the listener.py script in the background."""
    return bot_manager.start()


@app.post("/api/bot/stop")
def stop_bot() -> Dict[str, Any]:
    """Terminates the running listener.py process tree."""
    return bot_manager.stop()


@app.post("/api/browser/open-login")
def open_login_browser() -> Dict[str, Any]:
    """Launches Chrome with the persistent profile so the user can log into Mostaql, Nafezly, and Khamsat."""
    setup_script = BASE_DIR / "setup_session.py"
    if not setup_script.exists():
        raise HTTPException(status_code=404, detail="setup_session.py not found")

    try:
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        subprocess.Popen(
            [sys.executable, str(setup_script)],
            cwd=str(BASE_DIR),
            creationflags=creationflags,
        )
        return {
            "success": True,
            "message": "تم فتح نافذة Google Chrome الحقيقي! سجّل دخولك في المنصات ثم اضغط Enter في النافذة المفتوحة.",
        }
    except Exception as exc:
        logger.exception("Failed to launch setup_session: %s", exc)
        raise HTTPException(status_code=500, detail=f"فشل تشغيل المتصفح: {exc}")


@app.get("/api/bot/logs")
def get_bot_logs(lines: int = 40) -> Dict[str, Any]:
    """Fetches the latest N lines from the bot's logs."""
    return {
        "lines": bot_manager.get_logs(max_lines=lines),
        "status": bot_manager.get_status(),
    }


# -----------------------------------------------------------------------------
# Static Files & SPA Root
# -----------------------------------------------------------------------------
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    """Serves the main single-page UI."""
    if STATIC_INDEX.exists():
        return FileResponse(str(STATIC_INDEX))
    return JSONResponse(
        status_code=200,
        content={"message": "Atrees Dashboard API is running. Place index.html in the static/ folder."},
    )


# -----------------------------------------------------------------------------
# Direct Execution Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("🚀 Starting Atrees Local Web Dashboard Server...")
    print("📍 Local URL:  http://localhost:8000")
    print("📱 Mobile URL: http://192.168.1.60:8000")
    print("=" * 60)
    uvicorn.run("dashboard_api:app", host="0.0.0.0", port=8000, reload=True)

