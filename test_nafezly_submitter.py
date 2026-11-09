import inspect
from nafezly_submitter import clamp, submit_nafezly_offer


def test_clamping_logic():
    # Budget clamping
    assert clamp(10, 25, 100) == 25  # Below min
    assert clamp(150, 25, 100) == 100  # Above max
    assert clamp(50, 25, 100) == 50  # Within range

    # Period clamping
    assert clamp(0, 1, 90) == 1
    assert clamp(100, 1, 90) == 90
    assert clamp(15, 1, 90) == 15
    print("✅ Budget and period clamping passed.")


def test_function_signature():
    sig = inspect.signature(submit_nafezly_offer)
    params = list(sig.parameters.keys())
    assert params == ["page", "job_url", "period_days", "proposed_cost", "proposal_text"]
    assert inspect.iscoroutinefunction(submit_nafezly_offer)
    print("✅ submit_nafezly_offer signature and coroutine verification passed.")


if __name__ == "__main__":
    test_clamping_logic()
    test_function_signature()
    print("🎉 ALL NAFEZLY SUBMITTER TESTS PASSED!")

