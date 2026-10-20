import pytest

from src.config import MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS
from src.data_io import DataValidationError, load_labelled_csv, load_requests_csv, template_csv


def test_valid_upload_generates_missing_ids():
    frame = load_requests_csv(b"request_text\nPrinter broken\nOrder gloves\n")
    assert list(frame["request_id"]) == ["UP-0001", "UP-0002"]
    assert list(frame.columns) == ["request_id", "requester", "request_text"]


def test_template_round_trips():
    assert len(load_requests_csv(template_csv())) == 2


def test_column_names_are_case_and_space_insensitive():
    assert len(load_requests_csv(b" Request_Text ,Requester\nhello there,Ann\n")) == 1


@pytest.mark.parametrize(
    "data, fragment",
    [
        (b"", "empty"),
        (b"request_text\n", "no data rows"),
        (b"text\nhello\n", "Missing required column"),
        (b"request_text,other\n   ,x\n", "Empty request_text"),
        (b"request_id,request_text\nA,one\nA,two\n", "Duplicate request_id"),
        (b"request_text\n" + b"x" * 2100 + b"\n", "longer than"),
        (b"\xff\xfe\x00bad", "UTF-8"),
    ],
    ids=["empty-file", "header-only", "missing-column", "blank-text", "duplicate-ids", "text-too-long", "not-utf8"],
)
def test_invalid_uploads_give_useful_errors(data, fragment):
    with pytest.raises(DataValidationError, match=fragment):
        load_requests_csv(data)


def test_labelled_csv_rejects_unknown_labels(tmp_path):
    path = tmp_path / "l.csv"
    path.write_text("request_text,expected_category,expected_priority,expected_team\n"
                    "x,Plumbing,High,IT Service Desk\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="expected_category"):
        load_labelled_csv(path)


def test_labelled_csv_requires_label_columns(tmp_path):
    path = tmp_path / "l.csv"
    path.write_text("request_text\nx\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="Missing required column"):
        load_labelled_csv(path)


def test_size_and_row_limits_are_enforced():
    with pytest.raises(DataValidationError, match="larger than"):
        load_requests_csv(b"a" * (MAX_UPLOAD_BYTES + 1))
    with pytest.raises(DataValidationError, match="limit"):
        load_requests_csv(b"request_text\n" + b"row\n" * (MAX_UPLOAD_ROWS + 1))
