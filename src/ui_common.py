"""Streamlit helpers shared by all pages: engine selection, cached resources, formatting, small UI pieces.

Presentation only; business logic lives in the other src modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from . import config
from .data_io import load_holdout, load_sample
from .impact import ImpactAssumptions
from .storage import Storage
from .triage import RULES_ENGINE, Completer, TriageResult, llm_engine_label, make_openai_completer, run_triage

NAVY, MINT, MINT_DARK, GREY, RED, AMBER = "#0B1F3A", "#3DDBB0", "#0B8F7A", "#9AA8B6", "#B42318", "#B54708"

# Only our own class names and Streamlit's documented theme config are used; no internal DOM selectors.
_CSS = """
<style>
  .block-container { padding: 1.5rem 2.2rem 2rem 2.2rem; max-width: 100%; }
  /* Cards: keyed containers (documented st-key-* classes) and our own HTML cards */
  [class*="st-key-card_"], .ops-card { background: #FFFFFF; border: 1px solid #D5DCE6; border-radius: 12px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
  .ops-card { padding: 1rem 1.1rem; min-height: 6.4rem; box-sizing: border-box; }
  .ops-card.dark { background: #0B8F7A; border-color: #0B8F7A; }
  .ops-card.dark .ops-card-title, .ops-card.dark .ops-card-sub { color: #D9F2EC; }
  .ops-card.dark .ops-kpi { color: #FFFFFF; }
  .ops-card-title { font-size: 0.85rem; font-weight: 600; color: #475467; margin: 0 0 0.35rem 0; }
  .ops-kpi { font-size: clamp(1.4rem, 1.9vw, 2rem); font-weight: 650; letter-spacing: -0.02em; line-height: 1.15; color: #0B1F3A; margin: 0; }
  .ops-kpi, [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
  .ops-mail { background: #FFFFFF; border: 1px solid #D5DCE6; border-radius: 10px; padding: 0.9rem 1.1rem; margin-top: 0.6rem; }
  .ops-mail-head { display: flex; align-items: center; gap: 0.6rem; color: #0B1F3A; font-size: 1rem; }
  .ops-mail-meta { color: #667085; font-size: 0.8rem; margin: 0.2rem 0 0.6rem 0; }
  .ops-mail-body { color: #1D2939; font-size: 0.92rem; line-height: 1.5; margin: 0; }
  .ops-attn { background: #FFFFFF; border: 1px solid #D5DCE6; border-left: 4px solid #E8A33D; border-radius: 10px;
              padding: 0.8rem 1.1rem; margin: 0 0 1rem 0; }
  .ops-attn b { display: block; color: #0B1F3A; font-size: 0.95rem; margin-bottom: 0.3rem; }
  .ops-attn p { color: #344054; font-size: 0.88rem; line-height: 1.45; margin: 0.15rem 0; }
  .ops-kpi.muted { color: #98A2B3; font-size: 1.5rem; line-height: 2.4rem; }
  .ops-card-sub { font-size: 0.8rem; color: #475467; margin: 0.45rem 0 0 0; }
  .ops-chip { display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 0.1rem 0.45rem; border-radius: 6px;
              margin-right: 0.4rem; }
  .ops-chip.good { background: #E3F5EE; color: #0B5E4A; }
  .ops-chip.warn { background: #FFF1D6; color: #8A5A00; }
  .ops-chip.bad { background: #FDE8E6; color: #9B2C1F; }
  .ops-chip.neutral { background: #EEF1F5; color: #475467; }
  .ops-step-num { display: inline-block; width: 1.5rem; height: 1.5rem; line-height: 1.5rem; text-align: center;
                  border-radius: 50%; background: #0B1F3A; color: #fff; font-size: 0.8rem; font-weight: 600; margin-right: 0.5rem; }
  .ops-lead { font-size: 1.05rem; color: #344054; margin: 0 0 0.5rem 0; max-width: 46rem; }
  .ops-headline { padding: 0.25rem 0 0.75rem 0; }
  .ops-headline .label { font-size: 0.9rem; color: #475467; margin: 0; }
  .ops-headline .value { font-size: 2.8rem; font-weight: 650; letter-spacing: -0.02em; line-height: 1.15; margin: 0.1rem 0; }
  .ops-headline .value.pos { color: #0B7D63; }
  .ops-headline .value.neg { color: #B42318; }
  .ops-headline .value.zero { color: #0B1F3A; }
  .ops-headline .sub { font-size: 0.85rem; color: #475467; margin: 0; }
  .ops-section { font-size: 1rem; font-weight: 600; color: #0B1F3A; margin: 0.25rem 0 0.5rem 0; }
  .ops-hero { background: linear-gradient(135deg, #0B1F3A 0%, #12305A 60%, #0B6B58 130%); color: #FFFFFF; border-radius: 14px;
              padding: 1.2rem 1.4rem; min-height: 6.4rem; display: flex; justify-content: space-between; align-items: center;
              gap: 1rem; box-sizing: border-box; }
  .ops-hero p { margin: 0; }
  .ops-hero .t { font-size: 0.85rem; font-weight: 600; color: #B7C7DB; }
  .ops-hero .v { font-size: 2.4rem; font-weight: 650; letter-spacing: -0.02em; line-height: 1.2; margin: 0.15rem 0; }
  .ops-hero .s { font-size: 0.8rem; color: #B7C7DB; }
  .ops-ring { position: relative; flex: 0 0 5.5rem; width: 5.5rem; height: 5.5rem; border-radius: 50%; display: grid; place-items: center; }
  .ops-ring::before { content: ""; position: absolute; inset: 0.55rem; border-radius: 50%; background: #12305A; }
  .ops-ring span { position: relative; font-size: 0.8rem; font-weight: 600; color: #FFFFFF; }
  .ops-user { color: #E6EDF5; font-size: 0.85rem; line-height: 1.3; margin: 0.2rem 0 0.5rem 0; }
  .ops-user small { color: #9FB3C8; }
  .ops-signin-left { background: linear-gradient(160deg, #0B1F3A 0%, #12305A 65%, #0B6B58 140%); color: #FFFFFF; border-radius: 16px;
                     padding: 2.2rem; min-height: 30rem; box-sizing: border-box; }
  .ops-signin-left h2 { color: #FFFFFF; font-size: 1.9rem; line-height: 1.2; margin: 1.2rem 0 0.6rem 0; }
  .ops-signin-left p { color: #C9D6E5; margin: 0 0 1.2rem 0; }
  .ops-signin-left ul { list-style: none; padding: 0; margin: 0; }
  .ops-signin-left li { color: #E6EDF5; margin: 0.55rem 0; padding-left: 1.4rem; position: relative; font-size: 0.95rem; }
  .ops-signin-left li::before { content: ""; position: absolute; left: 0; top: 0.5rem; width: 0.55rem; height: 0.55rem;
                                border-radius: 50%; background: #3DDBB0; }
  .ops-title h1 { color: #0B1F3A; font-size: 1.6rem; font-weight: 650; margin: 0; padding: 0; letter-spacing: -0.01em; }
  .ops-rule { border-bottom: 1px solid #D5DCE6; margin: 0.2rem 0 1.2rem 0; }
  .ops-kpi { overflow-wrap: anywhere; }
  .ops-banner { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
                padding: 0 0 1rem 0; margin: 0 0 1.2rem 0; border-bottom: 1px solid #D5DCE6; }
  .ops-banner h1 { color: #0B1F3A; font-size: 1.6rem; font-weight: 650; margin: 0; padding: 0; letter-spacing: -0.01em; }
  .ops-banner p { color: #475467; font-size: 0.9rem; margin: 0.15rem 0 0 0; }
  .ops-avatar { display: flex; align-items: center; gap: 0.6rem; font-size: 0.85rem; color: #344054; }
  .ops-avatar b { display: grid; place-items: center; width: 2.1rem; height: 2.1rem; border-radius: 50%;
                  background: #0B8F7A; color: #fff; font-size: 0.8rem; }
  .ops-pill { display: inline-block; background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.22);
              color: #E6EDF5; font-size: 0.75rem; padding: 0.2rem 0.65rem; border-radius: 999px; }
</style>
"""


def inject_css() -> None:
    st.html(_CSS)


def _bootstrap(storage: Storage, items: list[dict]) -> None:
    """First launch only: run the real rule-based workflow on the sample queue and both labelled sets."""
    from .evaluation import evaluate

    results = [run_triage(i["request_id"], i["text"], i["requester"] or None) for i in items]
    run_id = storage.save_run("inbox", RULES_ENGINE, "sample", results=results)
    for res in results:
        storage.save_result(res, run_id, "Not processed" if res.error else "Ready for review")
    for name, data in (("Labelled sample set", sample_data()), ("Holdout set", holdout_data())):
        run = evaluate(data, lambda i, t, q: run_triage(i, t, q), dataset=name, engine=RULES_ENGINE)
        storage.save_run("replay", RULES_ENGINE, name, n_requests=run.metrics["n"],
                         n_flagged=run.metrics["review_flagged"], metrics=run.metrics)
    for res in results:  # automatic notices the workflow raises for urgent requests
        if res.priority == "Urgent":
            storage.send_message("OpsFlow workflow", res.team, f"Urgent {res.category.lower()} request {res.request_id}",
                                 f"{res.summary}\n\n{res.review_reason}", "Urgent", res.request_id)


def load_workspace() -> None:
    """Fill session state from the local database once per session: queue, results and review status."""
    if "queue" in st.session_state:
        return
    storage = get_storage()
    items = storage.load_queue()
    if not items:
        items = [{"request_id": r.request_id, "requester": r.requester, "text": r.request_text, "source": "sample"}
                 for r in sample_data().itertuples()]
        for item in items:
            storage.upsert_request(item)
    if config.autoseed() and not config.llm_available() and storage.runs(limit=1).empty:
        _bootstrap(storage, items)
    results, run_ids, status = storage.load_results()
    st.session_state.queue = items
    st.session_state.results = results
    st.session_state.run_ids = run_ids
    st.session_state.status = status
    st.session_state.selected_id = items[0]["request_id"]


def init_state() -> None:
    st.session_state.setdefault("assumptions", ImpactAssumptions())
    st.session_state.setdefault("replays", {})


# ---- resources --------------------------------------------------------------
@st.cache_resource
def get_storage() -> Storage:
    storage = Storage(config.db_path())
    try:  # the provided demo account; ignored if it already exists
        storage.create_user(config.DEMO_EMAIL, config.DEMO_NAME, config.DEMO_ROLE, config.DEMO_PASSWORD)
    except ValueError:
        pass
    for email, name, role in config.EXTRA_DEMO_USERS:
        try:
            storage.create_user(email, name, role, config.DEMO_PASSWORD)
        except ValueError:
            pass
    return storage


@st.cache_resource
def _completer(model: str) -> Optional[Completer]:
    key = config.llm_api_key()
    return make_openai_completer(key, model) if key else None


@st.cache_data
def sample_data() -> pd.DataFrame:
    return load_sample()


@st.cache_data
def holdout_data() -> pd.DataFrame:
    return load_holdout()


# ---- engine -----------------------------------------------------------------
@dataclass(frozen=True)
class Engine:
    mode: str  # "rules" or "llm"
    label: str
    ready: bool
    problem: str = ""


def current_engine() -> Engine:
    """No manual switch: LLM mode when an API key is configured, otherwise the rule-based demo."""
    if config.llm_available():
        return Engine("llm", llm_engine_label(config.llm_model()), True)
    return Engine("rules", RULES_ENGINE, True)


def make_triage_fn(engine: Engine):
    """Return fn(request_id, text, requester) -> TriageResult for the chosen engine."""
    model = config.llm_model()
    complete = _completer(model) if engine.mode == "llm" and engine.ready else None

    def fn(request_id: str, text: str, requester: Optional[str] = None) -> TriageResult:
        return run_triage(request_id, text, requester, mode=engine.mode, complete=complete, model=model)  # type: ignore[arg-type]

    return fn


def engine_short(engine_label: str) -> str:
    return "Rule-based" if engine_label.startswith("Rule") else "LLM"


# ---- small UI pieces ----------------------------------------------------------
def section_label(text: str) -> None:
    st.markdown(f'<p class="ops-section">{text}</p>', unsafe_allow_html=True)


def card(name: str):
    """A white bordered card for charts and tables."""
    return st.container(border=True, key=f"card_{name}")


_ICONS = {
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "flag": '<path d="M4 22V4"/><path d="M4 4h13l-2 4 2 4H4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
}
_ICON_FOR = {"Requests processed": "inbox", "Routing accuracy": "target", "Needing human review": "flag",
             "Estimated time saved": "clock"}


def kpi_card(title: str, value: str, sub: str = "", chip: str = "", tone: str = "neutral") -> None:
    """KPI card in plain HTML so long labels wrap instead of being truncated."""
    muted = " muted" if value in ("-", "Not evaluated") else ""
    chip_html = f'<span class="ops-chip {tone}">{escape(chip)}</span>' if chip else ""
    icon = _ICONS[_ICON_FOR.get(title, "chart")]
    svg = (f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon}</svg>')
    st.html(f'<div class="ops-card {tone}"><p class="ops-card-title">{escape(title)}</p>'
            f'<p class="ops-kpi{muted}">{escape(value)}</p>'
            f'<p class="ops-card-sub">{chip_html}{escape(sub)}</p></div>')


def attention(title: str, items: list[str]) -> None:
    """Compact call-out for things a person should look at."""
    rows = "".join(f"<p>{escape(i)}</p>" for i in items)
    st.html(f'<div class="ops-attn" role="status"><b>{escape(title)}</b>{rows}</div>')


def kpi_cards(items: list[tuple], per_row: int = 4) -> None:
    """items: (title, value, sub[, chip, tone]). Rows wrap; columns stack on narrow screens."""
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        for col, item in zip(st.columns(per_row, gap="small"), row):
            with col:
                kpi_card(*item)


def hero_card(title: str, value: str, sub: str, fraction: Optional[float]) -> None:
    ring = (f"conic-gradient(#3DDBB0 {fraction * 360:.0f}deg, rgba(255,255,255,0.18) 0)" if fraction is not None
            else "rgba(255,255,255,0.18)")
    ring_text = f"{fraction * 100:.0f}%" if fraction is not None else "-"
    st.html(f'<div class="ops-hero"><div><p class="t">{escape(title)}</p><p class="v">{escape(value)}</p>'
            f'<p class="s">{escape(sub)}</p></div><div class="ops-ring" style="background:{ring}"><span>{ring_text}</span></div></div>')


ROLES = ["Operations reviewer", "Operations lead", "AI analyst"]
MAX_FAILED_SIGNINS = 5


def signin_page() -> None:
    """Sign in with the provided demo account (prefilled). Accounts live in this machine's SQLite file."""
    storage = get_storage()
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        st.html('<div class="ops-signin-left" style="min-height:0;padding:1.4rem 1.6rem;margin-top:3rem">'
                '<h2 style="margin:0">OpsFlow Lab</h2><p style="margin:0.3rem 0 0 0">From manual work to verified AI.</p></div>')
        with st.container(border=True, key="card_signin"):
            st.subheader("Sign in")
            with st.form("signin", border=False):
                email = st.text_input("Email", value=config.DEMO_EMAIL)
                password = st.text_input("Password", type="password", value=config.DEMO_PASSWORD)
                go = st.form_submit_button("Sign in", type="primary", width="stretch")
        if go:
            failed = st.session_state.get("failed_signins", 0)
            if failed >= MAX_FAILED_SIGNINS:
                st.error("Too many failed attempts. Reload the page to try again.")
            else:
                user = storage.authenticate(email, password)
                if user:
                    st.session_state.pop("failed_signins", None)
                    st.session_state["user"] = user
                    st.rerun()
                st.session_state["failed_signins"] = failed + 1
                st.error("Email or password is incorrect.")


def triage_fn_for(mode: str):
    """Triage function for a specific engine, or None when it is unavailable (LLM without a key)."""
    if mode == "llm" and not config.llm_available():
        return None
    return make_triage_fn(Engine(mode, "", True))


def notifications() -> list[str]:
    """Things that need attention, derived from the current queue and stored messages."""
    results, status = st.session_state.get("results", {}), st.session_state.get("status", {})
    waiting = [r for rid, r in results.items() if status.get(rid) == "Ready for review"]
    out = []
    urgent = sum(r.priority == "Urgent" for r in waiting)
    flagged = sum(r.needs_review for r in waiting)
    if urgent:
        out.append(f"{urgent} urgent request(s) waiting for review")
    if flagged:
        out.append(f"{flagged} flagged request(s) need a decision")
    try:
        urgent_msgs = get_storage().messages()
        urgent_msgs = urgent_msgs[urgent_msgs["priority"] == "Urgent"]
        if len(urgent_msgs):
            out.append(f"{len(urgent_msgs)} urgent message(s) in the feed")
    except Exception:  # notifications must never break a page
        pass
    return out


def sidebar_user() -> None:
    user = st.session_state["user"]
    with st.sidebar:
        st.markdown(f'<p class="ops-user"><b>{escape(user["name"])}</b><br><small>{escape(user["role"])}</small></p>',
                    unsafe_allow_html=True)
        if st.button("Sign out", icon=":material/logout:", key="signout"):
            del st.session_state["user"]
            st.rerun()


def page_header(title: str, lead: str, engine: "Engine") -> None:
    """Top bar: page title on the left, notifications and the signed-in user on the right."""
    user = st.session_state.get("user", {"name": "?"})
    initials = "".join(w[0] for w in user["name"].split()[:2]).upper()
    left, bell, who = st.columns([5, 2, 2], vertical_alignment="center")
    left.html(f'<div class="ops-title"><h1>{escape(title)}</h1></div>')
    items = notifications()
    with bell.popover(f"Notifications ({len(items)})" if items else "Notifications", icon=":material/notifications:",
                      width="stretch"):
        if items:
            for text in items:
                st.markdown(f"- {text}")
        else:
            st.write("Nothing needs your attention.")
    who.html(f'<div class="ops-avatar"><b>{escape(initials)}</b>{escape(user["name"])}</div>')
    st.html('<div class="ops-rule"></div>')


def engine_badge(engine: Engine) -> None:
    st.badge(engine.label, icon=":material/memory:" if engine.mode == "llm" else ":material/rule:",
             color="blue" if engine.mode == "llm" else "gray")


PRIORITY_COLOR = {"Urgent": "red", "High": "orange", "Normal": "gray", "Low": "green"}


def priority_badge(priority: str) -> None:
    st.badge(priority, color=PRIORITY_COLOR.get(priority, "gray"))


# ---- formatting -------------------------------------------------------------
def fmt_pct(value: Optional[float], digits: int = 0) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}€{abs(value):,.2f}" if abs(value) < 100 else f"{sign}€{abs(value):,.0f}"


def fmt_hours(value: float) -> str:
    return f"{value:,.1f} h"
