@echo off
chcp 65001 >nul
title Atrees - تسجيل الدخول لمنصات العمل الحر
cd /d "%~dp0"

echo ========================================================
echo   🔐 Atrees - تسجيل الدخول لمنصات العمل الحر (مرة واحدة فقط)
echo ========================================================
echo.
echo سيتم فتح متصفح Chrome الآن لتسجيل الدخول في:
echo   - مستقل (Mostaql)
echo   - نفذلي (Nafezly)
echo   - خمسات (Khamsat)
echo.
echo ملاحظة: يتم حفظ جلسة الدخول والكوكيز بأمان محلياً في جهازك (browser_session)
echo ولن تحتاج لإدخال كلمة المرور مرة أخرى بعد ذلك.
echo.

if not exist .venv\Scripts\python.exe (
    echo [ERROR] البيئة الافتراضية غير موجودة. يرجى تشغيل Start_Dashboard.bat أولاً.
    pause
    exit /b 1
)

.\.venv\Scripts\python.exe setup_session.py
pause

