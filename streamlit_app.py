"""Entry point for Streamlit Community Cloud: the live fund plus the harness lab."""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "evaluation"))  # the harness package used by the lab page

st.set_page_config(page_title="Momentum L/S Paper Fund", page_icon="📈", layout="wide")
st.session_state["_multipage"] = True

page = st.navigation([
    st.Page("dashboard/fund_page.py", title="Fund", icon="📈", default=True),
    st.Page("evaluation/app.py", title="Harness lab", icon="🧪"),
])
page.run()
