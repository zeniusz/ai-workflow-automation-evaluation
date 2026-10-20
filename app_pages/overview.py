import json

import pandas as pd
import plotly.express as px
import streamlit as st

from src import ui_common as ui
from src.triage import CATEGORIES

storage = ui.get_storage()
engine = ui.current_engine()
sample, holdout = ui.sample_data(), ui.holdout_data()
import datetime as _dt

_hour = _dt.datetime.now().hour
_greeting = "Good morning" if _hour < 12 else "Good afternoon" if _hour < 18 else "Good evening"
ui.page_header("Overview", f"{_greeting}, {st.session_state['user']['name'].split()[0]}. "
               f"{_dt.date.today():%A %d %B}.", engine)

pick, _ = st.columns([1, 3])
with pick:
    month_label = st.selectbox("Period", ["All time", *storage.months()], key="overview_month",
                               label_visibility="collapsed", format_func=lambda m: m if m == "All time" else ui.month_label(m))
month = None if month_label == "All time" else month_label
processed = storage.processed()
if month:
    processed = processed[processed["processed_at"].str.startswith(month)]
reviews = storage.review_summary(month)
latest = storage.latest_replay(month)  # only a saved, completed run counts as an evaluation
assumptions = st.session_state["assumptions"]
n_processed = len(processed)
n_flagged = int(processed["needs_review"].sum()) if n_processed else 0

# ---- what needs attention (derived from real stored results only) ----
notes = []
if latest and latest["metrics"]["errors_unflagged"]:
    mt = latest["metrics"]
    notes.append(f"{mt['errors_unflagged']} of {mt['errors']} wrong results in the last evaluation "
                 f"({latest['dataset']}) were not flagged for human review.")
if reviews["total"] and reviews["corrected"]:
    worst = max(reviews["corrections_by_field"], key=reviews["corrections_by_field"].get)
    notes.append(f"Reviewers corrected {reviews['corrected']} of {reviews['total']} results, most often the {worst}.")
if not latest:
    notes.append("The workflow has not been evaluated yet, so its accuracy is unknown.")
if notes:
    ui.attention("Needs attention", notes)

# ---- headline numbers: one row of equal cards ----
accuracy = ("Routing accuracy", ui.fmt_pct(latest["metrics"]["routing_accuracy"]) if latest else "-", "", "", "dark")
saved = n_processed * (assumptions.manual_minutes - assumptions.assisted_minutes) / 60
ui.kpi_cards([
    accuracy,
    ("Requests processed", str(n_processed)),
    ("Needing human review", str(n_flagged)),
    ("Estimated time saved", ui.fmt_hours(saved)),
])

# ---- charts ----
left, right = st.columns([2, 1], gap="small")
with left:
    with ui.card("accuracy_trend", height=420):
        st.markdown("**Routing accuracy by evaluation run**")
        runs = storage.runs(limit=500, month=month)
        runs = runs[(runs["run_type"] == "replay") & runs["metrics_json"].notna()].copy()
        if runs.empty:
            st.caption("No evaluation runs yet.")
        else:
            runs["Routing accuracy"] = runs["metrics_json"].apply(lambda j: json.loads(j)["routing_accuracy"])
            runs["Month"] = pd.to_datetime(runs["created_at"]).dt.strftime("%b %Y")
            runs["Month order"] = pd.to_datetime(runs["created_at"]).dt.strftime("%Y-%m")
            runs["Test set"] = runs["dataset"]
            latest_per = (runs.sort_values("created_at").groupby(["Month order", "Month", "Test set"], as_index=False).last()
                          .sort_values("Month order"))
            fig = px.bar(latest_per, x="Month", y="Routing accuracy", color="Test set", barmode="group",
                         text=latest_per["Routing accuracy"].map(lambda v: f"{v:.0%}"),
                         color_discrete_sequence=[ui.MINT_DARK, ui.NAVY])
            fig.update_xaxes(categoryorder="array", categoryarray=list(dict.fromkeys(latest_per["Month"])))
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0),
                              yaxis=dict(range=[0, 1.15], tickformat=".0%", title=None), xaxis=dict(title=None),
                              legend=dict(orientation="h", y=-0.15, title=None),
                              plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch")
with right:
    with ui.card("categories", height=420):
        st.markdown("**Request categories**")
        if n_processed:
            counts, source = processed["category"].value_counts(), "Processed requests"
        else:
            counts, source = pd.concat([sample, holdout])["expected_category"].value_counts(), "Sample dataset (not processed)"
        frame = counts.reindex(CATEGORIES, fill_value=0).rename_axis("Category").reset_index(name="Requests")
        fig = px.pie(frame[frame["Requests"] > 0], names="Category", values="Requests", hole=0.62, color="Category",
                     color_discrete_map=dict(zip(CATEGORIES, [ui.NAVY, ui.MINT_DARK, "#3DDBB0", "#7F93AD", "#D0D5DD"])))
        fig.update_traces(textinfo="value", sort=False)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.1, yanchor="top"),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")

# ---- feedback + activity ----
fb, act = st.columns([1, 2], gap="small")
with fb:
    with ui.card("feedback", height=400):
        st.markdown("**Human review**")
        stat_values = list(st.session_state.get("status", {}).values())
        waiting = stat_values.count("Ready for review")
        reviewed = stat_values.count("Approved") + stat_values.count("Corrected")
        r1, r2 = st.columns(2)
        r1.metric("Waiting", waiting)
        r2.metric("Reviewed", reviewed)
        if reviews["total"]:
            st.metric("Accepted unchanged", ui.fmt_pct(reviews["acceptance_rate"]))
            fields = pd.Series(reviews["corrections_by_field"]).rename_axis("Field").reset_index(name="Corrections")
            st.dataframe(fields, hide_index=True, width="stretch",
                         column_config={"Corrections": st.column_config.ProgressColumn(
                             "Corrections", min_value=0, max_value=max(1, int(fields["Corrections"].max())), format="%d")})
        elif waiting:
            st.progress(reviewed / max(1, waiting + reviewed), text="Review progress")
            if st.button("Start reviewing", type="primary", key="start_review"):
                st.switch_page("app_pages/review.py")
with act:
    with ui.card("activity", height=400):
        st.markdown("**Recent activity**")
        recent = storage.runs(limit=12, month=month)
        if recent.empty:
            st.caption("No activity yet.")
        else:
            view = recent.assign(
                Time=pd.to_datetime(recent["created_at"]).dt.strftime("%b %d %H:%M"),
                Engine=recent["engine"].map(ui.engine_short),
                Routing=recent["metrics_json"].apply(
                    lambda j: json.loads(j).get("routing_accuracy") if isinstance(j, str) else None))
            st.dataframe(view[["Time", "run_type", "dataset", "Engine", "n_requests", "Routing"]],
                         hide_index=True, width="stretch", column_config={
                             "run_type": "Type", "dataset": "Source", "n_requests": "Requests",
                             "Routing": st.column_config.NumberColumn("Routing", format="percent")})
