from submitter import (
    extract_numeric_duration_and_budget,
    get_platform_handler,
    MostaqlHandler,
    NafezlyHandler,
    KhamsatHandler,
)


def test_numeric_extraction():
    # 1. 300$ - 500$ (Midpoint is 400$, slightly above average is 430$)
    dur, bud = extract_numeric_duration_and_budget("5 أيام", "300$ - 500$")
    assert dur == 5
    assert bud == 430

    # 2. $100 - $250 (Midpoint is 175$, slightly above average is 200$)
    dur_m, bud_m = extract_numeric_duration_and_budget("15 يوما", "$100 - $250")
    assert dur_m == 15, "Should stick strictly to client requested duration"
    assert bud_m == 200, "Should be slightly above average"

    # 3. Project #7 case: $10 - $25 / 1-3 أيام (Midpoint is 17.5$, slightly above is 20$)
    dur_j7, bud_j7 = extract_numeric_duration_and_budget("$10 - $25 / 1-3 أيام", "$10 - $25 / 1-3 أيام")
    assert dur_j7 == 3, f"Duration should be client's 3 days, not {dur_j7}"
    assert bud_j7 == 20, f"Budget should be 20$ (slightly above average), not {bud_j7}"

    # 4. Nafezly case: only budget mentioned '10 - 25 دولار'
    dur_naf, bud_naf = extract_numeric_duration_and_budget("10 - 25 دولار", "10 - 25 دولار")
    assert dur_naf == 2, f"Duration should default to 2 days for small tasks, not {dur_naf}"
    assert bud_naf == 20

    # 5. Large project: $1000 - $2500 / 60 يوما (Midpoint is 1750$, slightly above is 2000$)
    dur_lg, bud_lg = extract_numeric_duration_and_budget("60 يوما", "$1000 - $2500")
    assert dur_lg == 60, "Should match client requested 60 days"
    assert bud_lg == 2000

    # 6. Single budget mention $250
    dur2, bud2 = extract_numeric_duration_and_budget("7 days / $250", "$250")
    assert dur2 == 7
    assert bud2 == 250

    # 7. Empty strings
    dur3, bud3 = extract_numeric_duration_and_budget("", "")
    assert dur3 == 2
    assert bud3 == 25
    print("✅ Duration adherence and slightly-above-average budget calculation passed.")


def test_platform_detection():
    h_mostaql = get_platform_handler("https://mostaql.com/projects/12345")
    assert h_mostaql == MostaqlHandler
    assert "textarea[name='comment']:visible" in h_mostaql.PROPOSAL_TEXTAREA_SELECTORS

    h_nafezly = get_platform_handler("https://nafezly.com/projects/98765")
    assert h_nafezly == NafezlyHandler
    assert "textarea#offer_description:visible" in h_nafezly.PROPOSAL_TEXTAREA_SELECTORS

    h_khamsat = get_platform_handler("https://khamsat.com/community/requests/123")
    assert h_khamsat == KhamsatHandler

    h_other = get_platform_handler("https://google.com")
    assert h_other is None
    print("✅ Platform detection and selector presence passed.")


if __name__ == "__main__":
    test_numeric_extraction()
    test_platform_detection()
    print("🎉 ALL SUBMITTER LOGIC TESTS PASSED!")

