from html import escape

import pandas as pd
import streamlit as st

from src import ui_common as ui
from src.triage import TEAMS

storage = ui.get_storage()
user = st.session_state["user"]
results = st.session_state.get("results", {})
ui.page_header("Messages", "Send one message to a team, or to everyone.", ui.current_engine())

URGENT_CHIP = '<span class="ops-chip bad">Urgent</span>'
RECIPIENTS = ["All teams", *TEAMS]


def draft_from_request() -> None:
    """Fill the form from a processed request so urgent items can be announced in one click."""
    res = results.get(st.session_state.get("msg_request"))
    if res is None:
        return
    st.session_state["msg_to"] = res.team
    st.session_state["msg_priority"] = "Urgent" if res.priority == "Urgent" else "Normal"
    st.session_state["msg_subject"] = f"{res.priority} {res.category.lower()} request {res.request_id}"
    st.session_state["msg_body"] = (f"{res.summary}\n\nProposed: {res.category}, {res.priority}, {res.team}."
                                    + (f"\nNeeds attention: {res.review_reason}" if res.needs_review else ""))


compose, feed = st.columns([2, 3], gap="small")
with compose, ui.card("compose"):
    st.markdown("**New message**")
    linkable = [rid for rid, r in results.items() if not r.error]
    st.selectbox("Link a request (optional)", ["None", *linkable], key="msg_request",
                 on_change=draft_from_request)
    st.selectbox("To", RECIPIENTS, key="msg_to")
    st.segmented_control("Priority", ["Normal", "Urgent"], default="Normal", key="msg_priority")
    st.text_input("Subject", key="msg_subject", max_chars=120)
    st.text_area("Message", key="msg_body", height=140, max_chars=2000)
    if st.button("Send", type="primary", icon=":material/send:", key="msg_send"):
        try:
            link = st.session_state.get("msg_request")
            storage.send_message(user["name"], st.session_state["msg_to"], st.session_state["msg_subject"],
                                 st.session_state["msg_body"], st.session_state.get("msg_priority") or "Normal",
                                 None if link in (None, "None") else link)
        except ValueError as exc:
            st.error(str(exc))
        else:
            for k in ("msg_subject", "msg_body", "msg_request"):
                st.session_state.pop(k, None)
            st.session_state["msg_sent"] = True
            st.rerun()
    if st.session_state.pop("msg_sent", False):
        st.success("Message sent.")

with feed, ui.card("feed"):
    f1, f2 = st.columns([1, 1], vertical_alignment="center")
    view_mode = f1.segmented_control("View", ["All", "Sent by me"], default="All", key="msg_view",
                                     label_visibility="collapsed") or "All"
    team = f2.selectbox("Team", ["All teams", *TEAMS], label_visibility="collapsed", key="msg_filter")
    inbox = storage.messages(None if team == "All teams" else team)
    if view_mode == "Sent by me":
        inbox = inbox[inbox["sender"] == user["name"]]
    inbox = inbox.reset_index(drop=True)
    if inbox.empty:
        st.write("No messages.")
    else:
        view = inbox.assign(Time=pd.to_datetime(inbox["created_at"]).dt.strftime("%b %d %H:%M"),
                            Direction=inbox["sender"].map(lambda n: "Sent" if n == user["name"] else "Received"))
        event = st.dataframe(view[["Time", "Direction", "sender", "recipient", "priority", "subject"]], hide_index=True,
                             width="stretch", height=300, on_select="rerun", selection_mode="single-row",
                             key=f"msg_table_{view_mode}_{team}",
                             column_config={"sender": "From", "recipient": "To", "priority": "Priority", "subject": "Subject"})
        row = inbox.iloc[event.selection.rows[0] if event.selection.rows else 0]
        urgent = row["priority"] == "Urgent"
        st.html(f'<div class="ops-mail"><div class="ops-mail-head"><b>{escape(row["subject"])}</b>'
                f'{URGENT_CHIP if urgent else ""}</div>'
                f'<p class="ops-mail-meta">From {escape(row["sender"])} to {escape(row["recipient"])}, '
                f'{pd.to_datetime(row["created_at"]):%d %b %H:%M}</p>'
                f'<p class="ops-mail-body">{escape(row["body"]).replace(chr(10), "<br>")}</p></div>')
        st.caption("Preview of how this message would appear in an email client. It is shown in the app only; nothing is emailed.")
