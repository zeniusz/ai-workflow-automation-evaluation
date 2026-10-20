"""Business-impact estimate. Every output is an estimate derived from the inputs, not a measurement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ImpactAssumptions:
    requests_per_week: float = 250
    manual_minutes: float = 6.0
    assisted_minutes: float = 2.5
    hourly_cost: float = 30.0
    ai_cost_per_request: float = 0.01

    def validate(self) -> None:
        for name, value in vars(self).items():
            if value is None or value != value or value < 0:  # None, NaN or negative
                raise ValueError(f"{name} must be a number that is zero or greater.")


@dataclass(frozen=True)
class ImpactResult:
    baseline_hours: float
    assisted_hours: float
    hours_saved: float  # negative when the AI-assisted process is slower
    percent_reduction: Optional[float]  # None when baseline is zero
    capacity_value: float
    ai_cost: float
    net_benefit: float


def calculate_impact(a: ImpactAssumptions) -> ImpactResult:
    """Weekly estimate. Capacity value = hours saved x hourly cost (time freed, not cash saved)."""
    a.validate()
    baseline = a.requests_per_week * a.manual_minutes / 60
    assisted = a.requests_per_week * a.assisted_minutes / 60
    saved = baseline - assisted
    capacity_value = saved * a.hourly_cost
    ai_cost = a.requests_per_week * a.ai_cost_per_request
    return ImpactResult(
        baseline_hours=baseline,
        assisted_hours=assisted,
        hours_saved=saved,
        percent_reduction=(saved / baseline) if baseline > 0 else None,
        capacity_value=capacity_value,
        ai_cost=ai_cost,
        net_benefit=capacity_value - ai_cost,
    )
