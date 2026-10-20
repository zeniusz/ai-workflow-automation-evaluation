import pytest

from src.storage import Storage


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "m.db")


def test_send_and_filter_messages_by_team(storage):
    storage.send_message("Ann", "IT Service Desk", "Printer down", "Radiology printer is out.", "Urgent", "S-008")
    storage.send_message("Ann", "All teams", "Maintenance window", "Friday 18:00.")
    storage.send_message("Ann", "Facilities Maintenance", "Leak", "Ceiling leak.")
    it = storage.messages("IT Service Desk")
    assert set(it["subject"]) == {"Printer down", "Maintenance window"}
    assert len(storage.messages()) == 3 and storage.messages().iloc[0]["subject"] == "Leak"
    assert it.set_index("subject").loc["Printer down", "request_id"] == "S-008"


@pytest.mark.parametrize("recipient, subject, body, priority", [
    ("Nobody", "s", "b", "Normal"), ("All teams", " ", "b", "Normal"),
    ("All teams", "s", "", "Normal"), ("All teams", "s", "b", "Whenever"),
])
def test_invalid_messages_rejected(storage, recipient, subject, body, priority):
    with pytest.raises(ValueError):
        storage.send_message("Ann", recipient, subject, body, priority)
    assert storage.messages().empty
