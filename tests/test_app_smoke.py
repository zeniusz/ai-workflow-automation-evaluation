"""Headless smoke tests: every page renders, and the core inbox flow works without an API key."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.triage import make_openai_completer

APP = Path(__file__).resolve().parent.parent / "app.py"
PAGES = ["app_pages/inbox.py", "app_pages/review.py", "app_pages/messages.py", "app_pages/replay.py", "app_pages/ai.py", "app_pages/impact.py", "app_pages/team.py"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSFLOW_DB_PATH", str(tmp_path / "smoke.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPSFLOW_AUTOSEED", "0")
    from src import ui_common

    ui_common.get_storage.clear()  # each test gets its own database
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["user"] = {"name": "Test User", "role": "Operations reviewer"}
    return at.run()


def test_signin_is_prefilled_rejects_bad_password_and_accepts_demo_account(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSFLOW_DB_PATH", str(tmp_path / "s.db"))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception and "user" not in at.session_state
    assert at.text_input[0].value == "demo@opsflow.lab" and at.text_input[1].value
    good = at.text_input[1].value
    at.text_input[1].set_value("wrong-password")
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert "incorrect" in at.error[0].value and "user" not in at.session_state
    at.text_input[1].set_value(good)
    next(b for b in at.button if b.label == "Sign in").click().run()
    assert at.session_state["user"]["email"] == "demo@opsflow.lab" and not at.exception


def test_every_page_renders_without_exceptions(app):
    assert not app.exception
    for page in PAGES:
        app.switch_page(page).run()
        assert not app.exception, page


def test_queue_processing_and_approval_flow(app):
    app.switch_page("app_pages/inbox.py").run()
    assert len(app.session_state["queue"]) == 30 and not app.session_state["results"]
    next(b for b in app.button if b.key == "process_all").click().run()
    assert not app.exception and len(app.session_state["results"]) == 30
    app.switch_page("app_pages/review.py").run()
    save = next(b for b in app.button if b.key and b.key.startswith("save_"))
    save.click().run()
    assert not app.exception and "Approved" in app.session_state["status"].values()


def test_engine_is_chosen_from_api_key(app, monkeypatch):
    from src import ui_common

    assert ui_common.current_engine().mode == "rules"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPSFLOW_AUTOSEED", "0")
    engine = ui_common.current_engine()
    assert engine.mode == "llm" and engine.ready


def test_openai_completer_builds_without_network():
    assert callable(make_openai_completer("sk-test-not-real", "some-model"))


def test_process_single_request_and_ai_check_without_key(app):
    app.switch_page("app_pages/inbox.py").run()
    next(b for b in app.button if b.key == "proc_S-001").click().run()
    assert not app.exception and list(app.session_state["results"]) == ["S-001"]
    assert any("not connected" in i.value for i in app.info)


def test_overview_renders_after_inbox_runs_and_reviews(app):
    app.switch_page("app_pages/inbox.py").run()
    next(b for b in app.button if b.key == "process_all").click().run()
    app.switch_page("app_pages/review.py").run()
    next(b for b in app.button if b.key and b.key.startswith("save_")).click().run()
    assert "Approved" in app.session_state["status"].values()
    app.switch_page("app_pages/overview.py").run()
    assert not app.exception


def test_ai_page_without_key_runs_rules_only_and_disables_comparison(app):
    app.switch_page("app_pages/ai.py").run()
    assert not app.exception
    assert next(b for b in app.button if b.key == "ai_compare").disabled
    app.text_area(key="ai_text").set_value("The printer in Radiology is not working. Ext 3120.").run()
    next(b for b in app.button if b.key == "ai_run_one").click().run()
    assert not app.exception and app.session_state["ai_one"]["llm"] is None
    assert app.session_state["ai_one"]["rules"].category == "IT"


def test_ai_comparison_with_a_stubbed_model(tmp_path, monkeypatch):
    import json

    from src import ui_common

    monkeypatch.setenv("OPSFLOW_DB_PATH", str(tmp_path / "c.db"))
    ui_common.get_storage.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    stub = json.dumps({"summary": "s", "category": "IT", "priority": "Normal", "extracted": {"location": "Lab"},
                       "missing_information": [], "suggested_response": "r", "explanation": "e", "confidence": "high"})
    monkeypatch.setattr(ui_common, "make_openai_completer", lambda key, model: (lambda text, requester: stub))
    ui_common._completer.clear()
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["user"] = {"name": "T", "email": "t@x.y", "role": "r", "onboarded": True}
    at.run().switch_page("app_pages/ai.py").run()
    next(b for b in at.button if b.key == "ai_compare").click().run()
    assert not at.exception and set(at.session_state["ai_runs"]["Holdout set"]) == {"rules", "llm"}
    ui_common._completer.clear()


def test_message_can_be_drafted_from_a_processed_request_and_sent(app):
    app.switch_page("app_pages/inbox.py").run()
    next(b for b in app.button if b.key == "process_all").click().run()
    app.switch_page("app_pages/messages.py").run()
    app.selectbox(key="msg_request").select("S-005").run()
    assert app.session_state["msg_to"] == "Safety & Compliance" and "S-005" in app.session_state["msg_subject"]
    next(b for b in app.button if b.key == "msg_send").click().run()
    assert not app.exception and len(app.session_state["results"]) == 30


def test_first_launch_fills_every_page_with_real_output(tmp_path, monkeypatch):
    from src import ui_common

    monkeypatch.setenv("OPSFLOW_DB_PATH", str(tmp_path / "seed.db"))
    monkeypatch.setenv("OPSFLOW_AUTOSEED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ui_common.get_storage.clear()
    at = AppTest.from_file(str(APP), default_timeout=90)
    at.session_state["user"] = {"name": "T", "email": "t@x.y", "role": "r", "onboarded": True}
    at.run()
    assert len(at.session_state["results"]) == 30
    storage = ui_common.get_storage()
    assert len(storage.runs(limit=50)) == 9 and len(storage.months()) == 3 and not storage.messages().empty
    for page in PAGES:
        at.switch_page(page).run()
        assert not at.exception, page
    ui_common.get_storage.clear()
