import pandas as pd
import plotly.express as px
import streamlit as st

from src import ui_common as ui
from src.impact import ImpactAssumptions, calculate_impact

ui.page_header("Impact report", "Weekly estimate from your assumptions.", ui.current_engine())

current: ImpactAssumptions = st.session_state["assumptions"]
form, out = st.columns([2, 3], gap="large")

with form, ui.card("assumptions"):
    ui.section_label("Assumptions")
    st.markdown("**Workload**")
    requests = st.number_input("Requests per week", min_value=0, max_value=100_000, value=int(current.requests_per_week),
                               step=10)
    st.markdown("**Handling time**")
    manual = st.number_input("Manual handling time per request (minutes)", min_value=0.0, max_value=480.0,
                             value=float(current.manual_minutes), step=0.5)
    assisted = st.number_input("AI-assisted handling and review time per request (minutes)", min_value=0.0,
                               max_value=480.0, value=float(current.assisted_minutes), step=0.5,
                               help="Employee time to review, correct and approve the proposal, including exceptions. "
                                    "Not the model's response time.")
    st.markdown("**Cost**")
    hourly = st.number_input("Operating cost per hour (€)", min_value=0.0, max_value=1000.0,
                             value=float(current.hourly_cost), step=1.0)
    ai_cost = st.number_input("AI cost per request (€)", min_value=0.0, max_value=100.0,
                              value=float(current.ai_cost_per_request), step=0.01, format="%.3f",
                              help="Use 0 for the rule-based demo.")

assumptions = ImpactAssumptions(requests, manual, assisted, hourly, ai_cost)
st.session_state["assumptions"] = assumptions  # shared with the Overview page
r = calculate_impact(assumptions)

with out, ui.card("results"):
    ui.section_label("Estimated result per week")
    tone = "pos" if r.net_benefit > 0 else "neg" if r.net_benefit < 0 else "zero"
    verdict = ("Net benefit" if r.net_benefit > 0 else "Net cost" if r.net_benefit < 0 else "Break-even")
    st.html(f'<div class="ops-headline"><p class="label">Estimated net benefit per week</p>'
            f'<p class="value {tone}">{ui.fmt_money(r.net_benefit)}</p>'
            f'<p class="sub">{verdict}: labour capacity value minus AI operating cost (estimate)</p></div>')
    if requests == 0:
        st.info("Requests per week is zero, so every figure is zero. Enter a weekly volume to see an estimate.")
    if r.hours_saved < 0:
        st.warning("Under these assumptions the AI-assisted process takes longer than the manual one, so the "
                   "estimated saving is negative.", icon=":material/trending_down:")

    change = "n/a" if r.percent_reduction is None else f"{-r.percent_reduction * 100:+.1f}%".replace("-", "−")
    ui.kpi_cards([
        ("Baseline handling", ui.fmt_hours(r.baseline_hours), "per week, manual"),
        ("AI-assisted handling", ui.fmt_hours(r.assisted_hours), "per week, with review"),
        ("Hours saved", ui.fmt_hours(r.hours_saved), "per week"),
        ("Change in handling time", change, "negative is faster"),
        ("Labour capacity value", ui.fmt_money(r.capacity_value), "per week"),
        ("AI operating cost", ui.fmt_money(r.ai_cost), "per week"),
    ], per_row=2)

    frame = pd.DataFrame({"Process": ["Manual", "AI-assisted"], "Hours": [r.baseline_hours, r.assisted_hours]})
    fig = px.bar(frame, x="Hours", y="Process", orientation="h", text=frame["Hours"].map(lambda v: f"{v:,.1f} h"),
                 color="Process", color_discrete_sequence=[ui.GREY, ui.MINT_DARK])
    fig.update_layout(height=160, showlegend=False, margin=dict(l=0, r=30, t=5, b=0), yaxis=dict(autorange="reversed", title=None),
                      xaxis=dict(visible=False), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_traces(textposition="outside", cliponaxis=False)
    st.plotly_chart(fig, width="stretch")

    with st.expander("How this is calculated"):
        st.markdown(
            f"""
| Step | Formula | Result |
|---|---|---|
| Baseline hours | {requests:,} × {manual:g} min ÷ 60 | {r.baseline_hours:,.1f} h |
| AI-assisted hours | {requests:,} × {assisted:g} min ÷ 60 | {r.assisted_hours:,.1f} h |
| Hours saved | baseline − AI-assisted | {r.hours_saved:,.1f} h |
| Labour capacity value | {r.hours_saved:,.1f} h × €{hourly:g} | {ui.fmt_money(r.capacity_value)} |
| AI operating cost | {requests:,} × €{ai_cost:g} | {ui.fmt_money(r.ai_cost)} |
| Net benefit | capacity value − AI cost | {ui.fmt_money(r.net_benefit)} |
"""
        )
    st.caption("All figures are estimates from your assumptions, not realised savings.")
