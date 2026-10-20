import pandas as pd
import streamlit as st

from src import ui_common as ui
from src.storage import REVIEW_FIELDS
from src.triage import CATEGORIES, PRIORITIES, TEAMS

storage = ui.get_storage()
engine = ui.current_engine()
queue = st.session_state.get("queue", [])
results = st.session_state.get("results", {})
status = st.session_state.get("status", {})
run_ids = st.session_state.get("run_ids", {})
by_id = {i["request_id"]: i for i in queue}

ui.page_header("Human review", "Check each proposal, then approve it or change it.", engine)

waiting = [rid for rid, st_ in status.items() if st_ == "Ready for review" and rid in by_id]
# Flagged requests first, then the rest in queue order.
waiting.sort(key=lambda rid: (not results[rid].needs_review, list(by_id).index(rid)))
done = sum(1 for v in status.values() if v in ("Approved", "Corrected"))

c1, c2 = st.columns([1, 3])
c1.metric("Waiting for you", len(waiting))
c2.metric("Reviewed", done)

if not waiting:
    if not results:
        st.write("Process requests in the inbox first.")
        if st.button("Go to Request inbox", icon=":material/inbox:"):
            st.switch_page("app_pages/inbox.py")
    else:
        st.success("Everything has been reviewed.", icon=":material/check_circle:")
else:
    rid = st.session_state.pop("review_id", None) or st.session_state.get("review_current")
    if rid not in waiting:
        rid = waiting[0]
    st.session_state["review_current"] = rid
    res, item = results[rid], by_id[rid]

    list_col, work_col = st.columns([2, 3], gap="small")
    with list_col, ui.card("review_list"):
        st.markdown("**Waiting for review**")
        table = pd.DataFrame([{"Request": r, "Priority": results[r].priority,
                               "Flag": "Needs attention" if results[r].needs_review else ""} for r in waiting])
        event = st.dataframe(table, hide_index=True, width="stretch", height=420, on_select="rerun",
                             selection_mode="single-row", key="review_table")
        if event.selection.rows:
            rid = table.iloc[event.selection.rows[0]]["Request"]
            st.session_state["review_current"] = rid
            res, item = results[rid], by_id[rid]

    with work_col, ui.card("review_work"):
        st.markdown(f"**{rid}**")
        st.write(item["text"])
        if res.needs_review:
            st.warning(res.review_reason, icon=":material/flag:", title="Why this needs your attention")
        st.markdown("**Proposed by the workflow**")
        chips = st.container(horizontal=True)
        chips.badge(res.category, color="blue")
        with chips:
            ui.priority_badge(res.priority)
        chips.badge(res.team, color="violet")
        if res.missing_information:
            st.caption("Missing: " + ", ".join(res.missing_information))

        st.markdown("**Your decision**")
        key = f"{run_ids.get(rid)}_{rid}"
        d1, d2, d3 = st.columns(3)
        final = {
            "category": d1.selectbox("Category", CATEGORIES, index=CATEGORIES.index(res.category), key=f"cat_{key}"),
            "priority": d2.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(res.priority), key=f"pri_{key}"),
            "team": d3.selectbox("Assigned team", TEAMS, index=TEAMS.index(res.team), key=f"team_{key}"),
        }
        note = st.text_input("Note (optional)", max_chars=200, key=f"note_{key}")
        changed = [f for f in REVIEW_FIELDS if final[f] != getattr(res, f)]
        label = f"Save correction ({', '.join(changed)})" if changed else "Approve"
        if st.button(label, type="primary", key=f"save_{key}", icon=":material/check:"):
            storage.save_review(res, final, run_id=run_ids.get(rid), note=note,
                                reviewer=st.session_state["user"]["name"])
            status[rid] = "Corrected" if changed else "Approved"
            storage.set_status(rid, status[rid])
            st.session_state.pop("review_current", None)
            st.session_state.flash = f"{rid} {'corrected' if changed else 'approved'}."
            st.rerun()

if st.session_state.get("flash"):
    st.toast(st.session_state.flash, icon=":material/check:")
    st.session_state.flash = None

history = storage.reviews(limit=10)
if not history.empty:
    st.markdown("**Recent decisions**")
    st.dataframe(history[["reviewed_at", "request_id", "reviewer", "decision", "final_category", "final_priority", "final_team"]],
                 hide_index=True, width="stretch", column_config={
                     "reviewed_at": "Time (UTC)", "request_id": "Request", "reviewer": "By", "decision": "Decision",
                     "final_category": "Category", "final_priority": "Priority", "final_team": "Team"})
