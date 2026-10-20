"""OpsFlow Lab: from manual work to verified AI. Streamlit entry point."""
import logging
from pathlib import Path

import streamlit as st

from src import ui_common as ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="OpsFlow Lab", page_icon=str(ASSETS / "icon.svg"), layout="wide")
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "icon.svg"), size="large")

ui.init_state()
ui.inject_css()

if "user" not in st.session_state:
    ui.signin_page()
    st.stop()

pages = [
    st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:", url_path="overview"),
    st.Page("app_pages/inbox.py", title="Request inbox", icon=":material/inbox:", default=True),
    st.Page("app_pages/review.py", title="Human review", icon=":material/fact_check:", url_path="review"),
    st.Page("app_pages/messages.py", title="Messages", icon=":material/forum:", url_path="messages"),
    st.Page("app_pages/replay.py", title="Replay lab", icon=":material/replay:", url_path="replay"),
    st.Page("app_pages/ai.py", title="AI assistant", icon=":material/auto_awesome:", url_path="ai"),
    st.Page("app_pages/impact.py", title="Impact report", icon=":material/calculate:", url_path="impact"),
    st.Page("app_pages/team.py", title="Team", icon=":material/group:", url_path="team"),
]
page = st.navigation(pages)
ui.sidebar_user()
ui.load_workspace()
page.run()
