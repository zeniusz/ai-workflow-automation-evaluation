import streamlit as st

from src import ui_common as ui

storage = ui.get_storage()
ui.page_header("Team", "People with access and their review activity.", ui.current_engine())

people = storage.users_overview()
people["Accepted unchanged"] = people.apply(
    lambda r: f"{r['approved'] / r['reviews']:.0%}" if r["reviews"] else "-", axis=1)
people["You"] = people["email"].map(lambda e: "You" if e == st.session_state["user"].get("email") else "")

with ui.card("team"):
    st.dataframe(people[["name", "role", "email", "reviews", "Accepted unchanged", "You"]], hide_index=True,
                 width="stretch", column_config={
                     "name": "Name", "role": "Role", "email": "Email", "reviews": "Reviews saved",
                     "Accepted unchanged": "Accepted unchanged"})
