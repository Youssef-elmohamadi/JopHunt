from submitter import extract_numeric_duration_and_budget

duration_str = "حسب نطاق العمل المطلوب / 15-25 يوماً"
budget_str = "$2500.00 - $5000.00"
job_text = """
عنوان المشروع: تصميم وتطوير متجر الكتروني متكامل لبيع المنتجات و الاكسسوارات
الميزانية المعروضة: $2500.00 - $5000.00
مدة التنفيذ المتوقعة: 20 يوما
"""

d, b = extract_numeric_duration_and_budget(duration_str, budget_str, job_text)
print(f"Calculated -> Duration: {d} days | Budget: {b} USD")

