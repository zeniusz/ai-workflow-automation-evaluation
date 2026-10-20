"""Replay a labelled dataset through a triage function and measure the errors.

Rules that keep the numbers honest:
* every labelled case is in the denominator;
* a request that failed to process counts as wrong on every field;
* flagging a case for review does NOT turn a wrong answer into a right one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from .triage import TriageResult

FIELDS = ("category", "priority", "team")
TriageFn = Callable[[str, str, Optional[str]], TriageResult]

STATUS_CORRECT = "Correct"
STATUS_INCORRECT = "Incorrect"
STATUS_REVIEW = "Review required"
STATUS_FAILED = "Not processed"

RESULT_COLUMNS = [
    "request_id", "request_text", "status",
    "expected_category", "actual_category", "category_ok",
    "expected_priority", "actual_priority", "priority_ok",
    "expected_team", "actual_team", "team_ok",
    "routing_ok", "exact_ok", "needs_review", "review_reason",
    "confidence", "missing_information", "explanation", "error", "engine",
]


@dataclass(frozen=True)
class EvaluationRun:
    dataset: str
    engine: str
    ran_at: str
    results: pd.DataFrame
    metrics: dict


def _same(expected: object, actual: object) -> bool:
    return str(expected).strip().lower() == str(actual).strip().lower()


def _row(case: pd.Series, result: TriageResult) -> dict:
    failed = result.error is not None
    row = {"request_id": case["request_id"], "request_text": case["request_text"]}
    for field in FIELDS:
        expected = case[f"expected_{field}"]
        actual = "" if failed else getattr(result, field)  # unprocessed never matches
        row[f"expected_{field}"] = expected
        row[f"actual_{field}"] = actual
        row[f"{field}_ok"] = (not failed) and _same(expected, actual)
    row["routing_ok"] = row["category_ok"] and row["team_ok"]
    row["exact_ok"] = row["routing_ok"] and row["priority_ok"]
    row["needs_review"] = bool(result.needs_review)
    row["review_reason"] = result.review_reason
    row["confidence"] = result.confidence
    row["missing_information"] = "; ".join(result.missing_information)
    row["explanation"] = result.explanation
    row["error"] = result.error or ""
    row["engine"] = result.engine
    if failed:
        row["status"] = STATUS_FAILED
    elif row["needs_review"]:
        row["status"] = STATUS_REVIEW
    elif row["exact_ok"]:
        row["status"] = STATUS_CORRECT
    else:
        row["status"] = STATUS_INCORRECT
    return row


def compute_metrics(results: pd.DataFrame) -> dict:
    """Accuracy and review statistics. Ratios are None (not 0) when undefined."""
    n = len(results)

    def ratio(num: int, den: int) -> Optional[float]:
        return num / den if den else None

    if n == 0:
        return {"n": 0, "processed": 0, "failed": 0, "review_flagged": 0, "errors": 0, "errors_flagged": 0,
                "errors_unflagged": 0, "straight_through": 0, **{k: None for k in (
                    "category_accuracy", "priority_accuracy", "team_accuracy", "routing_accuracy",
                    "exact_accuracy", "review_rate", "error_catch_rate", "straight_through_rate")}}

    flagged = results["needs_review"].astype(bool)
    wrong = ~results["exact_ok"].astype(bool)
    failed = int((results["status"] == STATUS_FAILED).sum())
    errors = int(wrong.sum())
    straight = int((~flagged & ~wrong).sum())
    metrics = {
        "n": n,
        "processed": n - failed,
        "failed": failed,
        "category_accuracy": results["category_ok"].sum() / n,
        "priority_accuracy": results["priority_ok"].sum() / n,
        "team_accuracy": results["team_ok"].sum() / n,
        "routing_accuracy": results["routing_ok"].sum() / n,
        "exact_accuracy": results["exact_ok"].sum() / n,
        "review_flagged": int(flagged.sum()),
        "review_rate": flagged.sum() / n,
        "errors": errors,
        "errors_flagged": int((wrong & flagged).sum()),
        "errors_unflagged": int((wrong & ~flagged).sum()),
        "error_catch_rate": ratio(int((wrong & flagged).sum()), errors),
        "straight_through": straight,
        "straight_through_rate": straight / n,
    }
    return {k: float(v) if isinstance(v, float) else v for k, v in metrics.items()}  # plain floats for JSON


def evaluate(
    labelled: pd.DataFrame,
    triage_fn: TriageFn,
    *,
    dataset: str,
    engine: str,
    progress: Optional[Callable[[int, int], None]] = None,
) -> EvaluationRun:
    """Run every labelled case through triage_fn and score the outputs."""
    rows = []
    total = len(labelled)
    for i, (_, case) in enumerate(labelled.iterrows(), start=1):
        requester = case.get("requester") or None
        result = triage_fn(str(case["request_id"]), str(case["request_text"]), requester)
        rows.append(_row(case, result))
        if progress:
            progress(i, total)
    results = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    return EvaluationRun(
        dataset=dataset,
        engine=engine,
        ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        results=results,
        metrics=compute_metrics(results),
    )


def mismatch_notes(row: pd.Series) -> list[str]:
    """Plain-language list of what went wrong in one result row."""
    if row["status"] == STATUS_FAILED:
        return [f"Request was not processed: {row['error']}"]
    notes = []
    for field in FIELDS:
        if not row[f"{field}_ok"]:
            notes.append(f"{field.capitalize()}: expected {row[f'expected_{field}']}, got {row[f'actual_{field}']}.")
    return notes


def results_to_csv(results: pd.DataFrame) -> bytes:
    return results.to_csv(index=False).encode("utf-8")
