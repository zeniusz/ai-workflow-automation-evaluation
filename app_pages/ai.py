import pandas as pd
import streamlit as st

from src import config, ui_common as ui
from src.config import MAX_REQUEST_CHARS
from src.evaluation import evaluate
from src.triage import RULES_ENGINE, llm_engine_label, validate_request_text

storage = ui.get_storage()
engine = ui.current_engine()
connected = config.llm_available()
rules_fn, llm_fn = ui.triage_fn_for("rules"), ui.triage_fn_for("llm")

ui.page_header("AI assistant", "Compare the rule-based workflow with an LLM on the same requests.", engine)

# ---- try one request on both engines ----
with ui.card("ai_try"):
    st.markdown("**Try a request on both engines**")
    text = st.text_area("Request text", value=ui.sample_data().iloc[0]["request_text"], max_chars=MAX_REQUEST_CHARS,
                        height=100, key="ai_text", label_visibility="collapsed",
                        placeholder="e.g. The autoclave in the sterilisation room failed its cycle twice. Tag BM-0932.")
    if st.button("Run both", type="primary", icon=":material/compare_arrows:", key="ai_run_one"):
        try:
            clean = validate_request_text(text)
        except ValueError as exc:
            st.error(str(exc))
        else:
            with st.spinner("Running..."):
                st.session_state["ai_one"] = {"rules": rules_fn("TRY", clean, None),
                                              "llm": llm_fn("TRY", clean, None) if llm_fn else None}
    one = st.session_state.get("ai_one")
    if not one:  # show the rule-based result for the prefilled request right away
        one = {"rules": rules_fn("TRY", text, None), "llm": None}
    if one:
        c1, c2 = st.columns(2)
        for col, key, label in ((c1, "rules", "Rule-based demo"), (c2, "llm", f"LLM ({config.llm_model()})")):
            with col:
                st.markdown(f"**{label}**")
                res = one[key]
                if res is None:
                    st.caption("Not connected")
                elif res.error:
                    st.error(res.error)
                else:
                    st.write(f"{res.category}, {res.priority}, {res.team}")
                    if res.needs_review:
                        st.caption("Flagged: " + res.review_reason)
                    st.caption(res.explanation)

# ---- compare on a labelled dataset ----
with ui.card("ai_compare_card"):
    st.markdown("**Compare on labelled cases**")
    DATASETS = {"Labelled sample set": ui.sample_data, "Holdout set": ui.holdout_data}
    dataset = st.segmented_control("Dataset", list(DATASETS), default="Holdout set", key="ai_dataset") or "Holdout set"
    labelled = DATASETS[dataset]()
    if st.button("Run comparison", type="primary", icon=":material/play_arrow:", key="ai_compare", disabled=not connected):
        bar = st.progress(0.0, text="Running...")
        runs = {}
        for name, fn, label in (("rules", rules_fn, RULES_ENGINE), ("llm", llm_fn, llm_engine_label(config.llm_model()))):
            runs[name] = evaluate(labelled, fn, dataset=dataset, engine=label,
                                  progress=lambda i, n, name=name: bar.progress(i / n / 2 + (0.5 if name == "llm" else 0),
                                                                                text=f"{name}: {i} of {n}"))
            storage.save_run("replay", label, dataset, n_requests=runs[name].metrics["n"],
                             n_flagged=runs[name].metrics["review_flagged"], metrics=runs[name].metrics)
        bar.empty()
        st.session_state.setdefault("ai_runs", {})[dataset] = runs

    runs = st.session_state.get("ai_runs", {}).get(dataset)
    if runs:
        rules_run, llm_run = runs["rules"], runs["llm"]
    else:
        cache = st.session_state.setdefault("ai_rules", {})
        if dataset not in cache:
            cache[dataset] = evaluate(labelled, rules_fn, dataset=dataset, engine=RULES_ENGINE)
        rules_run, llm_run = cache[dataset], None
    r, l = rules_run.metrics, (llm_run.metrics if llm_run else None)
    rows = [("Category accuracy", "category_accuracy"), ("Priority accuracy", "priority_accuracy"),
            ("Team accuracy", "team_accuracy"), ("Routing accuracy", "routing_accuracy"),
            ("Human-review rate", "review_rate")]
    table = pd.DataFrame({"Metric": [n for n, _ in rows],
                          "Rule-based": [ui.fmt_pct(r[k]) for _, k in rows],
                          "LLM": [ui.fmt_pct(l[k]) if l else "-" for _, k in rows]})
    table.loc[len(table)] = ["Errors not flagged", f"{r['errors_unflagged']} of {r['errors']}",
                             f"{l['errors_unflagged']} of {l['errors']}" if l else "-"]
    st.dataframe(table, hide_index=True, width="stretch")
    if llm_run:
        a_, b_ = rules_run.results, llm_run.results
        merged = a_.merge(b_, on="request_id", suffixes=("_rules", "_llm"))
        diff = merged[(merged["actual_category_rules"] != merged["actual_category_llm"])
                      | (merged["actual_priority_rules"] != merged["actual_priority_llm"])
                      | (merged["actual_team_rules"] != merged["actual_team_llm"])]
        st.markdown(f"**Where they disagree ({len(diff)} of {len(merged)})**")
        if diff.empty:
            st.caption("The engines gave the same result on every case.")
        else:
            st.dataframe(diff[["request_id", "expected_category_rules", "actual_category_rules", "actual_category_llm",
                               "expected_priority_rules", "actual_priority_rules", "actual_priority_llm"]],
                         hide_index=True, width="stretch", column_config={
                             "request_id": "Case", "expected_category_rules": "Expected category",
                             "actual_category_rules": "Rules category", "actual_category_llm": "LLM category",
                             "expected_priority_rules": "Expected priority", "actual_priority_rules": "Rules priority",
                             "actual_priority_llm": "LLM priority"})
    else:
        errs = rules_run.results[~rules_run.results["exact_ok"]]
        st.markdown(f"**Rule-based misses ({len(errs)} of {len(rules_run.results)})**")
        st.dataframe(errs[["request_id", "expected_category", "actual_category", "expected_priority", "actual_priority"]],
                     hide_index=True, width="stretch", column_config={
                         "request_id": "Case", "expected_category": "Expected category", "actual_category": "Category",
                         "expected_priority": "Expected priority", "actual_priority": "Priority"})
