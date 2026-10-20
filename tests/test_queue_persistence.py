import pytest

from src.storage import Storage
from src.triage import triage_rules


def test_queue_results_and_status_survive_reopening(tmp_path):
    db = tmp_path / "q.db"
    first = Storage(db)
    item = {"request_id": "S-1", "requester": "Ann", "text": "The printer in Radiology is not working.", "source": "sample"}
    first.upsert_request(item)
    res = triage_rules("S-1", item["text"])
    first.save_result(res, "run_x", "Ready for review")
    first.set_status("S-1", "Approved")

    again = Storage(db)
    assert again.load_queue() == [item]
    results, run_ids, status = again.load_results()
    assert results["S-1"].category == res.category and run_ids["S-1"] == "run_x" and status["S-1"] == "Approved"


def test_upsert_request_does_not_overwrite(tmp_path):
    s = Storage(tmp_path / "q.db")
    s.upsert_request({"request_id": "A", "requester": "", "text": "first", "source": "manual"})
    s.upsert_request({"request_id": "A", "requester": "", "text": "second", "source": "manual"})
    assert [i["text"] for i in s.load_queue()] == ["first"]
