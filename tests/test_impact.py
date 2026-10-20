import pytest

from src.impact import ImpactAssumptions, calculate_impact


def test_standard_calculation():
    r = calculate_impact(ImpactAssumptions(requests_per_week=100, manual_minutes=6, assisted_minutes=3,
                                           hourly_cost=30, ai_cost_per_request=0.02))
    assert r.baseline_hours == pytest.approx(10)
    assert r.assisted_hours == pytest.approx(5)
    assert r.hours_saved == pytest.approx(5)
    assert r.percent_reduction == pytest.approx(0.5)
    assert r.capacity_value == pytest.approx(150)
    assert r.ai_cost == pytest.approx(2)
    assert r.net_benefit == pytest.approx(148)


def test_zero_volume_gives_zeros_and_no_percentage():
    r = calculate_impact(ImpactAssumptions(requests_per_week=0))
    assert r.baseline_hours == r.assisted_hours == r.hours_saved == r.net_benefit == 0
    assert r.percent_reduction is None


def test_zero_manual_time_does_not_divide_by_zero():
    r = calculate_impact(ImpactAssumptions(manual_minutes=0, assisted_minutes=0))
    assert r.percent_reduction is None and r.hours_saved == 0


def test_negative_savings_when_assisted_is_slower():
    r = calculate_impact(ImpactAssumptions(requests_per_week=60, manual_minutes=2, assisted_minutes=5,
                                           hourly_cost=20, ai_cost_per_request=0))
    assert r.hours_saved == pytest.approx(-3)
    assert r.percent_reduction == pytest.approx(-1.5)
    assert r.net_benefit == pytest.approx(-60)


def test_ai_cost_can_make_net_benefit_negative_despite_time_saved():
    r = calculate_impact(ImpactAssumptions(requests_per_week=100, manual_minutes=6, assisted_minutes=5.5,
                                           hourly_cost=10, ai_cost_per_request=1))
    assert r.hours_saved > 0 and r.net_benefit < 0


@pytest.mark.parametrize("field", ["requests_per_week", "manual_minutes", "assisted_minutes", "hourly_cost",
                                   "ai_cost_per_request"])
def test_negative_or_missing_inputs_are_rejected(field):
    with pytest.raises(ValueError):
        calculate_impact(ImpactAssumptions(**{field: -1}))
    with pytest.raises(ValueError):
        calculate_impact(ImpactAssumptions(**{field: float("nan")}))
