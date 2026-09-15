"""
app.py  —  Multi-page entry point for Streamlit 1.36+
Run with:  streamlit run app.py
"""
import os
import sys
from pathlib import Path

import streamlit as st

# Bootstrap: allow same-folder imports and load .env
sys.path.insert(0, str(Path(__file__).parent))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Bridge Streamlit Cloud secrets → env vars
try:
    for _key in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN", "SF_DOMAIN",
                 "BQ_CREDENTIALS_FILE", "GP_PASSWORD"):
        if _key in st.secrets and not os.getenv(_key):
            os.environ[_key] = st.secrets[_key]
except Exception:
    pass

# ── Navigation ─────────────────────────────────────────────────────────────
pg = st.navigation([
    st.Page("dashboard.py",                title="SSL Dashboard",   icon="📦", default=True),
    st.Page("pages/01_Inventory_Aging.py", title="Inventory Aging", icon="📊"),
    st.Page("pages/02_Comparison.py",      title="Comparison",      icon="📈"),
    st.Page("pages/03_Monthly_Reports.py", title="Monthly Reports",  icon="📋"),
    st.Page("pages/gp.py", title="GP Analysis", icon="📊", url_path="gp"),
])

# ── Global CSS applied to every page ───────────────────────────────────────
st.markdown("""
<style>
/* ---------- fit to screen: remove excess padding ---------- */
.block-container {
    padding-top: 0.75rem !important;
    padding-bottom: 0.75rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    max-width: 100% !important;
}
/* ---------- plotly charts always fill their column ---------- */
.js-plotly-plot, .plotly, .plot-container {
    max-width: 100% !important;
    width: 100% !important;
}
/* ---------- tables scroll horizontally, never overflow ---------- */
[data-testid="stDataFrame"] { overflow-x: auto !important; }
/* ---------- tabs don't clip content ---------- */
[data-testid="stTabs"] { overflow: visible !important; }
/* ---------- responsive: stack st.columns on narrow screens ---------- */
@media (max-width: 768px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 0 !important;
    }
    .block-container {
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
    }
}
</style>
""", unsafe_allow_html=True)

pg.run()
