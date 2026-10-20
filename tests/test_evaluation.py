import pandas as pd
import pytest

from src.data_io import load_holdout, load_sample
from src.evaluation import (STATUS_CORRECT, STATUS_FAILED, STATUS_INCORRECT, STATUS_REVIEW, compute_metrics, evaluate,
                            mismatch_notes, results_to_csv)
from src.triage import TriageResult, failed_result, run_triage


def make_result(request_id, category, priority, team, review=False):
    return TriageResult(request_id=request_id, engine="fake", summary="s", category=category, priority=priority,
                        team=team, needs_review=review)


def labelled(rows):
    return pd.DataFrame(rows, columns=["request_id", "requester", "request_text", "expected_category",
                                       "expected_priority", "expected_team"])


CASES = labelled([
    ["a", "", "t1", "IT", "High", "IT Service Desk"],
    ["b", "", "t2", "Facilities", "Normal", "Facilities Maintenance"],
    ["c", "", "t3", "Supplies", "Low", "Supply & Procurement"],
    ["d", "", "t4", "Equipment", "Urgent", "Biomedical Engineering"],
])


def fake_triage(request_id, text, requester):
    return {
        "a": make_result("a", "IT", "High", "IT Service Desk"),                     # fully correct
        "b": make_result("b", "Facilities", "High", "Facilities Maintenance"),      # priority wrong, unflagged
        "c": make_result("c", "IT", "Low", "IT Service Desk", review=True),         # wrong but flagged
        "d": failed_result("d", "fake", "boom"),                                    # not processed
    }[request_id]


def test_metric_calculations():
    m = evaluate(CASES, fake_triage, dataset="d", engine="fake").metrics
    assert m["n"] == 4 and m["failed"] == 1 and m["processed"] == 3
    assert m["category_accuracy"] == pytest.approx(2 / 4)   # a, b
    assert m["priority_accuracy"] == pytest.approx(2 / 4)   # a, c
    assert m["team_accuracy"] == pytest.approx(2 / 4)
    assert m["routing_accuracy"] == pytest.approx(2 / 4)
    assert m["exact_accuracy"] == pytest.approx(1 / 4)
    assert m["review_flagged"] == 2                         # c and the failed case
    assert m["errors"] == 3 and m["errors_flagged"] == 2 and m["errors_unflagged"] == 1
    assert m["error_catch_rate"] == pytest.approx(2 / 3)
    assert m["straight_through"] == 1


def test_status_values_and_unprocessed_never_counts_as_success():
    results = evaluate(CASES, fake_triage, dataset="d", engine="fake").results.set_index("request_id")
    assert results.loc["a", "status"] == STATUS_CORRECT
    assert results.loc["b", "status"] == STATUS_INCORRECT
    assert results.loc["c", "status"] == STATUS_REVIEW
    assert results.loc["d", "status"] == STATUS_FAILED
    assert not results.loc["d", ["category_ok", "priority_ok", "team_ok"]].any()
    assert not results.loc["c", "exact_ok"]  # flagged-but-wrong stays wrong


def test_failed_case_does_not_match_even_when_label_is_other():
    cases = labelled([["x", "", "t", "Other", "Normal", "Operations Triage"]])
    run = evaluate(cases, lambda i, t, q: failed_result(i, "fake", "boom"), dataset="d", engine="fake")
    assert run.metrics["exact_accuracy"] == 0 and run.metrics["failed"] == 1


def test_empty_dataset_has_no_division_by_zero():
    m = compute_metrics(evaluate(CASES.iloc[0:0], fake_triage, dataset="d", engine="fake").results)
    assert m["n"] == 0 and m["routing_accuracy"] is None and m["error_catch_rate"] is None


def test_mismatch_notes_and_csv_export():
    results = evaluate(CASES, fake_triage, dataset="d", engine="fake").results
    notes = mismatch_notes(results.set_index("request_id", drop=False).loc["b"])
    assert notes == ["Priority: expected Normal, got High."]
    csv = results_to_csv(results).decode()
    assert csv.splitlines()[0].startswith("request_id,request_text,status") and "Not processed" in csv


def test_progress_callback_is_called_per_case():
    seen = []
    evaluate(CASES, fake_triage, dataset="d", engine="fake", progress=lambda i, n: seen.append((i, n)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_builtin_datasets_are_valid_and_replay_is_repeatable():
    sample, holdout = load_sample(), load_holdout()
    assert len(sample) >= 20 and len(holdout) >= 10
    assert not set(sample["request_id"]) & set(holdout["request_id"])
    assert not set(sample["request_text"]) & set(holdout["request_text"])

    def fn(i, t, q):
        return run_triage(i, t, q)

    a = evaluate(sample, fn, dataset="s", engine="rules").metrics
    b = evaluate(sample, fn, dataset="s", engine="rules").metrics
    assert a == b and a["n"] == len(sample) and a["failed"] == 0
