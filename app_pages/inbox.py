import uuid

import pandas as pd
import streamlit as st

from src import ui_common as ui
from src.config import MAX_REQUEST_CHARS, MAX_UPLOAD_BYTES, MAX_UPLOAD_ROWS
from src.data_io import DataValidationError, load_requests_csv, template_csv
from src.triage import TriageResult, validate_request_text

storage = ui.get_storage()
engine = ui.current_engine()
sample = ui.sample_data()

st.session_state.setdefault("results", {})   # request_id -> TriageResult
st.session_state.setdefault("status", {})    # request_id -> Ready for review / Approved / Corrected / Not processed
st.session_state.setdefault("run_ids", {})   # request_id -> run id that produced the result
st.session_state.setdefault("flash", None)

STATUS_COLOR = {"Not processed": "gray", "Ready for review": "orange", "Approved": "green", "Corrected": "blue"}


def process(items: list[dict]) -> None:
    """Run the engine once per request and keep the results (no repeat calls on rerun)."""
    fn = ui.make_triage_fn(engine)
    done: list[TriageResult] = []
    with st.spinner(f"Processing {len(items)} request(s)..."):
        for item in items:
            res = fn(item["request_id"], item["text"], item["requester"] or None)
            st.session_state.results[item["request_id"]] = res
            st.session_state.status[item["request_id"]] = "Not processed" if res.error else "Ready for review"
            done.append(res)
    run_id = storage.save_run("inbox", engine.label, items[0]["source"] if len({i["source"] for i in items}) == 1 else "mixed",
                              results=done)
    for item in items:
        st.session_state.run_ids[item["request_id"]] = run_id
        storage.save_result(st.session_state.results[item["request_id"]], run_id,
                            st.session_state.status[item["request_id"]])
    failed = sum(bool(r.error) for r in done)
    st.session_state.flash = (f"Processed {len(done) - failed} of {len(done)}." + (f" {failed} failed." if failed else ""))


def add_to_queue(new_items: list[dict]) -> None:
    st.session_state.queue = new_items + st.session_state.queue
    for item in new_items:
        storage.upsert_request(item)
    st.session_state.selected_id = new_items[0]["request_id"]


@st.dialog("New request")
def new_request_dialog() -> None:
    text = st.text_area("Request text", max_chars=MAX_REQUEST_CHARS, height=140,
                        placeholder="e.g. The autoclave in the sterilisation room failed its cycle twice. Tag BM-0932.")
    requester = st.text_input("Requester (optional)")
    if st.button("Add and process", type="primary"):
        try:
            clean = validate_request_text(text)
        except ValueError as exc:
            st.error(str(exc))
            return
        item = {"request_id": f"MAN-{uuid.uuid4().hex[:8]}", "requester": requester.strip(), "text": clean, "source": "manual"}
        add_to_queue([item])
        process([item])
        st.rerun()


@st.dialog("Upload CSV")
def upload_dialog() -> None:
    st.caption(f"Needs a request_text column. Up to {MAX_UPLOAD_ROWS} rows, {MAX_UPLOAD_BYTES // 1000} KB.")
    st.download_button("Download template", template_csv(), "opsflow_request_template.csv", "text/csv",
                       icon=":material/download:")
    upload = st.file_uploader("CSV file", type="csv", label_visibility="collapsed")
    if upload is None:
        return
    try:
        frame = load_requests_csv(upload.getvalue())
    except DataValidationError as exc:
        st.error(str(exc))
        return
    existing = {i["request_id"] for i in st.session_state.queue}
    clash = existing & set(frame["request_id"])
    if clash:
        st.error("These request_id values are already in the queue: " + ", ".join(sorted(clash)[:5]) + ".")
        return
    st.success(f"{len(frame)} request(s) ready. They are added to the queue; nothing is processed yet.")
    if engine.mode == "llm":
        st.warning("When processed, the request text is sent to the LLM provider.")
    if st.button(f"Add {len(frame)} to queue", type="primary"):
        add_to_queue([{"request_id": r.request_id, "requester": r.requester, "text": r.request_text, "source": "upload"}
                      for r in frame.itertuples()])
        st.rerun()


@st.dialog("Welcome")
def intro_dialog() -> None:
    st.markdown(
        "**OpsFlow Lab** tests an AI workflow on a fictional clinic's internal requests.\n\n"
        "1. **Request inbox**: process requests, then approve or correct each result.\n"
        "2. **Replay lab**: run labelled test cases and see where it goes wrong.\n"
        "3. **Impact report**: estimate hours and cost saved.\n\n"
        "Nothing is sent anywhere without your action.")
    if st.button("Got it", type="primary"):
        storage.mark_onboarded(st.session_state["user"]["email"])
        st.session_state["user"]["onboarded"] = True
        st.rerun()


if not st.session_state["user"].get("onboarded", True):
    intro_dialog()

# ---------------------------------------------------------------- header + toolbar
ui.page_header("Request inbox", "", engine)
queue, results, status = st.session_state.queue, st.session_state.results, st.session_state.status
pending = [i for i in queue if i["request_id"] not in results]

with st.container(horizontal=True):
    if st.button("New request", icon=":material/add:"):
        new_request_dialog()
    if st.button("Upload CSV", icon=":material/upload:"):
        upload_dialog()
    if results and not pending and st.button("Next: Replay lab", icon=":material/arrow_forward:", key="next_replay"):
        st.switch_page("app_pages/replay.py")
    if st.button("Process all", type="primary", icon=":material/play_arrow:", key="process_all",
                 disabled=not pending):
        process(pending)
        st.rerun()
if st.session_state.flash:
    st.toast(st.session_state.flash, icon=":material/check:")
    st.session_state.flash = None

# ---------------------------------------------------------------- queue + detail
list_col, detail_col = st.columns([3, 2], gap="small")


def row_status(rid: str) -> str:
    return status.get(rid, "Not processed")


with list_col, ui.card("queue"):
    show = st.segmented_control("Show", ["All", "Not processed", "Ready for review", "Done"], default="All",
                                key="inbox_filter", label_visibility="collapsed") or "All"
    query = st.text_input("Search requests", key="inbox_search", placeholder="Search id or text",
                          label_visibility="collapsed", icon=":material/search:")
    rows = []
    for i in queue:
        rid, res = i["request_id"], results.get(i["request_id"])
        rows.append({"Request": rid, "Status": row_status(rid),
                     "Priority": res.priority if res and not res.error else "",
                     "Category": res.category if res and not res.error else "",
                     "Text": i["text"][:80],
                     "Team": res.team if res and not res.error else "",
                     "Flag": "Review" if res and res.needs_review else ""})
    table = pd.DataFrame(rows)
    if show == "Done":
        table = table[table["Status"].isin(["Approved", "Corrected"])]
    elif show != "All":
        table = table[table["Status"] == show]
    if query.strip():
        needle = query.strip().lower()
        table = table[table["Request"].str.lower().str.contains(needle, regex=False)
                      | table["Text"].str.lower().str.contains(needle, regex=False)]
    table = table.reset_index(drop=True)
    if not table.empty:
        st.download_button("Export CSV", table.to_csv(index=False).encode("utf-8"), "opsflow_queue.csv", "text/csv",
                           icon=":material/download:", key="queue_export")
    if table.empty:
        st.info("Nothing here.")
    else:
        STATUS_BG = {"Not processed": "", "Ready for review": "#FFF1D6", "Approved": "#E3F5EE", "Corrected": "#E1ECFF"}
        PRIORITY_FG = {"Urgent": "#B42318", "High": "#B54708", "Normal": "#475467", "Low": "#0B7D63"}

        def paint(frame):
            css = pd.DataFrame("", index=frame.index, columns=frame.columns)
            css["Status"] = frame["Status"].map(lambda v: f"background-color:{STATUS_BG.get(v, '')};" + ("color:#667085" if v == "Not processed" else "font-weight:600"))
            css["Priority"] = frame["Priority"].map(lambda v: f"color:{PRIORITY_FG.get(v, '')};font-weight:600")
            return css

        event = st.dataframe(table.style.apply(paint, axis=None), hide_index=True, width="stretch", height=520, on_select="rerun",
                             selection_mode="single-row", key=f"inbox_table_{show}",
                             column_config={"Text": st.column_config.TextColumn("Request text", width="medium")})
        if event.selection.rows:
            st.session_state.selected_id = table.iloc[event.selection.rows[0]]["Request"]

with detail_col, ui.card("detail"):
    item = next((i for i in queue if i["request_id"] == st.session_state.selected_id), queue[0])
    rid = item["request_id"]
    res = results.get(rid)
    head = st.container(horizontal=True, vertical_alignment="center")
    head.markdown(f"**{rid}**")
    head.badge(row_status(rid), color=STATUS_COLOR[row_status(rid)])
    st.write(item["text"])
    st.caption(f"Requester: {item['requester'] or 'not given'}")

    if res is None:
        if st.button("Process this request", type="primary", key=f"proc_{rid}", icon=":material/play_arrow:"):
            process([item])
            st.rerun()
        st.stop()
    if res.error:
        st.error(f"Could not be processed: {res.error}. Route it manually.")
        if st.button("Try again", key=f"retry_{rid}"):
            process([item])
            st.rerun()
        st.stop()

    chips = st.container(horizontal=True)
    chips.badge(res.category, color="blue")
    with chips:
        ui.priority_badge(res.priority)
    chips.badge(res.team, color="violet")
    if res.needs_review:
        st.warning(res.review_reason, icon=":material/flag:", title="Needs human review")

    tab_details, tab_reply, tab_ai, tab_raw = st.tabs(["Details", "Reply draft", "AI check", "Data"])
    with tab_details:
        st.write(res.summary)
        info = res.extracted.model_dump()
        labels = {"location": "Location", "item": "Item", "asset_tag": "Asset tag", "quantity": "Quantity",
                  "contact": "Contact"}
        st.dataframe(pd.DataFrame({"Field": list(labels.values()), "Value": [info[k] or "-" for k in labels]}),
                     hide_index=True, width="stretch")
        if res.missing_information:
            st.markdown("**Missing:** " + ", ".join(res.missing_information))
        st.caption(res.explanation)
    with tab_reply:
        st.text(res.suggested_response)
    with tab_ai:
        other_mode = "rules" if engine.mode == "llm" else "llm"
        other_fn = ui.triage_fn_for(other_mode)
        if other_fn is None:
            st.info("The AI model is not connected.")
        elif st.button("Compare with " + ("rule-based demo" if other_mode == "rules" else "LLM"), key=f"cmp_{rid}",
                       icon=":material/compare_arrows:"):
            with st.spinner("Running..."):
                st.session_state.setdefault("second", {})[rid] = other_fn(rid, item["text"], item["requester"] or None)
        other = st.session_state.get("second", {}).get(rid)
        if other is not None:
            if other.error:
                st.error(f"Could not run the second engine: {other.error}")
            else:
                rows = [{"Field": f.capitalize(), "Current": getattr(res, f), "Second opinion": getattr(other, f),
                         "Agree": "✓" if getattr(res, f) == getattr(other, f) else "✗"}
                        for f in ("category", "priority", "team")]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                if all(r["Agree"] == "✓" for r in rows):
                    st.success("Both engines agree.")
                else:
                    st.warning("The engines disagree. Check this request before approving.")
                st.caption(f"Second opinion from: {other.engine}")
    with tab_raw:
        st.json(res.model_dump())

    if row_status(rid) == "Ready for review":
        if st.button("Review this request", type="primary", icon=":material/fact_check:", key=f"to_review_{rid}"):
            st.session_state.review_id = rid
            st.switch_page("app_pages/review.py")
    else:
        st.badge(row_status(rid), color=STATUS_COLOR[row_status(rid)])
