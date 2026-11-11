"""
AI Relevance & Proposal Drafting Engine (ai_engine.py)
Implements a robust Multi-Model Fallback Chain (Failover strategy):
  1. Google Gemini API (google-genai / v1beta)
  2. Groq API (official groq async python SDK / Llama 3)
  3. Ollama (local self-hosted model via aiohttp / Docker / Linux)
Guarantees 100% free and continuous operation even during rate limits or outages.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from google import genai
from google.genai import types
from groq import AsyncGroq
from pydantic import BaseModel, Field

from config import config

logger = logging.getLogger("atrees.ai_engine")
PROFILE_PATH = Path(__file__).resolve().parent / "my_profile.json"


class JobAnalysisResult(BaseModel):
    is_relevant: bool = Field(
        description="True ONLY if the job matches any of the freelancer's listed skills or services."
    )
    reason: str = Field(
        description=(
            "Brief concise summary of the project and why it matches in ARABIC ONLY (باللغة العربية حصراً). "
            "مثال: 'المشروع يتطلب ربط واجهات أمامية بـ API وبناء لوحة تحكم، وهو صلب تخصصي.'"
        )
    )
    estimated_budget: str = Field(
        description="Estimated budget range or suggested delivery timeline if applicable (e.g., '$100 - $200 / 3-5 days' or 'حسب نطاق العمل المطلوب')."
    )
    proposal_arabic: str = Field(
        description=(
            "A compelling, concise Arabic proposal. Never mention that you are an AI; speak as a human senior developer. "
            "Start directly with how you will solve the client's problem, and ask one technical question at the end to encourage a reply."
        )
    )


def load_profile() -> dict:
    """Loads the freelancer profile from my_profile.json."""
    if not PROFILE_PATH.exists():
        return {
            "title": "Full-Stack Web Developer",
            "tech_stack": [".NET", "React", "Next.js", "Node.js", "WordPress"],
        }
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read %s: %s", PROFILE_PATH, e)
        return {}


def build_system_instruction() -> str:
    profile = load_profile()
    name = profile.get("name", "مطور ويب متكامل")
    title = profile.get("title", "Senior Full-Stack Web Developer")
    years_exp = profile.get("years_of_experience", 5)
    tech_stack = profile.get("tech_stack", [".NET Core", "React", "Next.js", "Node.js"])
    if isinstance(tech_stack, list):
        tech_stack_str = ", ".join(tech_stack)
    else:
        tech_stack_str = str(tech_stack)
    custom_tone = profile.get("custom_instructions") or profile.get("tone_of_voice") or "Direct, confident, professional senior developer."
    disliked = profile.get("disliked_topics") or []
    disliked_str = "\n".join(f"- {d}" for d in disliked) if disliked else "- Translation, Data Entry, or Content Writing (unless requested in skills)."

    return f"""You are {name}, a skilled professional and {title} ({years_exp}+ years of experience).
Your capabilities, services, and skill stack include:
{tech_stack_str}

Custom Style & Instructions from Profile:
{custom_tone}

Your goal is to evaluate if this freelance project matches ANY of your listed skills/services, and if so, write a highly converting, winning, 100% human-sounding freelance proposal in Arabic.

CRITICAL RULES FOR EVALUATION (is_relevant & reason):
1. MATCHING CRITERIA (is_relevant = True):
   - Set is_relevant = True if the project relates to ANY skill or service explicitly mentioned in your profile or skill stack (for example: Web Development, Software Engineering, Resume/CV Writing, Technical Writing, Database Design, System Architecture, etc.).
   - The field `reason` MUST BE IN ARABIC ONLY (ملخص المشروع باللغة العربية دائماً وليس بالإنجليزية).

2. REJECTION CRITERIA (is_relevant = False):
   - Reject ONLY if the project falls under disliked categories or has zero overlap with your skills:
{disliked_str}
   - If rejected, explain the rejection reason in clear Arabic in the `reason` field.

CRITICAL RULES FOR THE PROPOSAL:
1. GREETING & CLIENT NAME (CRITICAL):
   - ALWAYS start the proposal with a warm, respectful Arabic greeting:
     * If the client's name is known or mentioned, start with: "السلام عليكم أستاذ [اسم العميل]،" (or "أهلاً بك أستاذ [اسم العميل]،").
     * If the client's name is NOT mentioned, start with: "السلام عليكم أخي الكريم،" أو "السلام عليكم ورحمة الله،".
   - Follow the greeting immediately with a line break or continue into the core solution.

2. DEEP REQUIREMENT TARGETING:
   - Address the CORE needs requested by the client (e.g. for CV writing: ATS-friendly format, professional summary, restructuring experience; for Web: responsive UI, backend logic, APIs).
   - Talk about the RESULT and BUSINESS VALUE you will deliver.

3. NO AI CLICHÉS OR ROBOTIC PHRASES:
   - NEVER use generic phrases like: "لقد قرأت مشروعك بعناية", "يسعدني ويشرفني", "أنا الخيار الأمثل", "كذكاء اصطناعي", "بصفتي خبير".
   - Enter directly into your technical insight or practical execution plan.

4. STRUCTURE OF A WINNING PROPOSAL:
   - GREETING: "السلام عليكم أستاذ [الاسم]،"
   - THE HOOK: Direct insight addressing their specific project problem or requirement.
   - THE EXECUTION PLAN: 2-3 concise points showing exactly how you will execute the work.
   - THE TRUST FACTOR: Professional standard, attention to detail, and proven track record.
   - THE CTA QUESTION: Always end with ONE smart question that invites a direct conversation and makes replying easy.

5. LENGTH: 70 to 130 words maximum. Natural, polished professional Arabic.

Output strictly in the specified JSON schema."""


def _clean_json_markdown(text: str) -> str:
    """Strips markdown code fences and isolates the JSON object substring."""
    raw = text.strip()
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if match:
            raw = match.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    return raw.strip()


class AIEngine:
    """
    Multi-Provider AI Engine with automatic failover chain:
      1. Gemini API  (Primary — google-genai SDK with multi-model internal fallback)
      2. Groq API    (Fast Cloud Failover — updated active models)
      3. Ollama      (Local Self-Hosted Offline — if available)
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        ollama_host: Optional[str] = None,
        gemini_model: Optional[str] = None,
        groq_model: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        self.gemini_api_key = (
            gemini_api_key
            or getattr(config, "gemini_api_key", "")
            or os.getenv("GEMINI_API_KEY", "")
        ).strip()

        self.groq_api_key = (
            groq_api_key
            or getattr(config, "groq_api_key", "")
            or os.getenv("GROQ_API_KEY", "")
        ).strip()

        self.ollama_host = (
            ollama_host
            or getattr(config, "ollama_host", "")
            or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        ).strip()

        self.gemini_model = (
            gemini_model
            or getattr(config, "gemini_model", "")
            or os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        ).strip()

        self.groq_model = (
            groq_model
            or getattr(config, "groq_model", "")
            or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        ).strip()

        self.ollama_model = (
            ollama_model
            or getattr(config, "ollama_model", "")
            or os.getenv("OLLAMA_MODEL", "llama3")
        ).strip()

        # Initialize clients lazily or upfront
        self.gemini_client: Optional[genai.Client] = None
        if self.gemini_api_key:
            try:
                self.gemini_client = genai.Client(
                    api_key=self.gemini_api_key,
                    http_options=types.HttpOptions(api_version="v1beta"),
                )
            except Exception as e:
                logger.warning("Failed to initialize Gemini Client: %s", e)

        self.groq_client: Optional[AsyncGroq] = None
        if self.groq_api_key:
            try:
                self.groq_client = AsyncGroq(api_key=self.groq_api_key)
            except Exception as e:
                logger.warning("Failed to initialize Groq Client: %s", e)

        self.profile = load_profile()

    # -------------------------------------------------------------------------
    # Provider 1: Gemini API (google-genai / v1beta)
    # -------------------------------------------------------------------------
    async def _call_gemini(
        self, system_instruction: str, user_prompt: str
    ) -> JobAnalysisResult:
        """Calls Google Gemini API with structured JSON output and internal model fallback."""
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        if not self.gemini_client:
            self.gemini_client = genai.Client(
                api_key=self.gemini_api_key,
                http_options=types.HttpOptions(api_version="v1beta"),
            )

        # Gemini fallback chain (confirmed available on free tier as of Nov 2026)
        models_to_try = [self.gemini_model]
        for fallback_m in [
            "gemini-3.5-flash-lite",   # Confirmed OK
            "gemini-3.1-flash-lite",   # Confirmed OK (fewer free-tier limits)
            "gemini-flash-lite-latest",# Latest alias - catches future upgrades
            "gemini-3.5-flash",        # Full flash as last Gemini resort
        ]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_gemini_err: Optional[Exception] = None
        for model in models_to_try:
            try:
                logger.debug("Calling Gemini model: %s...", model)
                response = await self.gemini_client.aio.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=JobAnalysisResult,
                        temperature=0.3,
                    ),
                )

                if response.parsed:
                    return response.parsed  # type: ignore

                if response.text:
                    clean_json = _clean_json_markdown(response.text)
                    return JobAnalysisResult.model_validate_json(clean_json)

            except Exception as exc:
                last_gemini_err = exc
                logger.warning("Gemini model '%s' failed: %s. Trying next Gemini model...", model, exc)

        raise RuntimeError(f"All Gemini models exhausted: {last_gemini_err}")

    # -------------------------------------------------------------------------
    # Provider 2: Groq API (Official async groq SDK)
    # -------------------------------------------------------------------------
    async def _call_groq(
        self, system_instruction: str, user_prompt: str
    ) -> JobAnalysisResult:
        """Calls Groq API with JSON object response format matching JobAnalysisResult schema."""
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        if not self.groq_client:
            self.groq_client = AsyncGroq(api_key=self.groq_api_key)

        schema_json = json.dumps(JobAnalysisResult.model_json_schema(), ensure_ascii=False)
        groq_system = (
            f"{system_instruction}\n\n"
            "CRITICAL: Output must be a strictly valid JSON object matching this schema:\n"
            f"{schema_json}\n"
            "Output RAW JSON only, without any markdown code fences or conversational text."
        )

        # Active Groq models (verified Nov 2026 — llama3-70b/8b decommissioned)
        models_to_try = [self.groq_model]
        for fallback_m in [
            "openai/gpt-oss-120b",   # Best available on this account
            "openai/gpt-oss-20b",    # Faster, smaller fallback
            "qwen/qwen3.8-27b",      # Alibaba Qwen - good at Arabic
        ]:
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_groq_err: Optional[Exception] = None
        for model in models_to_try:
            try:
                logger.debug("Calling Groq model: %s...", model)
                completion = await self.groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": groq_system},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )

                content = completion.choices[0].message.content or ""
                clean_json = _clean_json_markdown(content)
                return JobAnalysisResult.model_validate_json(clean_json)

            except Exception as exc:
                last_groq_err = exc
                logger.warning("Groq model '%s' failed: %s. Trying next Groq model...", model, exc)

        raise RuntimeError(f"All Groq models exhausted: {last_groq_err}")

    # -------------------------------------------------------------------------
    # Provider 3: Ollama (Local Self-Hosted Fallback via aiohttp)
    # -------------------------------------------------------------------------
    async def _call_ollama(
        self, system_instruction: str, user_prompt: str
    ) -> JobAnalysisResult:
        """Calls locally hosted Ollama API via aiohttp requesting format='json'."""
        if not self.ollama_host:
            raise ValueError("OLLAMA_HOST is not configured.")

        schema_json = json.dumps(JobAnalysisResult.model_json_schema(), ensure_ascii=False)
        ollama_system = (
            f"{system_instruction}\n\n"
            "CRITICAL: You must return a valid JSON object matching this schema:\n"
            f"{schema_json}\n"
            "Output RAW JSON only."
        )

        endpoint = f"{self.ollama_host.rstrip('/')}/api/chat"
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": ollama_system},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,
            },
        }

        logger.debug("Calling Ollama endpoint: %s with model: %s...", endpoint, self.ollama_model)
        timeout = aiohttp.ClientTimeout(total=45)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload) as resp:
                if resp.status != 200:
                    err_body = await resp.text()
                    raise RuntimeError(f"Ollama server returned HTTP {resp.status}: {err_body}")

                data = await resp.json()
                message_content = data.get("message", {}).get("content", "")
                if not message_content:
                    raise RuntimeError("Ollama returned empty response message content.")

                clean_json = _clean_json_markdown(message_content)
                return JobAnalysisResult.model_validate_json(clean_json)

    # -------------------------------------------------------------------------
    # Main Failover Evaluator
    # -------------------------------------------------------------------------
    async def evaluate_and_draft(
        self, job_text: str, job_url: str = ""
    ) -> Optional[JobAnalysisResult]:
        """
        Sends the job description through the Multi-Model Fallback Chain:
          1. Gemini API
          2. Groq API
          3. Ollama (Local)
        Gracefully handles timeouts, rate limits (429), or server errors (500/503),
        falling over to the next provider until success or all fail.
        """
        clean_text = job_text.strip()
        if not clean_text:
            return None

        system_instruction = build_system_instruction()
        user_prompt = f"""يرجى تقييم هذا المشروع وتحديد مدى ملاءمته وصياغة العرض:

رابط المشروع (إن وجد): {job_url or 'لا يوجد رابط'}

نص المشروع / الرسالة:
\"\"\"
{clean_text}
\"\"\"
"""

        # Chain list of (Provider Name, Coroutine Method)
        providers = [
            ("Gemini API", self._call_gemini),
            ("Groq API", self._call_groq),
            ("Ollama Local", self._call_ollama),
        ]

        for provider_name, provider_func in providers:
            try:
                logger.info("Attempting job analysis via Provider: [%s]...", provider_name)
                result = await provider_func(system_instruction, user_prompt)
                if result:
                    logger.info("✅ [%s] successfully analyzed job and generated proposal.", provider_name)
                    return result
            except Exception as exc:
                logger.warning(
                    "⚠️ Provider [%s] failed during analysis: %s. Falling back to next provider...",
                    provider_name,
                    exc,
                )
                continue

        logger.error("❌ All AI providers in the fallback chain (Gemini, Groq, Ollama) failed to evaluate the job.")
        return None


# Global singleton instance
ai_engine = AIEngine()


async def evaluate_and_draft(job_text: str, job_url: str = "") -> Optional[JobAnalysisResult]:
    """Helper module-level function for direct importing."""
    return await ai_engine.evaluate_and_draft(job_text, job_url)
