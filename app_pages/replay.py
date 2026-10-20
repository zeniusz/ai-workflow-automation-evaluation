import pandas as pd
import plotly.express as px
import streamlit as st

from src import ui_common as ui
from src.evaluation import (STATUS_CORRECT, STATUS_FAILED, STATUS_INCORRECT, STATUS_REVIEW, evaluate, mismatch_notes,
                            results_to_csv)
from src.triage import CATEGORIES

storage = ui.get_storage()
engine = ui.current_engine()

DATASETS = {
    "Labelled sample set": (ui.sample_data, "development set, scores are optimistic"),
    "Holdout set": (ui.holdout_data, "not used to tune the rules, small sample"),
}

ui.page_header("Replay lab", "", engine)

dataset = st.segmented_control("Dataset", list(DATASETS), default="Labelled sample set", key="replay_dataset") \
    or "Labelled sample set"
loader, note = DATASETS[dataset]
labelled = loader()
run_key = (dataset, engine.label)

if engine.mode == "llm":
    st.caption(f"All {len(labelled)} request texts will be sent to the LLM provider when you run the evaluation.")

run_clicked = st.button("Run evaluation", type="primary", icon=":material/play_arrow:", disabled=labelled.empty)
if labelled.empty:
    st.warning("This dataset has no cases.")
    st.stop()
if run_clicked:
    bar = st.progress(0.0, text="Running evaluation...")
    run = evaluate(labelled, ui.make_triage_fn(engine), dataset=dataset, engine=engine.label,
                   progress=lambda i, n: bar.progress(i / n, text=f"Processed {i} of {n}"))
    bar.empty()
    run_id = storage.save_run("replay", engine.label, dataset, n_requests=run.metrics["n"],
                              n_flagged=run.metrics["review_flagged"], metrics=run.metrics)
    st.session_state.replays[run_key] = (run, run_id)

stored = st.session_state.replays.get(run_key)
if not stored and engine.mode == "rules":  # instant and local: show results straight away
    st.session_state.replays[run_key] = (evaluate(labelled, ui.make_triage_fn(engine), dataset=dataset,
                                                  engine=engine.label), "auto")
    stored = st.session_state.replays[run_key]
if not stored:
    st.stop()

run, run_id = stored
m, results = run.metrics, run.results
st.divider()
if m["failed"]:
    st.error(f"{m['failed']} case(s) could not be processed. They count as incorrect on every field.")

ui.kpi_cards([
    ("Category accuracy", ui.fmt_pct(m["category_accuracy"]), f"{int(results['category_ok'].sum())} of {m['n']} correct"),
    ("Priority accuracy", ui.fmt_pct(m["priority_accuracy"]), f"{int(results['priority_ok'].sum())} of {m['n']} correct"),
    ("Team accuracy", ui.fmt_pct(m["team_accuracy"]), f"{int(results['team_ok'].sum())} of {m['n']} correct"),
    ("Human-review rate", ui.fmt_pct(m["review_rate"]), f"{m['review_flagged']} of {m['n']} flagged"),
])

# ---- cases ----
st.divider()
fcol, dcol = st.columns([3, 1], vertical_alignment="bottom")
status_filter = fcol.segmented_control(
    "Show cases", ["All", STATUS_INCORRECT, STATUS_REVIEW, STATUS_CORRECT, STATUS_FAILED], default="All", key="replay_filter") or "All"
dcol.download_button("Export CSV", results_to_csv(results), f"opsflow_replay_{run_id}.csv", "text/csv",
                     icon=":material/download:", width="stretch")
view = (results if status_filter == "All" else results[results["status"] == status_filter]).reset_index(drop=True)
if view.empty:
    st.info("No cases match this filter.")
    st.stop()

SYMBOL = {STATUS_CORRECT: "✓ Correct", STATUS_INCORRECT: "✗ Incorrect", STATUS_REVIEW: "⚑ Review required",
          STATUS_FAILED: "✗ Not processed"}


def cell(row: pd.Series, field: str) -> str:
    actual = row[f"actual_{field}"] or "none"
    return actual if row[f"{field}_ok"] else f"{actual} (expected {row[f'expected_{field}']})"


table = pd.DataFrame({
    "Case": view["request_id"],
    "Status": view["status"].map(SYMBOL),
    "Category": view.apply(lambda r: cell(r, "category"), axis=1),
    "Priority": view.apply(lambda r: cell(r, "priority"), axis=1),
    "Team": view.apply(lambda r: cell(r, "team"), axis=1),
})
STATUS_STYLE = {SYMBOL[STATUS_CORRECT]: "background-color:#E3F5EE;color:#0B5E4A",
                SYMBOL[STATUS_INCORRECT]: "background-color:#FDE8E6;color:#9B2C1F",
                SYMBOL[STATUS_REVIEW]: "background-color:#FFF1D6;color:#8A5A00",
                SYMBOL[STATUS_FAILED]: "background-color:#FDE8E6;color:#9B2C1F"}
ok_mask = view[["category_ok", "priority_ok", "team_ok"]].rename(
    columns={"category_ok": "Category", "priority_ok": "Priority", "team_ok": "Team"})


def style_cells(frame: pd.DataFrame) -> pd.DataFrame:
    css = pd.DataFrame("", index=frame.index, columns=frame.columns)
    css["Status"] = frame["Status"].map(STATUS_STYLE)
    for col in ok_mask.columns:
        css.loc[~ok_mask[col], col] = "color:#9B2C1F;font-weight:600"
    return css


event = st.dataframe(table.style.apply(style_cells, axis=None), hide_index=True, width="stretch",
                     height=min(400, 40 + 35 * len(table)), on_select="rerun", selection_mode="single-row",
                     key=f"replay_table_{run_id}_{status_filter}")


# ---- detail ----
case = view.iloc[event.selection.rows[0] if event.selection.rows else 0]
st.markdown(f"**Case {case['request_id']}**: {SYMBOL[case['status']]}")
tab_req, tab_cmp, tab_why = st.tabs(["Request", "Expected vs actual", "Review and explanation"])
with tab_req:
    st.write(case["request_text"])
with tab_cmp:
    st.dataframe(pd.DataFrame({
        "Field": ["Category", "Priority", "Team"],
        "Expected": [case["expected_category"], case["expected_priority"], case["expected_team"]],
        "Actual": [case["actual_category"] or "none", case["actual_priority"] or "none", case["actual_team"] or "none"],
        "Result": ["✓ Correct" if case[f"{f}_ok"] else "✗ Incorrect" for f in ("category", "priority", "team")],
    }), hide_index=True, width="stretch")
    notes = mismatch_notes(case)
    if notes:
        st.markdown("**What went wrong**")
        for n in notes:
            st.markdown(f"- {n}")
    else:
        st.success("All three fields match the label.")
with tab_why:
    if case["needs_review"]:
        st.warning(case["review_reason"], icon=":material/flag:", title="Flagged for human review")
    elif not case["exact_ok"]:
        st.error("This error was not flagged for review.", icon=":material/warning:")
    else:
        st.info("Not flagged for review.")
    if case["missing_information"]:
        st.markdown(f"**Missing information:** {case['missing_information']}")
    st.markdown("**Workflow explanation**")
    st.write(case["explanation"])

with st.expander("Category confusion matrix"):
    matrix = pd.crosstab(results["expected_category"], results["actual_category"]).reindex(
        index=CATEGORIES, columns=CATEGORIES, fill_value=0)
    fig = px.imshow(matrix, text_auto=True, aspect="auto", color_continuous_scale=["#FFFFFF", ui.MINT_DARK],
                    labels=dict(x="Actual", y="Expected", color="Cases"))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=5, b=0), coloraxis_showscale=False,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")

st.divider()
if st.button("Next: estimate the impact", icon=":material/arrow_forward:", key="next_impact"):
    st.switch_page("app_pages/impact.py")
