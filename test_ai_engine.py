import asyncio
import inspect
from unittest.mock import AsyncMock, patch
from ai_engine import AIEngine, evaluate_and_draft, JobAnalysisResult, _clean_json_markdown

# Sample Job 1: WordPress & WooCommerce Store (RELEVANT)
SAMPLE_MATCHING_WEB_JOB = """
مطلوب مطور ويب محترف لربط بوابة دفع إلكتروني بمتجر ووكومرس (WooCommerce) وإصلاح بطء تحميل الصفحات وتحسين سرعة الموقع.
رابط المشروع: https://mostaql.com/projects/2345678
"""

# Sample Job 2: Irrelevant job (Pure Graphic Design)
SAMPLE_IRRELEVANT_JOB = """
مطلوب مصمم جرافيك لتصميم شعار وهوية بصرية كاملة وتصميم 10 بوستات سوشيال ميديا باستخدام فوتوشوب وإليستريتور.
"""


def test_clean_json_markdown():
    # Plain JSON
    assert _clean_json_markdown('{"is_relevant": true}') == '{"is_relevant": true}'
    # Markdown wrapped
    wrapped = '```json\n{"is_relevant": false, "reason": "test"}\n```'
    assert _clean_json_markdown(wrapped) == '{"is_relevant": false, "reason": "test"}'
    # Text before and after
    noisy = 'Here is the result:\n```json\n{"is_relevant": true}\n```\nHope it helps!'
    assert _clean_json_markdown(noisy) == '{"is_relevant": true}'
    print("✅ _clean_json_markdown passed all cases.")


async def test_failover_mechanism():
    """Tests that if Gemini fails, it gracefully falls over to Groq, and if Groq fails, falls over to Ollama."""
    engine = AIEngine(gemini_api_key="dummy_key", groq_api_key="dummy_key", ollama_host="http://localhost:11434")

    # Case A: Gemini fails with 429 Rate Limit, Groq succeeds
    expected_groq_result = JobAnalysisResult(
        is_relevant=True,
        reason="Matched fullstack requirements",
        estimated_budget="$150 / 3 days",
        proposal_arabic="أهلاً بك، سأقوم بحل المشكلة فوراً...",
    )

    engine._call_gemini = AsyncMock(side_effect=RuntimeError("429 RESOURCE_EXHAUSTED"))
    engine._call_groq = AsyncMock(return_value=expected_groq_result)
    engine._call_ollama = AsyncMock()

    result = await engine.evaluate_and_draft("مطلوب موقع Next.js")
    assert result == expected_groq_result
    assert engine._call_gemini.called
    assert engine._call_groq.called
    assert not engine._call_ollama.called
    print("✅ Failover: Gemini failure -> Groq success passed.")

    # Case B: Gemini and Groq fail, Ollama succeeds
    expected_ollama_result = JobAnalysisResult(
        is_relevant=True,
        reason="Ollama local analyzed web project",
        estimated_budget="$200 / 5 days",
        proposal_arabic="أهلاً بك من خلال النموذج المحلي...",
    )
    engine._call_gemini = AsyncMock(side_effect=RuntimeError("Gemini down"))
    engine._call_groq = AsyncMock(side_effect=RuntimeError("Groq 500 error"))
    engine._call_ollama = AsyncMock(return_value=expected_ollama_result)

    result2 = await engine.evaluate_and_draft("مطلوب مطور لارافل")
    assert result2 == expected_ollama_result
    assert engine._call_ollama.called
    print("✅ Failover: Gemini & Groq failure -> Ollama success passed.")

    # Case C: All fail -> returns None
    engine._call_gemini = AsyncMock(side_effect=RuntimeError("Gemini down"))
    engine._call_groq = AsyncMock(side_effect=RuntimeError("Groq down"))
    engine._call_ollama = AsyncMock(side_effect=RuntimeError("Ollama down"))

    result3 = await engine.evaluate_and_draft("مطلوب عمل ما")
    assert result3 is None
    print("✅ Failover: All providers fail -> returns None gracefully passed.")


async def run_live_evaluations():
    print("\n--- Running Live Evaluation Test ---")
    print("Testing Job 1: (Web Dev / E-Commerce / Speed -> Should be RELEVANT)")
    res1 = await evaluate_and_draft(
        job_text=SAMPLE_MATCHING_WEB_JOB,
        job_url="https://mostaql.com/projects/2345678",
    )
    if res1:
        print(f"Is Relevant: {res1.is_relevant}")
        print(f"Reason: {res1.reason}")
        print(f"Budget: {res1.estimated_budget}")
        print(f"Proposal:\n{res1.proposal_arabic}")
    else:
        print("Note: API call returned None (check API keys or logs).")

    print("\n" + "=" * 50 + "\n")

    print("Testing Job 2: (Pure Graphic Design -> Should be IRRELEVANT)")
    res2 = await evaluate_and_draft(job_text=SAMPLE_IRRELEVANT_JOB)
    if res2:
        print(f"Is Relevant: {res2.is_relevant}")
        print(f"Reason: {res2.reason}")


async def main():
    test_clean_json_markdown()
    await test_failover_mechanism()
    await run_live_evaluations()
    print("\n🎉 ALL MULTI-MODEL FALLBACK CHAIN TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
