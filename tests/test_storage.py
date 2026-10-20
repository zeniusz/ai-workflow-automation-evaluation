import pytest

from src.storage import Storage
from src.triage import triage_rules


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "test.db")


@pytest.fixture
def result():
    return triage_rules("R-1", "The printer in Radiology is not working. Contact: a@b.example")


def final_of(result, **changes):
    final = {"category": result.category, "priority": result.priority, "team": result.team}
    return {**final, **changes}


def test_unchanged_review_is_saved_as_approved(storage, result):
    run_id = storage.save_run("inbox", result.engine, "sample", results=[result])
    storage.save_review(result, final_of(result), run_id=run_id, note="  looks right ")
    row = storage.reviews_for("R-1").iloc[0]
    assert row["decision"] == "approved" and row["fields_changed"] == "" and row["note"] == "looks right"
    assert row["run_id"] == run_id and row["reviewed_at"]


def test_changed_review_is_saved_as_corrected_with_fields(storage, result):
    storage.save_review(result, final_of(result, category="Equipment", team="Biomedical Engineering"))
    row = storage.reviews_for("R-1").iloc[0]
    assert row["decision"] == "corrected" and row["fields_changed"] == "category,team"
    assert (row["proposed_category"], row["final_category"]) == ("IT", "Equipment")
    summary = storage.review_summary()
    assert summary["total"] == 1 and summary["corrected"] == 1 and summary["acceptance_rate"] == 0
    assert summary["corrections_by_field"] == {"category": 1, "priority": 0, "team": 1}


def test_invalid_values_are_rejected(storage, result):
    with pytest.raises(ValueError):
        storage.save_review(result, final_of(result, priority="Whenever"))
    assert storage.reviews().empty


def test_data_survives_reopening_the_database(tmp_path, result):
    Storage(tmp_path / "x.db").save_review(result, final_of(result))
    assert len(Storage(tmp_path / "x.db").reviews()) == 1


def test_runs_have_unique_ids_and_request_text_is_not_stored(storage, result):
    a = storage.save_run("inbox", "e", "sample", results=[result])
    b = storage.save_run("inbox", "e", "sample", results=[result])
    assert a != b
    processed = storage.processed()
    assert len(processed) == 2 and "request_text" not in processed.columns


def test_latest_replay_round_trips_metrics(storage):
    assert storage.latest_replay() is None
    storage.save_run("replay", "rules", "holdout", n_requests=12, n_flagged=3,
                     metrics={"routing_accuracy": 0.9, "n": 12})
    latest = storage.latest_replay()
    assert latest["metrics"]["routing_accuracy"] == 0.9 and latest["n_flagged"] == 3


def test_empty_database_summary(storage):
    summary = storage.review_summary()
    assert summary["total"] == 0 and summary["acceptance_rate"] is None
    assert storage.runs().empty


def test_bad_run_type_rejected(storage):
    with pytest.raises(ValueError):
        storage.save_run("other", "e", "d")
