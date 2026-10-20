import pytest

from src.storage import Storage


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "u.db")


def test_account_roundtrip_and_password_not_stored_in_clear(storage, tmp_path):
    storage.create_user("Alex@Example.com", "Alex", "AI analyst", "correct horse battery")
    user = storage.authenticate("alex@example.com", "correct horse battery")
    assert user["name"] == "Alex" and user["onboarded"] is False
    assert storage.authenticate("alex@example.com", "wrong password") is None
    assert storage.authenticate("nobody@example.com", "correct horse battery") is None
    assert b"correct horse battery" not in (tmp_path / "u.db").read_bytes()


@pytest.mark.parametrize("email, name, password, fragment", [
    ("not-an-email", "A", "longenough1", "valid email"),
    ("a@b.co", "  ", "longenough1", "name"),
    ("a@b.co", "A", "short", "at least"),
])
def test_invalid_signups_are_rejected(storage, email, name, password, fragment):
    with pytest.raises(ValueError, match=fragment):
        storage.create_user(email, name, "AI analyst", password)


def test_duplicate_email_rejected_and_onboarding_flag_persists(storage):
    storage.create_user("a@b.co", "A", "AI analyst", "longenough1")
    with pytest.raises(ValueError, match="already exists"):
        storage.create_user("A@B.CO", "Other", "AI analyst", "longenough2")
    storage.mark_onboarded("a@b.co")
    assert storage.authenticate("a@b.co", "longenough1")["onboarded"] is True


def test_users_overview_counts_reviews_per_person(storage):
    from src.triage import triage_rules

    storage.create_user("a@b.co", "Ann", "AI analyst", "longenough1")
    storage.create_user("c@d.co", "Cy", "AI analyst", "longenough1")
    res = triage_rules("R-1", "The printer in Radiology is not working. Ext 3120.")
    final = {"category": res.category, "priority": res.priority, "team": res.team}
    storage.save_review(res, final, reviewer="Ann")
    overview = storage.users_overview().set_index("name")
    assert overview.loc["Ann", "reviews"] == 1 and overview.loc["Ann", "approved"] == 1
    assert overview.loc["Cy", "reviews"] == 0
