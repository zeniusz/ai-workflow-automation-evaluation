import json

import pytest

from src.triage import (RULES_ENGINE, SAFETY_TEAM, ExtractedInfo, apply_business_rules, parse_llm_output, run_triage,
                        triage_rules, validate_request_text)


@pytest.mark.parametrize(
    "text, category, team",
    [
        ("The infusion pump in Exam Room 4 keeps beeping an occlusion alarm.", "Equipment", "Biomedical Engineering"),
        ("Water is leaking from the ceiling above the waiting room.", "Facilities", "Facilities Maintenance"),
        ("Please reorder 10 boxes of nitrile gloves for the Pharmacy.", "Supplies", "Supply & Procurement"),
        ("I am locked out of my account after changing my password. Ext 2210.", "IT", "IT Service Desk"),
    ],
)
def test_known_examples_route_correctly(text, category, team):
    result = triage_rules("T-1", text)
    assert (result.category, result.team) == (category, team)
    assert result.engine == RULES_ENGINE


def test_rules_are_deterministic():
    text = "The autoclave in the sterilisation room failed its cycle twice. Tag BM-0932."
    first, second = triage_rules("T-1", text), triage_rules("T-1", text)
    assert first.model_dump(exclude={"processed_at"}) == second.model_dump(exclude={"processed_at"})


def test_extraction():
    r = triage_rules("T-1", "Please order 5 packs of gauze for Exam Room 2. Tag BM-1180, ext 3120.")
    assert r.extracted.location == "Exam Room 2"
    assert r.extracted.quantity == "5 packs"
    assert r.extracted.asset_tag == "BM-1180"
    assert r.extracted.contact == "ext 3120"


def test_missing_fields_are_detected():
    r = triage_rules("T-1", "The infusion pump keeps beeping an alarm.")
    assert "location" in r.missing_information
    assert r.needs_review
    assert "missing information" in r.review_reason.lower()
    r = triage_rules("T-2", "We are running low on gloves.")
    assert "quantity" in r.missing_information


def test_complete_routine_request_is_not_flagged():
    r = triage_rules("T-1", "Please reorder 10 boxes of nitrile gloves for the Pharmacy.")
    assert not r.missing_information and not r.needs_review


def test_urgent_and_hazard_escalate_to_review():
    r = triage_rules("T-1", "Strong smell of gas near the staff kitchen. Send someone immediately.")
    assert r.priority == "Urgent" and r.team == SAFETY_TEAM and r.needs_review
    assert "safety" in r.review_reason.lower()


def test_ambiguous_request_goes_to_exception_queue():
    r = triage_rules("T-1", "Can someone help with the thing we discussed yesterday?")
    assert r.category == "Other" and r.team == "Operations Triage"
    assert r.needs_review and r.confidence == "low"


def test_not_urgent_is_not_treated_as_urgent():
    r = triage_rules("T-1", "The paint in the corridor is peeling. Not urgent, whenever the team has time.")
    assert r.priority == "Low"


@pytest.mark.parametrize("bad", ["", "   ", None, 42, "x" * 2100], ids=["empty", "blank", "none", "int", "too-long"])
def test_invalid_input_becomes_flagged_failure(bad):
    r = run_triage("T-1", bad)
    assert r.error and r.needs_review and r.summary == "Not processed"


def test_validate_request_text_strips():
    assert validate_request_text("  hello  ") == "hello"


# ---- LLM mode -------------------------------------------------------------
GOOD = {
    "summary": "Printer in Radiology is down.", "category": "it", "priority": "normal",
    "extracted": {"location": "Radiology", "item": "printer", "quantity": 3},
    "missing_information": [], "suggested_response": "Hello, we have logged this.",
    "explanation": "Printer fault.", "confidence": "high", "ignored_extra_key": "x",
}


def test_parse_llm_output_accepts_good_json_and_normalises_case():
    draft = parse_llm_output("```json\n" + json.dumps(GOOD) + "\n```")
    assert draft.category == "IT" and draft.priority == "Normal"
    assert draft.extracted.quantity == "3"


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "[1, 2]", json.dumps({**GOOD, "category": "Plumbing"}),
     json.dumps({k: v for k, v in GOOD.items() if k != "summary"}), json.dumps({**GOOD, "priority": 3})],
)
def test_malformed_model_output_raises_value_error(raw):
    with pytest.raises(ValueError):
        parse_llm_output(raw)


def test_malformed_model_output_is_flagged_not_crashed():
    r = run_triage("T-1", "The printer is down.", mode="llm", complete=lambda t, q: "I cannot help", model="m")
    assert r.error and r.needs_review and "valid JSON" in r.error
    assert r.engine == "LLM (m)"


def test_api_failure_is_flagged_without_leaking_text():
    def boom(text, requester):
        raise ConnectionError("secret sk-123 request text here")

    r = run_triage("T-1", "The printer is down.", mode="llm", complete=boom, model="m")
    assert r.error == "ConnectionError while calling the model"
    assert "sk-123" not in r.error and r.needs_review


def test_llm_mode_without_completer_fails_gracefully():
    r = run_triage("T-1", "The printer is down.", mode="llm", complete=None, model="m")
    assert r.error and r.needs_review


def test_business_rules_override_model_after_the_fact():
    # The model calls a gas leak "Normal"; deterministic rules still escalate and re-route.
    raw = json.dumps({**GOOD, "category": "Facilities", "priority": "Normal", "confidence": "high"})
    r = run_triage("T-1", "Gas leak in the kitchen on Floor 1, please come immediately.",
                   mode="llm", complete=lambda t, q: raw, model="m")
    assert r.priority == "Urgent" and r.team == SAFETY_TEAM and r.needs_review


def test_low_model_confidence_triggers_review():
    raw = json.dumps({**GOOD, "confidence": "low"})
    r = run_triage("T-1", "The printer in Radiology is down, ext 3000.", mode="llm", complete=lambda t, q: raw, model="m")
    assert r.needs_review and "low confidence" in r.review_reason.lower()


def test_model_missing_info_is_merged_with_required_checks():
    out = apply_business_rules("The pump is broken, please fix", "Equipment", "High", ExtractedInfo(item="pump"),
                               model_missing=["asset tag"])
    assert out.missing == ["location", "asset tag"] and out.needs_review
