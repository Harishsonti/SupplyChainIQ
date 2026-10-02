import streamlit as st
import json as _json
import html as _html
import decimal as _decimal
from snowflake.snowpark.context import get_active_session
from provenance import parse_agent_response, build_provenance, render_provenance_card
from disagreement import render_disagreement_detector
from readiness import render_readiness_scorecard

session = get_active_session()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="SupplyChainIQ CoCo", layout="wide")

# ── Helpers ───────────────────────────────────────────────────────────────────

def as_float(value, default=0.0):
    """Safely convert decimal.Decimal or any numeric to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def q(sql):
    """Run SQL and return a pandas DataFrame."""
    return session.sql(sql).to_pandas()


def q1(sql):
    """Run SQL and return the first row as a dict, or None."""
    rows = session.sql(sql).collect()
    if not rows:
        return None
    row = rows[0]
    return {col: row[col] for col in row.asDict()}


def fmt_val(value):
    """Format a numeric value with M/K suffixes."""
    v = as_float(value)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:,.1f}K"
    if isinstance(value, float) or isinstance(value, _decimal.Decimal):
        if abs(v) < 1:
            return f"{v:.2f}"
        return f"{v:,.2f}"
    return f"{v:,.0f}"


def fmt_pct(value):
    """Format a percentage value."""
    v = as_float(value)
    return f"{v:.2f}%"


def fmt_usd(value):
    """Format a USD currency value."""
    v = as_float(value)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}K"
    return f"${v:,.0f}"


def render_beige_board(title, df, subtitle="", max_rows=100):
    """Render a warm analytical data table with beige/cream styling."""
    if df is None or df.empty:
        st.info(f"No data for {title}.")
        return
    cols = list(df.columns)
    rows = df.head(max_rows)
    header_html = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for _, row in rows.iterrows():
        cells = []
        for c in cols:
            val = row[c]
            if val is None or (isinstance(val, float) and val != val):
                cells.append('<td style="color:#999;">—</td>')
            else:
                cells.append(f"<td>{_html.escape(str(val))}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body_html = "\n".join(body_rows)
    sub_line = f'<div style="color:var(--beige-2);font-size:0.82rem;margin-bottom:8px;">{_html.escape(subtitle)}</div>' if subtitle else ""
    row_note = f'<div style="color:var(--muted);font-size:0.75rem;margin-top:6px;">Showing {len(rows)} of {len(df)} rows</div>' if len(df) > max_rows else ""
    _h0 = f'<div class="beige-board"> <div style="font-weight:700;font-size:1.05rem;margin-bottom:4px;color:var(--beige-ink);">{_html.escape(title)}</div> {sub_line} <div style="overflow-x:auto;"> <table class="beige-table"> <thead><tr>{header_html}</tr></thead> <tbody>{body_html}</tbody> </table> </div> {row_note} </div>'
    st.markdown(_h0, unsafe_allow_html=True)


def render_signal_card(title, body, source, severity="info"):
    """Render a signal card with severity styling."""
    _h1 = f'<div class="card card-severity-{_html.escape(severity)}"> <div class="card-title">{title}</div> <div class="card-body">{body}</div> <div class="card-source">{_html.escape(source)}</div> </div>'
    st.markdown(_h1, unsafe_allow_html=True)


def render_kpi_strip(items):
    """Render an enterprise KPI strip. items = list of (label, value) tuples."""
    inner = ""
    for label, value in items:
        inner += f'<div class="es-item"><div class="es-label">{_html.escape(str(label))}</div><div class="es-value">{_html.escape(str(value))}</div></div>'
    st.markdown(f'<div class="enterprise-strip">{inner}</div>', unsafe_allow_html=True)


def render_section(title, chip=None):
    """Render a section rule and title."""
    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
    chip_html = f' &nbsp;<span class="entity-chip">{_html.escape(chip)}</span>' if chip else ""
    st.markdown(f'<div class="section-title">{_html.escape(title)}{chip_html}</div>', unsafe_allow_html=True)


# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
:root {
    --bg: #121214;
    --panel: #1a1c1e;
    --panel-2: #222426;
    --border: #36373a;
    --text: #f4f7f3;
    --text-2: #c5d0ca;
    --muted: #879791;
    --green: #6b9e8a;
    --green-soft: #1e2b26;
    --beige: #e8dfcd;
    --beige-2: #d9cfbb;
    --beige-ink: #1c2823;
    --amber: #e8ae55;
    --amber-soft: #3b2e1b;
}

/* ── Full-page scroll fix ─────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"],
section[data-testid="stMain"], .main .block-container {
    overflow: visible !important;
}
.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 1rem !important;
    max-width: 100% !important;
}

/* ── Scrollbar ────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--panel); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ── Topbar ───────────────────────────────────────────────────────── */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    margin: -0.5rem -1rem 1rem -1rem;
    background: linear-gradient(135deg, var(--panel) 0%, var(--panel-2) 100%);
    border-bottom: 1px solid var(--border);
    border-radius: 0;
}
@keyframes supplychainiq-spin { to { transform: rotate(360deg); } }
.brand-row {
    display: flex;
    align-items: center;
    gap: 14px;
}
.brand-mark {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    font-size: 1.3rem;
    font-weight: 800;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #c4b99a, #b0a484) !important; border-color:#c4b99a !important; color:#1a1510;
    color: #fff;
    letter-spacing: -0.03em;
}
.brand-name {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.02em;
}
.brand-sub {
    font-size: 0.78rem;
    color: var(--muted);
    margin-top: 1px;
}
.live-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--green);
    background: var(--green-soft);
    padding: 5px 14px;
    border-radius: 20px;
    border: 1px solid var(--border);
}
.live-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 6px var(--green);
    animation: pulse-dot 2s ease-in-out infinite;
}
@keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* ── Tabs ─────────────────────────────────────────────────────────── */
button[data-baseweb="tab"] {
    background: var(--panel) !important;
    color: var(--muted) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px 6px 0 0 !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
    margin-right: 3px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: var(--green-soft) !important;
    color: var(--green) !important;
    border-bottom: 2px solid var(--green) !important;
}
div[data-baseweb="tab-highlight"] { display: none !important; }
div[data-baseweb="tab-border"] { display: none !important; }

/* ── Hero ─────────────────────────────────────────────────────────── */
.hero {
    background: radial-gradient(ellipse at 30% 20%, var(--green-soft) 0%, var(--panel) 60%, var(--bg) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 36px 32px 28px;
    margin-bottom: 20px;
}
.hero-title {
    font-size: 1.7rem;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -0.03em;
    margin-bottom: 6px;
}
.hero-copy {
    font-size: 0.92rem;
    color: var(--text-2);
    max-width: 720px;
    line-height: 1.5;
    margin-bottom: 20px;
}
.hero-kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
}
.hero-kpi {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    text-align: center;
}
.hero-kpi .label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 4px;
}
.hero-kpi .value {
    font-size: 1.45rem;
    font-weight: 700;
    color: var(--green);
}
.hero-kpi .note {
    font-size: 0.7rem;
    color: var(--muted);
    margin-top: 3px;
}

/* ── st.metric cards ──────────────────────────────────────────────── */
[data-testid="stMetricValue"] {
    font-size: 1.45rem !important;
    font-weight: 700 !important;
    color: var(--text) !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: var(--muted) !important;
}
[data-testid="metric-container"] {
    background: linear-gradient(145deg, var(--panel) 0%, var(--panel-2) 100%) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 16px 18px !important;
}

/* ── Card ─────────────────────────────────────────────────────────── */
.card {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 12px;
}
.card .card-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 6px;
}
.card .card-body {
    font-size: 0.88rem;
    color: var(--text-2);
    line-height: 1.55;
}
.card .card-source {
    font-size: 0.72rem;
    color: var(--muted);
    margin-top: 8px;
}
.card-severity-critical { border-left: 4px solid #e74c3c; }
.card-severity-warning  { border-left: 4px solid var(--amber); }
.card-severity-info     { border-left: 4px solid var(--green); }

/* ── Enterprise strip ─────────────────────────────────────────────── */
.enterprise-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 0;
    margin: 16px 0;
    background: var(--beige);
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--beige-2);
}
.enterprise-strip .es-item {
    flex: 1 1 160px;
    padding: 16px 20px;
    text-align: center;
    border-right: 1px solid var(--beige-2);
}
.enterprise-strip .es-item:last-child { border-right: none; }
.enterprise-strip .es-label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #5c6b63;
    margin-bottom: 4px;
}
.enterprise-strip .es-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--beige-ink);
}

/* ── Beige board (analytical table) ───────────────────────────────── */
.beige-board {
    background: var(--beige);
    border-radius: 12px;
    padding: 20px 22px;
    margin: 14px 0;
    border: 1px solid var(--beige-2);
}
.beige-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
    color: var(--beige-ink);
}
.beige-table thead th {
    text-align: left;
    padding: 8px 10px;
    font-weight: 700;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #5c6b63;
    border-bottom: 2px solid var(--beige-2);
}
.beige-table tbody td {
    padding: 7px 10px;
    border-bottom: 1px solid var(--beige-2);
}
.beige-table tbody tr:hover { background: rgba(0,0,0,0.04); }
.beige-table tbody tr:last-child td { border-bottom: none; }

/* ── Graph board ──────────────────────────────────────────────────── */
.graph-board {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    margin: 14px 0;
}
.graph-label {
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--text-2);
    margin-bottom: 8px;
}

/* ── Boundary callout ─────────────────────────────────────────────── */
.boundary {
    background: var(--amber-soft);
    border: 1px solid var(--amber);
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 0.85rem;
    color: var(--beige);
    line-height: 1.5;
    margin: 10px 0;
}

/* ── Success box ──────────────────────────────────────────────────── */
.success-box {
    background: var(--green-soft);
    border: 1px solid var(--green);
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 0.85rem;
    color: var(--beige);
    line-height: 1.5;
    margin: 10px 0;
}

/* ── Analyst shell ────────────────────────────────────────────────── */
.analyst-shell {
    background: radial-gradient(ellipse at 40% 30%, var(--green-soft) 0%, var(--panel) 55%, var(--bg) 100%);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 36px 32px;
    margin-bottom: 18px;
}

/* ── Answer card ──────────────────────────────────────────────────── */
.answer-card {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px;
    margin: 14px 0;
}
.answer-label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--green);
    font-weight: 700;
    margin-bottom: 8px;
}
.answer-summary {
    font-size: 0.95rem;
    color: var(--text);
    line-height: 1.6;
    white-space: pre-wrap;
}
.answer-kpis {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin: 14px 0;
}
.answer-kpi {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 16px;
    text-align: center;
    min-width: 120px;
}
.answer-finding {
    background: var(--panel);
    border-left: 3px solid var(--green);
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    margin: 8px 0;
    font-size: 0.88rem;
    color: var(--text-2);
}
.answer-governance {
    font-size: 0.75rem;
    color: var(--muted);
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
}
.answer-refusal {
    background: var(--amber-soft);
    border: 1px solid var(--amber);
    border-radius: 10px;
    padding: 16px 20px;
    font-size: 0.9rem;
    color: var(--beige);
}

/* ── Entity chip ──────────────────────────────────────────────────── */
.entity-chip {
    display: inline-block;
    background: var(--green-soft);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 0.75rem;
    color: var(--green);
    font-weight: 600;
    margin: 2px 3px;
}
.governance-box {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    margin: 10px 0;
}

/* ── Sidebar ──────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] { background: var(--panel) !important; }
section[data-testid="stSidebar"] * { color: var(--text-2) !important; }
.sidebar-brand {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text) !important;
    margin-bottom: 2px;
}
.sidebar-sub {
    font-size: 0.8rem;
    color: var(--muted) !important;
    margin-bottom: 16px;
    line-height: 1.45;
}
.sidebar-heading {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted) !important;
    font-weight: 700;
    margin: 14px 0 6px;
}
.status-box {
    background: var(--panel-2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    margin: 6px 0;
}
.status-title {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--green) !important;
}
.status-detail {
    font-size: 0.72rem;
    color: var(--muted) !important;
    margin-top: 2px;
}

/* ── Footer ───────────────────────────────────────────────────────── */
.footer-line {
    text-align: center;
    font-size: 0.72rem;
    color: var(--muted);
    padding: 20px 0 10px;
    margin-top: 30px;
    border-top: 1px solid var(--border);
    letter-spacing: 0.04em;
}

/* ── Section rule / title ─────────────────────────────────────────── */
.section-rule {
    height: 1px;
    background: var(--border);
    margin: 24px 0 18px;
}
.section-title {
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 10px;
}

/* ── Ask processing spinner ───────────────────────────────────────── */
.ask-processing-wrap {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 0;
}
.ask-processing-wrap .spinner {
    width: 18px;
    height: 18px;
    border: 2px solid var(--border);
    border-top: 2px solid var(--green);
    border-radius: 50%;
    animation: spin-ask 0.8s linear infinite;
}
@keyframes spin-ask {
    to { transform: rotate(360deg); }
}

/* ── Misc refinements ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0 !important;
}
div[data-testid="stExpander"] {
    background: var(--panel-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
}
div[data-testid="stExpander"] summary span {
    font-weight: 600 !important;
    color: var(--text-2) !important;
}
.stButton > button[kind="primary"] { padding:6px 20px !important; font-size:0.82rem !important; }
</style>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

delivery_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_DELIVERY_SCORECARD")
logistics_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_LOGISTICS_SCORECARD")
country_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD ORDER BY COUNTRY")
risk_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT ORDER BY RISK_SIGNAL_COUNT DESC")
supplier_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC")
site_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC")
monthly_del_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_DELIVERY_TREND ORDER BY MONTH_START")
monthly_log_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_LOGISTICS_TREND ORDER BY MONTH_START")
dq_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.DATA_QUALITY_SCORECARD")
rel_gov_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.RELATIONSHIP_GOVERNANCE ORDER BY STATUS DESC, SUBJECT_ENTITY")
entity_cat_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_CATALOG ORDER BY SOURCE_SYSTEM, ENTITY_NAME")
entity_rel_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_RELATIONSHIPS")
metric_reg_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.METRIC_REGISTRY ORDER BY METRIC_ID")
product_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ANALYTICS.PRODUCT_CATEGORY_PERFORMANCE ORDER BY TOTAL_SALES DESC")
ship_mode_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ANALYTICS.SHIPPING_MODE_ANALYSIS ORDER BY SOURCE_SYSTEM, TOTAL_VALUE DESC")
top_cust_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.ANALYTICS.TOP_CUSTOMERS ORDER BY TOTAL_SALES DESC LIMIT 50")
eval_smoke_results = q("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS ORDER BY TESTED_AT DESC LIMIT 1) ORDER BY TEST_ID")
eval_smoke_summary = q("SELECT RUN_ID, COUNT(*) AS TESTS_EXECUTED, COUNT_IF(PASS_FLAG) AS TESTS_PASSED, COUNT_IF(NOT PASS_FLAG) AS TESTS_FAILED, ROUND(100.0 * COUNT_IF(PASS_FLAG) / NULLIF(COUNT(*), 0), 2) AS PASS_RATE_PCT FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS ORDER BY TESTED_AT DESC LIMIT 1) GROUP BY RUN_ID")
eval_bench_summary = q("SELECT RUN_ID, CATEGORY, COUNT(*) AS TESTS_EXECUTED, COUNT_IF(PASS_FLAG) AS TESTS_PASSED, COUNT_IF(NOT PASS_FLAG) AS TESTS_FAILED, ROUND(100.0 * COUNT_IF(PASS_FLAG) / NULLIF(COUNT(*), 0), 2) AS PASS_RATE_PCT FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS ORDER BY EVALUATED_AT DESC LIMIT 1) GROUP BY RUN_ID, CATEGORY ORDER BY CATEGORY")
eval_bench_defs = q("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK WHERE ACTIVE = TRUE ORDER BY TEST_ID")
eval_bench_results = q("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS ORDER BY EVALUATED_AT DESC LIMIT 1) ORDER BY TEST_ID")
country_del_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD ORDER BY ORDER_ITEM_COUNT DESC")
country_log_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_LOGISTICS_SCORECARD ORDER BY SHIPMENT_COUNT DESC")
geo_df = q("SELECT * FROM SUPPLYCHAINIQ_COCO.CORE.GEOGRAPHY_DIM ORDER BY SOURCE_COVERAGE, COUNTRY_NAME")


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACT KPIs
# ══════════════════════════════════════════════════════════════════════════════

# Delivery KPIs (DataCo)
otd = as_float(delivery_df.iloc[0]["ON_TIME_DELIVERY_PCT"]) if not delivery_df.empty else 0
delay = as_float(delivery_df.iloc[0]["DELAY_RATE_PCT"]) if not delivery_df.empty else 0
avg_delay_days = as_float(delivery_df.iloc[0]["AVG_DELIVERY_DELAY_DAYS"]) if not delivery_df.empty else 0
order_count = as_float(delivery_df.iloc[0]["ORDER_COUNT"]) if not delivery_df.empty else 0
order_item_count = as_float(delivery_df.iloc[0]["ORDER_ITEM_COUNT"]) if not delivery_df.empty else 0
total_sales = as_float(delivery_df.iloc[0]["TOTAL_SALES"]) if not delivery_df.empty else 0
total_profit = as_float(delivery_df.iloc[0]["TOTAL_PROFIT"]) if not delivery_df.empty else 0
profit_margin = as_float(delivery_df.iloc[0]["PROFIT_MARGIN_PCT"]) if not delivery_df.empty else 0
avg_order_val = total_sales / max(order_count, 1)

# Logistics KPIs (SCMS)
shipment_count = as_float(logistics_df.iloc[0]["SHIPMENT_COUNT"]) if not logistics_df.empty else 0
shipment_value = as_float(logistics_df.iloc[0]["TOTAL_SHIPMENT_VALUE"]) if not logistics_df.empty else 0
freight_cost = as_float(logistics_df.iloc[0]["TOTAL_FREIGHT_COST"]) if not logistics_df.empty else 0
logistics_rate = as_float(logistics_df.iloc[0]["LOGISTICS_COST_RATE_PCT"]) if not logistics_df.empty else 0
insurance_cost = as_float(logistics_df.iloc[0]["TOTAL_INSURANCE_COST"]) if not logistics_df.empty else 0
null_freight_pct = as_float(logistics_df.iloc[0]["NULL_FREIGHT_PCT"]) if not logistics_df.empty else 0

# Risk counts
high_risk_count = len(risk_df[risk_df["RISK_TIER"] == "HIGH"]) if not risk_df.empty else 0
medium_risk_count = len(risk_df[risk_df["RISK_TIER"] == "MEDIUM"]) if not risk_df.empty else 0
low_risk_count = len(risk_df[risk_df["RISK_TIER"] == "LOW"]) if not risk_df.empty else 0

# Geography counts
geo_both = 0
geo_dataco_only = 0
geo_scms_only = 0
if not geo_df.empty:
    cov_vc = geo_df["SOURCE_COVERAGE"].value_counts()
    geo_both = int(cov_vc.get("BOTH", 0))
    geo_dataco_only = int(cov_vc.get("DATACO_ONLY", 0))
    geo_scms_only = int(cov_vc.get("SCMS_ONLY", 0))

# Supplier/site counts
supplier_count = len(supplier_df) if not supplier_df.empty else 0
site_count = len(site_df) if not site_df.empty else 0

# Product/customer counts
product_count = len(product_df) if not product_df.empty else 0
customer_count = len(top_cust_df) if not top_cust_df.empty else 0

# Evaluation counts
total_smoke = len(eval_smoke_results) if not eval_smoke_results.empty else 0
total_bench = len(eval_bench_results) if not eval_bench_results.empty else 0
total_tests = total_smoke + total_bench
smoke_passed = 0
smoke_failed = 0
if not eval_smoke_results.empty and "PASS_FLAG" in eval_smoke_results.columns:
    smoke_passed = int(eval_smoke_results["PASS_FLAG"].sum())
    smoke_failed = int((~eval_smoke_results["PASS_FLAG"]).sum())
bench_passed = 0
bench_failed = 0
if not eval_bench_results.empty and "PASS_FLAG" in eval_bench_results.columns:
    bench_passed = int(eval_bench_results["PASS_FLAG"].sum())
    bench_failed = int((~eval_bench_results["PASS_FLAG"]).sum())
all_passed = smoke_passed + bench_passed
all_failed = smoke_failed + bench_failed
pass_rate = (all_passed / max(total_tests, 1)) * 100

# Belize outlier
belize_row = country_log_df[country_log_df["COUNTRY"] == "Belize"] if not country_log_df.empty else None
belize_rate = as_float(belize_row.iloc[0]["LOGISTICS_COST_RATE_PCT"]) if belize_row is not None and not belize_row.empty else 0


# ══════════════════════════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════════════════════════

_h2 = '<div class="topbar"> <div class="brand-row"> <div class="brand-mark">🚚</div> <div> <div class="brand-name">SupplyChainIQ</div> <div class="brand-sub">Powered by CoCo</div> </div> </div> <div class="live-pill"><span class="live-dot"></span> LIVE &middot; SNOWFLAKE</div> </div>'
st.markdown(_h2, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown('<div class="sidebar-brand">SupplyChainIQ</div><div class="sidebar-sub" style="margin-top:2px;margin-bottom:6px;">Powered by CoCo</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sidebar-sub">Governed supply-chain operating intelligence across DataCo and SCMS.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-heading">Data domains</div>', unsafe_allow_html=True)
    st.markdown("**DataCo** — Orders, customers, products, sales, delivery (2015-2018)")
    st.markdown("**SCMS** — Shipments, suppliers, sites, freight, insurance (2006-2015)")
    st.divider()
    st.markdown('<div class="sidebar-heading">Data boundary</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="boundary">DataCo and SCMS are independent source systems with no row-level join key. '
        'Cross-source comparison at country aggregate only.</div>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<div class="sidebar-heading">Platform</div>', unsafe_allow_html=True)
    _h3 = '<div class="status-box"><div class="status-title">&bull; Semantic layer</div><div class="status-detail">SUPPLYCHAINIQ_COCO_SV</div></div> <div class="status-box"><div class="status-title">&bull; Analytics agent</div><div class="status-detail">SUPPLYCHAINIQ_COCO_AGENT</div></div> <div class="status-box"><div class="status-title">&bull; Governance</div><div class="status-detail">Ontology + metric + evaluation controls</div></div>'
    st.markdown(_h3, unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="sidebar-heading">Quick stats</div>', unsafe_allow_html=True)
    st.markdown(f"**{int(order_item_count):,}** DataCo order items")
    st.markdown(f"**{int(shipment_count):,}** SCMS shipments")
    st.markdown(f"**{len(geo_df)}** countries tracked")
    st.markdown(f"**{supplier_count}** suppliers")
    st.markdown(f"**{site_count}** manufacturing sites")
    st.markdown(f"**{total_tests}** evaluation tests")
    st.divider()
    st.markdown(f'<div style="font-size:0.72rem;color:var(--muted);">Pass rate: {pass_rate:.0f}% ({all_passed}/{total_tests})</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tower_tab, signals_tab, country_tab, supplier_tab, trends_tab, analyst_tab, gov_tab, disagree_tab, eval_tab = st.tabs([
    "Control Tower",
    "Decision Signals",
    "Country Intel",
    "Supplier / Site",
    "Trends",
    "Analyst",
    "Governance",
    "Disagreement",
    "Evaluation",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONTROL TOWER
# ══════════════════════════════════════════════════════════════════════════════
with tower_tab:

    # ── Hero ──────────────────────────────────────────────────────────────────
    _h4 = f'<div class="hero"> <div class="hero-title">Supply Chain Control Tower</div> <div class="hero-copy"> Two-source governed intelligence across DataCo e-commerce operations (2015-2018) and SCMS pharmaceutical logistics (2006-2015). All metrics governed by the semantic layer with full source attribution and outlier-inclusion policy. </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">On-Time Delivery</div> <div class="value">{otd:.1f}%</div> <div class="note">DataCo</div> </div> <div class="hero-kpi"> <div class="label">Delay Rate</div> <div class="value">{delay:.1f}%</div> <div class="note">DataCo</div> </div> <div class="hero-kpi"> <div class="label">Total Sales</div> <div class="value">${fmt_val(total_sales)}</div> <div class="note">DataCo</div> </div> <div class="hero-kpi"> <div class="label">Logistics Rate</div> <div class="value">{logistics_rate:.1f}%</div> <div class="note">SCMS</div> </div> </div> </div>'
    st.markdown(_h4, unsafe_allow_html=True)

    # ── Delivery Health ───────────────────────────────────────────────────────
    render_section("Delivery Health", chip="DataCo")

    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("On-Time Delivery", f"{otd:.2f}%")
    d2.metric("Delay Rate", f"{delay:.2f}%")
    d3.metric("Avg Delay", f"{avg_delay_days:.2f} days")
    d4.metric("Distinct Orders", f"{order_count:,.0f}")
    d5.metric("Order Items", f"{order_item_count:,.0f}")

    if delay > 50:
        _h5 = f'<div class="boundary"> <strong>Alert:</strong> Delay rate is {delay:.1f}% — more than half of non-cancelled order items were delivered late. This is a significant operational risk requiring investigation. </div>'
        st.markdown(_h5, unsafe_allow_html=True)

    # ── Commercial Performance ────────────────────────────────────────────────
    render_section("Commercial Performance", chip="DataCo")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Sales", f"${total_sales:,.0f}")
    c2.metric("Total Profit", f"${total_profit:,.0f}")
    c3.metric("Profit Margin", f"{profit_margin:.2f}%")
    c4.metric("Avg Order Value", f"${avg_order_val:,.0f}")

    # Enterprise strip — commercial KPIs
    render_kpi_strip([
        ("Total Sales", f"${fmt_val(total_sales)}"),
        ("Total Profit", f"${fmt_val(total_profit)}"),
        ("Profit Margin", f"{profit_margin:.1f}%"),
        ("Avg Order Value", f"${avg_order_val:,.0f}"),
        ("Orders", f"{order_count:,.0f}"),
        ("Order Items", f"{order_item_count:,.0f}"),
    ])

    # ── Product Category Breakdown ────────────────────────────────────────────
    render_section("Product Category Performance", chip="DataCo")

    if not product_df.empty:
        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("Product Categories", f"{product_count}")
        top_cat = product_df.iloc[0]["CATEGORY_NAME"] if "CATEGORY_NAME" in product_df.columns else "N/A"
        top_cat_sales = as_float(product_df.iloc[0]["TOTAL_SALES"]) if not product_df.empty else 0
        pc2.metric("Top Category", str(top_cat))
        pc3.metric("Top Category Sales", fmt_usd(top_cat_sales))

        render_beige_board(
            "Product Category Performance",
            product_df,
            subtitle="Sales, profit, and order volume by product category — DataCo source",
        )

        if "CATEGORY_NAME" in product_df.columns and "TOTAL_SALES" in product_df.columns:
            st.markdown('<div class="graph-board"><div class="graph-label">Sales by Product Category</div></div>', unsafe_allow_html=True)
            chart_prod = product_df.head(15).set_index("CATEGORY_NAME")[["TOTAL_SALES"]]
            st.bar_chart(chart_prod)

    # ── Top Customers ─────────────────────────────────────────────────────────
    render_section("Top Customers", chip="DataCo")

    if not top_cust_df.empty:
        tc1, tc2 = st.columns(2)
        tc1.metric("Customers Shown", f"{len(top_cust_df)}")
        top_cust_sales = as_float(top_cust_df["TOTAL_SALES"].sum())
        tc2.metric("Combined Sales", fmt_usd(top_cust_sales))
        render_beige_board(
            "Top 50 Customers by Sales",
            top_cust_df,
            subtitle="Top customers ranked by total sales — DataCo source",
            max_rows=50,
        )

    # ── Shipping Mode Analysis ────────────────────────────────────────────────
    render_section("Shipping Mode Analysis", chip="Both")

    if not ship_mode_df.empty:
        render_beige_board(
            "Shipping Mode Performance",
            ship_mode_df,
            subtitle="Shipping mode metrics across both source systems",
        )

    # ── Logistics Performance ─────────────────────────────────────────────────
    render_section("Logistics Performance", chip="SCMS")

    l1, l2, l3, l4, l5 = st.columns(5)
    l1.metric("Shipments", f"{shipment_count:,.0f}")
    l2.metric("Shipment Value", f"${shipment_value:,.0f}")
    l3.metric("Freight Cost", f"${freight_cost:,.0f}")
    l4.metric("Logistics Rate", f"{logistics_rate:.2f}%")
    l5.metric("Insurance", f"${insurance_cost:,.0f}")

    # Logistics enterprise strip
    render_kpi_strip([
        ("Shipments", f"{shipment_count:,.0f}"),
        ("Shipment Value", fmt_usd(shipment_value)),
        ("Freight Cost", fmt_usd(freight_cost)),
        ("Insurance Cost", fmt_usd(insurance_cost)),
        ("Logistics Rate", f"{logistics_rate:.1f}%"),
        ("Null Freight %", f"{null_freight_pct:.0f}%"),
    ])

    # ── Data Quality & Trust ──────────────────────────────────────────────────
    render_section("Data Quality & Trust")

    dq1, dq2 = st.columns(2)
    with dq1:
        _h6 = f'<div class="card card-severity-info"> <div class="card-title">DataCo Data Quality</div> <div class="card-body"> <strong>{int(order_item_count):,}</strong> order items loaded.<br> Key fields (sales, dates, delivery status) have <strong>0% null rate</strong>.<br> Full coverage of order, customer, product, and sales dimensions. </div> <div class="card-source">Source: DATA_QUALITY_SCORECARD &middot; DataCo</div> </div>'
        st.markdown(_h6, unsafe_allow_html=True)
    with dq2:
        _h7 = f'<div class="card card-severity-warning"> <div class="card-title">SCMS Data Quality</div> <div class="card-body"> <strong>{int(shipment_count):,}</strong> shipments loaded.<br> Freight cost has a <strong>{null_freight_pct:.0f}% NULL rate</strong>.<br> All freight-based metrics understate true costs. This is a known constraint. </div> <div class="card-source">Source: DATA_QUALITY_SCORECARD &middot; SCMS</div> </div>'
        st.markdown(_h7, unsafe_allow_html=True)

    render_beige_board("Data Quality Scorecard", dq_df, subtitle="Coverage and completeness across source systems")

    _h8 = f'<div class="boundary"> <strong>Data coverage note:</strong> SCMS freight cost has a {null_freight_pct:.0f}% NULL rate. All freight-based logistics metrics (logistics cost rate, freight per shipment) understate true costs. This is a known data-quality constraint, not an error. </div>'
    st.markdown(_h8, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DECISION SIGNALS
# ══════════════════════════════════════════════════════════════════════════════
with signals_tab:

    _h9 = f'<div class="hero"> <div class="hero-title">Decision Signals</div> <div class="hero-copy"> Operational signals surfaced from governed analytics. Each signal is grounded in semantic-layer metrics with full source attribution. Signals are ranked by severity. </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">Delay Rate</div> <div class="value">{delay:.1f}%</div> <div class="note">{"CRITICAL" if delay > 50 else "NORMAL"}</div> </div> <div class="hero-kpi"> <div class="label">High-Risk Countries</div> <div class="value">{high_risk_count}</div> <div class="note">countries</div> </div> <div class="hero-kpi"> <div class="label">Belize Anomaly</div> <div class="value">{belize_rate:.0f}%</div> <div class="note">logistics rate</div> </div> <div class="hero-kpi"> <div class="label">Null Freight</div> <div class="value">{null_freight_pct:.0f}%</div> <div class="note">SCMS gap</div> </div> </div> </div>'
    st.markdown(_h9, unsafe_allow_html=True)

    # ── Signal 1: Delivery Risk ───────────────────────────────────────────────
    render_section("Signal 1 — Delivery Risk")

    severity_class = "card-severity-critical" if delay > 50 else "card-severity-info"
    severity_word = "CRITICAL" if delay > 50 else "NORMAL"
    render_signal_card(
        f"Delivery Risk — {severity_word}",
        f"""{delay:.1f}% of non-cancelled DataCo order items were delivered late.
Enterprise on-time delivery is {otd:.1f}%. Average delay is {avg_delay_days:.1f} days.
{"This exceeds the 50% threshold and warrants immediate investigation." if delay > 50 else "Within acceptable operational bounds."}""",
        "Source: ENTERPRISE_DELIVERY_SCORECARD | Metric: ON_TIME_DELIVERY_PCT (governed) | DataCo",
        severity="critical" if delay > 50 else "info",
    )

    if not monthly_del_df.empty:
        st.markdown('<div class="graph-board"><div class="graph-label">OTD Trend Over Time (context for delivery risk)</div></div>', unsafe_allow_html=True)
        st.line_chart(monthly_del_df.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=250)

    # ── Signal 2: Logistics Cost Anomaly ──────────────────────────────────────
    render_section("Signal 2 — Logistics Cost Anomaly")

    render_signal_card(
        f"Logistics Cost Anomaly — Belize ({belize_rate:.0f}%)",
        f"""Belize logistics cost rate is {belize_rate:.0f}% — freight cost exceeds shipment value
by approximately 3x. This is real data, not an error. The governed outlier-inclusion policy requires
this data point to be included in all analyses and surfaced explicitly rather than silently excluded.
Investigate root cause before taking action.""",
        "Source: COUNTRY_LOGISTICS_SCORECARD | Metric: LOGISTICS_COST_RATE_PCT (governed) | SCMS",
        severity="warning",
    )

    if not country_log_df.empty:
        top_logistic_countries = country_log_df.head(10)
        if "COUNTRY" in top_logistic_countries.columns and "LOGISTICS_COST_RATE_PCT" in top_logistic_countries.columns:
            st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Countries by Logistics Cost Rate</div></div>', unsafe_allow_html=True)
            st.bar_chart(top_logistic_countries.set_index("COUNTRY")[["LOGISTICS_COST_RATE_PCT"]])

    # ── Signal 3: Country Risk ────────────────────────────────────────────────
    render_section("Signal 3 — Country Risk")

    risk_severity = "critical" if high_risk_count > 5 else "warning"
    render_signal_card(
        f"Country Risk — {high_risk_count} HIGH-Tier Countries",
        f"""{high_risk_count} countries flagged as HIGH risk based on 2+ risk signals above median thresholds
(delay rate, logistics cost rate, freight cost). An additional {medium_risk_count} countries are MEDIUM risk
and {low_risk_count} are LOW risk. Risk assessment is computed at country-aggregate level — the only
defensible cross-source grain.""",
        "Source: COUNTRY_RISK_ASSESSMENT | Benchmark: median-relative thresholds | Both sources",
        severity=risk_severity,
    )

    if not risk_df.empty:
        high_risk = risk_df[risk_df["RISK_TIER"] == "HIGH"]
        if not high_risk.empty:
            render_beige_board(
                "HIGH-Risk Countries",
                high_risk,
                subtitle="Countries with 2+ signals above median",
            )

    # ── Signal 4: Data Quality Gap ────────────────────────────────────────────
    render_section("Signal 4 — Data Quality Gap")

    render_signal_card(
        f"Data Quality Gap — SCMS Null Freight ({null_freight_pct:.0f}%)",
        f"""{null_freight_pct:.0f}% of SCMS shipment records have NULL freight cost. This means:
- Total freight cost ({fmt_usd(freight_cost)}) is understated
- Logistics cost rate ({logistics_rate:.1f}%) is understated
- Per-country freight comparisons may be skewed by uneven NULL distribution
All freight-based metrics should be interpreted as lower-bound estimates.""",
        "Source: ENTERPRISE_LOGISTICS_SCORECARD | NULL_FREIGHT_PCT | SCMS",
        severity="warning",
    )

    # ── Signal 5: Supplier Concentration ──────────────────────────────────────
    render_section("Signal 5 — Supplier Concentration")

    if not supplier_df.empty:
        top5_val = as_float(supplier_df.head(5)["SHIPMENT_VALUE_USD"].sum())
        total_val = as_float(supplier_df["SHIPMENT_VALUE_USD"].sum())
        top5_pct = (top5_val / max(total_val, 1)) * 100
        render_signal_card(
            f"Supplier Concentration — Top 5 = {top5_pct:.1f}% of Value",
            f"""The top 5 suppliers by shipment value account for {top5_pct:.1f}% of total SCMS
shipment value (${fmt_val(top5_val)} of ${fmt_val(total_val)}). This level of concentration
{"represents significant vendor dependency risk." if top5_pct > 50 else "is within acceptable bounds."}""",
            f"Source: SUPPLIER_SCORECARD | {supplier_count} total suppliers | SCMS",
            severity="warning" if top5_pct > 50 else "info",
        )

        top_freight_sup = supplier_df.nlargest(5, "LOGISTICS_COST_RATE_PCT")
        render_beige_board(
            "Top 5 Suppliers by Logistics Cost Rate",
            top_freight_sup,
            subtitle="Highest cost-rate suppliers — may indicate pricing or routing inefficiency",
        )

    # ── Signal 6: Non-Computable Metrics ──────────────────────────────────────
    render_section("Signal 6 — Non-Computable Metrics")

    render_signal_card(
        "Non-Computable Metrics",
        """The following standard supply chain KPIs <strong>cannot be computed</strong> from available data:<br>
&bull; <strong>Fill Rate</strong> — no partial-fill or demand-vs-fulfilled data<br>
&bull; <strong>Days of Inventory (DOI)</strong> — no inventory snapshot data<br>
&bull; <strong>Inventory Turnover</strong> — no inventory on-hand data<br>
&bull; <strong>Return Rate</strong> — no returns data<br>
&bull; <strong>Perfect Order Rate</strong> — multiple quality dimensions not captured<br>
The agent is trained to decline these queries with an explanation rather than hallucinate values.""",
        "Source: METRIC_REGISTRY | Governance: governed refusal policy",
        severity="info",
    )

    # ── Signal 7: Two-Island Constraint ───────────────────────────────────────
    render_section("Signal 7 — Architectural Constraint")

    render_signal_card(
        "Two-Island Constraint Active",
        """DataCo and SCMS share <strong>no row-level join key</strong>. The agent enforces this
constraint by refusing queries that attempt to join order-level DataCo data with shipment-level SCMS
data. The only valid cross-source analysis is at <strong>country-aggregate level</strong>, where
country name serves as the shared dimension.""",
        "Source: ONTOLOGY.RELATIONSHIP_GOVERNANCE | Governance: two-island constraint",
        severity="info",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — COUNTRY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
with country_tab:

    _h10 = f'<div class="hero"> <div class="hero-title">Country Intelligence</div> <div class="hero-copy"> Cross-source analysis at the country-aggregate level — the only defensible cross-source join grain. Country is the shared dimension between DataCo and SCMS. </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">Total Countries</div> <div class="value">{len(geo_df)}</div> <div class="note">All sources</div> </div> <div class="hero-kpi"> <div class="label">Both Sources</div> <div class="value">{geo_both}</div> <div class="note">DataCo + SCMS</div> </div> <div class="hero-kpi"> <div class="label">High Risk</div> <div class="value">{high_risk_count}</div> <div class="note">countries</div> </div> <div class="hero-kpi"> <div class="label">DataCo Only</div> <div class="value">{geo_dataco_only}</div> <div class="note">countries</div> </div> </div> </div>'
    st.markdown(_h10, unsafe_allow_html=True)

    sub_score, sub_risk, sub_cov = st.tabs(["Scorecards", "Risk Assessment", "Coverage"])

    # ── Scorecards ────────────────────────────────────────────────────────────
    with sub_score:
        render_section("Cross-Source Country Scorecard")

        if not country_df.empty:
            cov_opts = sorted(country_df["SOURCE_COVERAGE"].dropna().unique().tolist())
            sel_cov = st.multiselect("Filter by source coverage", cov_opts, default=cov_opts, key="ctry_cov_flt")
            filtered_cs = country_df[country_df["SOURCE_COVERAGE"].isin(sel_cov)] if sel_cov else country_df
            st.markdown(
                f'<div style="color:var(--muted);font-size:0.82rem;margin-bottom:8px;">{len(filtered_cs)} countries shown</div>',
                unsafe_allow_html=True,
            )
            render_beige_board(
                "Country Cross-Source Scorecard",
                filtered_cs,
                subtitle="DataCo columns: OTD, delay, sales, profit. SCMS columns: shipments, freight, logistics rate. NULL = no data from that source.",
            )

        render_section("Country Delivery Scorecard", chip="DataCo")

        if not country_del_df.empty:
            cd1, cd2, cd3 = st.columns(3)
            cd1.metric("Countries (DataCo)", f"{len(country_del_df)}")
            total_del_orders = as_float(country_del_df["ORDER_ITEM_COUNT"].sum())
            cd2.metric("Total Order Items", f"{total_del_orders:,.0f}")
            if "TOTAL_SALES" in country_del_df.columns:
                total_del_sales = as_float(country_del_df["TOTAL_SALES"].sum())
                cd3.metric("Total Sales", fmt_usd(total_del_sales))

        render_beige_board(
            "Delivery by Country",
            country_del_df,
            subtitle="Order items, OTD, delay rate, sales, profit by country — DataCo source",
        )

        render_section("Country Logistics Scorecard", chip="SCMS")

        if not country_log_df.empty:
            cl1, cl2, cl3 = st.columns(3)
            cl1.metric("Countries (SCMS)", f"{len(country_log_df)}")
            total_log_shipments = as_float(country_log_df["SHIPMENT_COUNT"].sum())
            cl2.metric("Total Shipments", f"{total_log_shipments:,.0f}")
            if "FREIGHT_COST_USD" in country_log_df.columns:
                total_log_freight = as_float(country_log_df["FREIGHT_COST_USD"].sum())
                cl3.metric("Total Freight", fmt_usd(total_log_freight))

        render_beige_board(
            "Logistics by Country",
            country_log_df,
            subtitle="Shipments, freight, logistics cost rate by country — SCMS source",
        )

    # ── Risk Assessment ───────────────────────────────────────────────────────
    with sub_risk:
        render_section("Country Risk Assessment")

        if not risk_df.empty:
            tier_opts = sorted(risk_df["RISK_TIER"].dropna().unique().tolist())
            sel_tier = st.multiselect("Risk tier filter", tier_opts, default=tier_opts, key="risk_tier_flt")
            filtered_risk = risk_df[risk_df["RISK_TIER"].isin(sel_tier)] if sel_tier else risk_df

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("HIGH Risk", f"{high_risk_count} countries")
            r2.metric("MEDIUM Risk", f"{medium_risk_count} countries")
            r3.metric("LOW Risk", f"{low_risk_count} countries")
            r4.metric("Total Assessed", f"{len(risk_df)} countries")

            render_beige_board(
                "Risk Assessment",
                filtered_risk,
                subtitle="Risk = 2+ signals above median (delay rate, logistics rate, freight cost). Belize is intentionally included — outlier policy prohibits silent exclusion.",
            )

            _h11 = '<div class="boundary"> <strong>Risk methodology:</strong> Countries are assessed based on deviation from median values across three dimensions: delay rate (DataCo), logistics cost rate (SCMS), and absolute freight cost (SCMS). A country is HIGH risk if 2+ signals exceed the median. The Belize outlier (311% logistics rate) is included per outlier-inclusion policy. </div>'
            st.markdown(_h11, unsafe_allow_html=True)
        else:
            st.info("No risk assessment data available.")

    # ── Coverage ──────────────────────────────────────────────────────────────
    with sub_cov:
        render_section("Geographic Source Coverage")

        if not geo_df.empty:
            gc1, gc2, gc3, gc4 = st.columns(4)
            gc1.metric("Total Countries", len(geo_df))
            gc2.metric("BOTH Sources", geo_both)
            gc3.metric("DataCo Only", geo_dataco_only)
            gc4.metric("SCMS Only", geo_scms_only)

            cov_summary = geo_df.groupby("SOURCE_COVERAGE").size().reset_index(name="COUNT")
            st.markdown('<div class="graph-board"><div class="graph-label">Countries by Source Coverage</div></div>', unsafe_allow_html=True)
            st.bar_chart(cov_summary.set_index("SOURCE_COVERAGE"))

            render_beige_board(
                "Full Country List",
                geo_df,
                subtitle="All countries with source system coverage mapping",
            )

            _h12 = '''<div class="success-box"> <strong>Coverage note:</strong> Countries tagged "BOTH" have data from both DataCo and SCMS, enabling cross-source aggregate comparison. Countries with single-source coverage can only be analyzed within that source's metrics. </div>'''
            st.markdown(_h12, unsafe_allow_html=True)
        else:
            st.info("No geography data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SUPPLIER / SITE
# ══════════════════════════════════════════════════════════════════════════════
with supplier_tab:

    _h13 = f'<div class="hero"> <div class="hero-title">Supplier &amp; Site Intelligence</div> <div class="hero-copy"> SCMS pharmaceutical procurement analytics — vendor performance, manufacturing site metrics, and logistics cost analysis. All data from SCMS source only. </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">Suppliers</div> <div class="value">{supplier_count}</div> <div class="note">SCMS</div> </div> <div class="hero-kpi"> <div class="label">Mfg Sites</div> <div class="value">{site_count}</div> <div class="note">SCMS</div> </div> <div class="hero-kpi"> <div class="label">Shipment Value</div> <div class="value">${fmt_val(shipment_value)}</div> <div class="note">total</div> </div> <div class="hero-kpi"> <div class="label">Freight Cost</div> <div class="value">${fmt_val(freight_cost)}</div> <div class="note">total</div> </div> </div> </div>'
    st.markdown(_h13, unsafe_allow_html=True)

    sub_sup, sub_site = st.tabs(["Supplier Scorecard", "Manufacturing Sites"])

    # ── Supplier Scorecard ────────────────────────────────────────────────────
    with sub_sup:
        render_section("Supplier Scorecard", chip="SCMS")

        if not supplier_df.empty:
            top_n_sup = st.slider(
                "Suppliers to display", 5, max(supplier_count, 5), min(20, supplier_count), key="sup_slider"
            )
            shown_sup = supplier_df.head(top_n_sup)

            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Total Suppliers", f"{supplier_count}")
            sm2.metric("Total Shipment Value", fmt_usd(as_float(supplier_df["SHIPMENT_VALUE_USD"].sum())))
            sm3.metric("Total Freight Cost", fmt_usd(as_float(supplier_df["FREIGHT_COST_USD"].sum())))
            sm4.metric("Avg Logistics Rate", fmt_pct(as_float(supplier_df["LOGISTICS_COST_RATE_PCT"].mean())))

            render_kpi_strip([
                ("Suppliers", f"{supplier_count}"),
                ("Shipment Value", fmt_usd(as_float(supplier_df["SHIPMENT_VALUE_USD"].sum()))),
                ("Freight Cost", fmt_usd(as_float(supplier_df["FREIGHT_COST_USD"].sum()))),
                ("Avg Logistics Rate", fmt_pct(as_float(supplier_df["LOGISTICS_COST_RATE_PCT"].mean()))),
            ])

            render_beige_board(
                "Supplier Performance",
                shown_sup,
                subtitle=f"Top {top_n_sup} suppliers by shipment value",
            )

            st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Suppliers by Shipment Value</div></div>', unsafe_allow_html=True)
            chart_sup = supplier_df.head(10).set_index("SUPPLIER")[["SHIPMENT_VALUE_USD"]]
            st.bar_chart(chart_sup)

            if "LOGISTICS_COST_RATE_PCT" in supplier_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Suppliers by Logistics Cost Rate</div></div>', unsafe_allow_html=True)
                top_rate_sup = supplier_df.nlargest(10, "LOGISTICS_COST_RATE_PCT").set_index("SUPPLIER")[["LOGISTICS_COST_RATE_PCT"]]
                st.bar_chart(top_rate_sup)
        else:
            st.info("No supplier data available.")

    # ── Manufacturing Sites ───────────────────────────────────────────────────
    with sub_site:
        render_section("Manufacturing Site Scorecard", chip="SCMS")

        if not site_df.empty:
            top_n_site = st.slider(
                "Sites to display", 5, max(site_count, 5), min(20, site_count), key="site_slider"
            )
            shown_site = site_df.head(top_n_site)

            si1, si2, si3, si4 = st.columns(4)
            si1.metric("Total Sites", f"{site_count}")
            si2.metric("Total Shipment Value", fmt_usd(as_float(site_df["SHIPMENT_VALUE_USD"].sum())))
            si3.metric("Total Freight Cost", fmt_usd(as_float(site_df["FREIGHT_COST_USD"].sum())))
            si4.metric("Avg Logistics Rate", fmt_pct(as_float(site_df["LOGISTICS_COST_RATE_PCT"].mean())))

            render_kpi_strip([
                ("Sites", f"{site_count}"),
                ("Shipment Value", fmt_usd(as_float(site_df["SHIPMENT_VALUE_USD"].sum()))),
                ("Freight Cost", fmt_usd(as_float(site_df["FREIGHT_COST_USD"].sum()))),
                ("Avg Logistics Rate", fmt_pct(as_float(site_df["LOGISTICS_COST_RATE_PCT"].mean()))),
            ])

            render_beige_board(
                "Manufacturing Site Performance",
                shown_site,
                subtitle=f"Top {top_n_site} sites by shipment value",
            )

            st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Sites by Shipment Value</div></div>', unsafe_allow_html=True)
            chart_site = site_df.head(10).set_index("SITE_NAME")[["SHIPMENT_VALUE_USD"]]
            st.bar_chart(chart_site)

            if "LOGISTICS_COST_RATE_PCT" in site_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Sites by Logistics Cost Rate</div></div>', unsafe_allow_html=True)
                top_rate_site = site_df.nlargest(10, "LOGISTICS_COST_RATE_PCT").set_index("SITE_NAME")[["LOGISTICS_COST_RATE_PCT"]]
                st.bar_chart(top_rate_site)
        else:
            st.info("No site data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — TRENDS
# ══════════════════════════════════════════════════════════════════════════════
with trends_tab:

    _h14 = '<div class="hero"> <div class="hero-title">Trend Analysis</div> <div class="hero-copy"> Monthly operational trends across delivery performance, commercial metrics, and logistics cost dynamics. Source-attributed and time-aligned. </div> </div>'
    st.markdown(_h14, unsafe_allow_html=True)

    sub_del_trend, sub_com_trend, sub_log_trend = st.tabs([
        "DataCo Delivery", "DataCo Commercial", "SCMS Logistics"
    ])

    # ── DataCo Delivery Trends ────────────────────────────────────────────────
    with sub_del_trend:
        render_section("Monthly Delivery Trends", chip="DataCo")

        if not monthly_del_df.empty:
            td1, td2, td3 = st.columns(3)
            td1.metric("Months Covered", f"{len(monthly_del_df)}")
            if "ON_TIME_DELIVERY_PCT" in monthly_del_df.columns:
                avg_otd = as_float(monthly_del_df["ON_TIME_DELIVERY_PCT"].mean())
                td2.metric("Avg Monthly OTD", f"{avg_otd:.1f}%")
            if "DELAY_RATE_PCT" in monthly_del_df.columns:
                avg_delay_m = as_float(monthly_del_df["DELAY_RATE_PCT"].mean())
                td3.metric("Avg Monthly Delay", f"{avg_delay_m:.1f}%")

            st.markdown('<div class="graph-board"><div class="graph-label">On-Time Delivery % and Delay Rate %</div></div>', unsafe_allow_html=True)
            st.line_chart(monthly_del_df.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=320)

            if "ORDER_ITEM_COUNT" in monthly_del_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Monthly Order Item Count</div></div>', unsafe_allow_html=True)
                st.bar_chart(monthly_del_df.set_index("MONTH_START")[["ORDER_ITEM_COUNT"]], height=260)

            if "AVG_DELIVERY_DELAY_DAYS" in monthly_del_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Average Delivery Delay (Days)</div></div>', unsafe_allow_html=True)
                st.line_chart(monthly_del_df.set_index("MONTH_START")[["AVG_DELIVERY_DELAY_DAYS"]], height=260)

            render_beige_board(
                "Delivery Trend Data",
                monthly_del_df,
                subtitle="Monthly delivery metrics — DataCo source",
            )
        else:
            st.info("No delivery trend data available.")

    # ── DataCo Commercial Trends ──────────────────────────────────────────────
    with sub_com_trend:
        render_section("Monthly Commercial Trends", chip="DataCo")

        if not monthly_del_df.empty:
            tc1, tc2, tc3 = st.columns(3)
            if "TOTAL_SALES" in monthly_del_df.columns:
                avg_monthly_sales = as_float(monthly_del_df["TOTAL_SALES"].mean())
                tc1.metric("Avg Monthly Sales", fmt_usd(avg_monthly_sales))
            if "TOTAL_PROFIT" in monthly_del_df.columns:
                avg_monthly_profit = as_float(monthly_del_df["TOTAL_PROFIT"].mean())
                tc2.metric("Avg Monthly Profit", fmt_usd(avg_monthly_profit))
            if "PROFIT_MARGIN_PCT" in monthly_del_df.columns:
                avg_margin = as_float(monthly_del_df["PROFIT_MARGIN_PCT"].mean())
                tc3.metric("Avg Monthly Margin", f"{avg_margin:.1f}%")

            if "TOTAL_SALES" in monthly_del_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Monthly Sales</div></div>', unsafe_allow_html=True)
                st.bar_chart(monthly_del_df.set_index("MONTH_START")[["TOTAL_SALES"]], height=280)

            if "TOTAL_PROFIT" in monthly_del_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Monthly Profit</div></div>', unsafe_allow_html=True)
                st.bar_chart(monthly_del_df.set_index("MONTH_START")[["TOTAL_PROFIT"]], height=280)

            if "PROFIT_MARGIN_PCT" in monthly_del_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Monthly Profit Margin %</div></div>', unsafe_allow_html=True)
                st.line_chart(monthly_del_df.set_index("MONTH_START")[["PROFIT_MARGIN_PCT"]], height=260)

            render_beige_board(
                "Commercial Trend Data",
                monthly_del_df,
                subtitle="Monthly commercial metrics — DataCo source",
            )
        else:
            st.info("No commercial trend data available.")

    # ── SCMS Logistics Trends ─────────────────────────────────────────────────
    with sub_log_trend:
        render_section("Monthly Logistics Trends", chip="SCMS")

        if not monthly_log_df.empty:
            tl1, tl2, tl3 = st.columns(3)
            tl1.metric("Months Covered", f"{len(monthly_log_df)}")
            if "FREIGHT_COST_USD" in monthly_log_df.columns:
                avg_freight_m = as_float(monthly_log_df["FREIGHT_COST_USD"].mean())
                tl2.metric("Avg Monthly Freight", fmt_usd(avg_freight_m))
            if "LOGISTICS_COST_RATE_PCT" in monthly_log_df.columns:
                avg_log_rate_m = as_float(monthly_log_df["LOGISTICS_COST_RATE_PCT"].mean())
                tl3.metric("Avg Monthly Log Rate", f"{avg_log_rate_m:.1f}%")

            if "FREIGHT_COST_USD" in monthly_log_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Freight Cost (USD)</div></div>', unsafe_allow_html=True)
                st.line_chart(monthly_log_df.set_index("MONTH_START")[["FREIGHT_COST_USD"]], height=300)

            if "LOGISTICS_COST_RATE_PCT" in monthly_log_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Logistics Cost Rate %</div></div>', unsafe_allow_html=True)
                st.line_chart(monthly_log_df.set_index("MONTH_START")[["LOGISTICS_COST_RATE_PCT"]], height=260)

            if "SHIPMENT_COUNT" in monthly_log_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Shipment Count</div></div>', unsafe_allow_html=True)
                st.bar_chart(monthly_log_df.set_index("MONTH_START")[["SHIPMENT_COUNT"]], height=260)

            if "SHIPMENT_VALUE_USD" in monthly_log_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Shipment Value (USD)</div></div>', unsafe_allow_html=True)
                st.bar_chart(monthly_log_df.set_index("MONTH_START")[["SHIPMENT_VALUE_USD"]], height=260)

            render_beige_board(
                "Logistics Trend Data",
                monthly_log_df,
                subtitle="Monthly logistics metrics — SCMS source",
            )
        else:
            st.info("No logistics trend data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — ANALYST
# ══════════════════════════════════════════════════════════════════════════════
with analyst_tab:

    # ── Analyst-specific CSS ───────────────────────────────────────────────
    st.markdown('<style>.ax-shell{background:radial-gradient(ellipse at 50% 0%,rgba(107,158,138,.08),transparent 55%),var(--panel);border:1px solid var(--border);border-radius:18px;padding:32px 28px 24px;margin-bottom:18px;text-align:center;} .ax-eyebrow{color:var(--green);font-size:.62rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;} .ax-title{font-size:1.8rem;font-weight:850;letter-spacing:-.04em;color:var(--text);margin:8px 0 6px;} .ax-sub{color:var(--muted);font-size:.85rem;max-width:480px;margin:0 auto;line-height:1.5;} .ax-examples{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;max-width:560px;margin:20px auto 0;} .ax-ex{background:var(--panel-2);border:1px solid var(--border);border-radius:10px;padding:10px 13px;text-align:left;color:var(--text-2);font-size:.78rem;line-height:1.4;cursor:default;transition:border-color .15s;} .ax-ex:hover{border-color:var(--green);} .ax-ex-cat{color:var(--green);font-size:.58rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-bottom:3px;} .ax-composer{background:linear-gradient(135deg,#f0e9da,#e6dcc8);border:1px solid #c8bca4;border-radius:14px;padding:3px;display:flex;align-items:center;gap:0;margin:6px 0 18px;} .ax-composer input{flex:1;background:transparent !important;border:none !important;outline:none !important;box-shadow:none !important;color:#2a2420 !important;font-size:.88rem;padding:10px 14px;} .ax-composer input::placeholder{color:#8a7e6e !important;} .ax-send{width:36px;height:36px;border-radius:10px;border:none;background:linear-gradient(135deg,#c4b99a,#b0a484);color:#1a1510;font-size:1rem;font-weight:800;cursor:pointer;display:flex;align-items:center;justify-content:center;margin-right:3px;flex-shrink:0;transition:opacity .15s;} .ax-send:hover{opacity:.85;} .ax-send:disabled{opacity:.4;cursor:default;} .ax-spinner{width:14px;height:14px;border:2px solid #c8bca4;border-top-color:#8a7e6e;border-radius:50%;animation:supplychainiq-spin .8s linear infinite;margin-right:3px;flex-shrink:0;} .ax-you{background:var(--panel-2);border:1px solid var(--border);border-left:3px solid var(--green);border-radius:12px;padding:14px 16px;margin-bottom:10px;} .ax-you-label{font-size:.6rem;font-weight:800;color:var(--green);text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px;} .ax-you-text{font-size:.88rem;color:var(--text);line-height:1.5;} .ax-agent{background:linear-gradient(135deg,#f0e9da,#e8dfcd);border:1px solid #c8bca4;border-radius:14px;padding:18px 20px;margin-bottom:10px;color:#2a2420;} .ax-agent-label{font-size:.6rem;font-weight:800;color:#6b8a7e;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;} .ax-agent-body{font-size:.88rem;line-height:1.6;color:#2a2420;} .ax-gov-toggle{font-size:.72rem;color:#8a7e6e;margin-top:10px;cursor:pointer;} .ax-footer{display:flex;align-items:center;justify-content:space-between;margin-top:10px;}</style>', unsafe_allow_html=True)

    # ── Single-turn state ──────────────────────────────────────────────────
    _VER = "v4-premium"
    if st.session_state.get("_analyst_ver") != _VER:
        st.session_state["_analyst_ver"] = _VER
        st.session_state["cur_q"] = ""
        st.session_state["cur_a"] = ""
        st.session_state["agent_busy"] = False
    for k, d in [("cur_q", ""), ("cur_a", ""), ("agent_busy", False), ("cur_prov", None)]:
        if k not in st.session_state:
            st.session_state[k] = d

    is_busy = st.session_state.agent_busy
    has_answer = bool(st.session_state.cur_q and st.session_state.cur_a)

    # ── Empty-state hero (shown only when no current exchange) ─────────────
    if not st.session_state.cur_q:
        st.markdown('<div class="ax-shell"><div class="ax-eyebrow">Governed Analytics</div><div class="ax-title">Ask the supply chain anything</div><div class="ax-sub">Governed analytics &mdash; ask business questions, get data-driven answers.</div><div class="ax-examples"><div class="ax-ex"><div class="ax-ex-cat">Enterprise</div>What is our on-time delivery percentage?</div><div class="ax-ex"><div class="ax-ex-cat">Logistics</div>Which country has the highest logistics cost rate?</div><div class="ax-ex"><div class="ax-ex-cat">Commercial</div>What are our total sales and profit?</div><div class="ax-ex"><div class="ax-ex-cat">Governance</div>What is our fill rate?</div></div></div>', unsafe_allow_html=True)

    # ── Composer (always visible, always at this position) ─────────────────
    with st.form("analyst_form", clear_on_submit=True):
        user_input = st.text_input("Ask SupplyChainIQ", placeholder="Ask a supply-chain question...", key="analyst_input", label_visibility="collapsed", disabled=is_busy)
        col_sp, col_send = st.columns([8, 1])
        with col_send:
            submitted = st.form_submit_button("Send" if not is_busy else "...", type="primary", disabled=is_busy)

    if is_busy:
        st.markdown('<div style="display:flex;align-items:center;gap:8px;padding:4px 0 10px;"><div class="ax-spinner"></div><span style="font-size:.78rem;color:var(--muted);">SupplyChainIQ Agent is thinking...</span></div>', unsafe_allow_html=True)

    # ── Phase 1: submit — replace state, set busy ─────────────────────────
    if submitted and user_input and user_input.strip() and not is_busy:
        st.session_state.cur_q = user_input.strip()
        st.session_state.cur_a = ""
        st.session_state.agent_busy = True
        if hasattr(st, 'rerun'):
            st.rerun()
        elif hasattr(st, 'experimental_rerun'):
            st.experimental_rerun()

    # ── Phase 2: busy — call real agent ───────────────────────────────────
    if st.session_state.agent_busy and st.session_state.cur_q:
        try:
            req_body = _json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": st.session_state.cur_q}]}]})
            result_raw = session.sql(f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_AGENT', $${req_body}$$)").collect()[0][0]
            prov_parsed = parse_agent_response(result_raw)
            response_text = prov_parsed.get("text", "")
            if not response_text:
                response_text = "The agent returned an empty response."
            st.session_state.cur_a = response_text
            st.session_state.cur_prov = build_provenance(prov_parsed, session)
        except Exception as e:
            st.session_state.cur_a = f"Agent error: {str(e)}"
            st.session_state.cur_prov = None
        st.session_state.agent_busy = False
        if hasattr(st, 'rerun'):
            st.rerun()
        elif hasattr(st, 'experimental_rerun'):
            st.experimental_rerun()

    # ── Render current exchange ────────────────────────────────────────────
    if st.session_state.cur_q:
        q_html = f'<div class="ax-you"><div class="ax-you-label">You</div><div class="ax-you-text">{_html.escape(st.session_state.cur_q)}</div></div>'
        st.markdown(q_html, unsafe_allow_html=True)
        if st.session_state.cur_a:
            a_html = f'<div class="ax-agent"><div class="ax-agent-label">SupplyChainIQ Agent</div><div class="ax-agent-body">{_html.escape(st.session_state.cur_a)}</div></div>'
            st.markdown(a_html, unsafe_allow_html=True)
            prov_obj = st.session_state.get("cur_prov")
            if prov_obj:
                render_provenance_card(prov_obj)
            else:
                with st.expander("Governance & Sources"):
                    st.markdown("**Semantic layer:** SUPPLYCHAINIQ_COCO_SV  \n**Agent:** SUPPLYCHAINIQ_COCO_AGENT  \n**Constraints:** Governed metric formulas, two-island constraint, outlier inclusion, source attribution, non-computable metric refusal.")

    # ── Footer: clear + branding ──────────────────────────────────────────
    if st.session_state.cur_q:
        if st.button("Clear", key="clear_hist"):
            st.session_state.cur_q = ""
            st.session_state.cur_a = ""
            st.session_state.cur_prov = None
            if hasattr(st, 'rerun'):
                st.rerun()
            elif hasattr(st, 'experimental_rerun'):
                st.experimental_rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — GOVERNANCE
# ══════════════════════════════════════════════════════════════════════════════
with gov_tab:

    _h20 = '<div class="hero"> <div class="hero-title">Governance &amp; Ontology</div> <div class="hero-copy"> Entity catalog, relationship governance, metric registry, and architectural constraints that define the trusted analytical boundary of SupplyChainIQ CoCo. </div> </div>'
    st.markdown(_h20, unsafe_allow_html=True)

    # ── Entity Catalog ────────────────────────────────────────────────────────
    render_section("Entity Catalog")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:10px;">'
        'All governed entities across DataCo and SCMS source systems.</div>',
        unsafe_allow_html=True,
    )

    if not entity_cat_df.empty:
        source_opts = sorted(entity_cat_df["SOURCE_SYSTEM"].dropna().unique().tolist())
        sel_source = st.multiselect("Filter by source system", source_opts, default=source_opts, key="ent_src_flt")
        filtered_ent = entity_cat_df[entity_cat_df["SOURCE_SYSTEM"].isin(sel_source)] if sel_source else entity_cat_df

        ec1, ec2 = st.columns(2)
        ec1.metric("Total Entities", f"{len(entity_cat_df)}")
        ec2.metric("Shown", f"{len(filtered_ent)}")

        render_beige_board(
            "Entity Catalog",
            filtered_ent,
            subtitle=f"{len(filtered_ent)} entities across {len(sel_source)} source systems",
        )

        # Entity chips
        chips_html = ""
        for _, row in entity_cat_df.iterrows():
            name = _html.escape(str(row.get("ENTITY_NAME", "")))
            src = _html.escape(str(row.get("SOURCE_SYSTEM", "")))
            chips_html += f'<span class="entity-chip">{name} ({src})</span> '
        if chips_html:
            st.markdown(f'<div style="margin:10px 0;">{chips_html}</div>', unsafe_allow_html=True)
    else:
        st.info("No entity catalog data available.")

    # ── Entity Relationships ──────────────────────────────────────────────────
    render_section("Entity Relationships")

    if not entity_rel_df.empty:
        er1, er2 = st.columns(2)
        er1.metric("Total Relationships", f"{len(entity_rel_df)}")
        if "RELATIONSHIP_TYPE" in entity_rel_df.columns:
            rel_types = entity_rel_df["RELATIONSHIP_TYPE"].nunique()
            er2.metric("Relationship Types", f"{rel_types}")

        render_beige_board(
            "Entity Relationships",
            entity_rel_df,
            subtitle="Governed relationships between entities — defines valid join paths",
        )
    else:
        st.info("No entity relationship data available.")

    # ── Relationship Governance ───────────────────────────────────────────────
    render_section("Relationship Governance")

    if not rel_gov_df.empty:
        supported = rel_gov_df[rel_gov_df["STATUS"] == "SUPPORTED"]
        unsupported = rel_gov_df[rel_gov_df["STATUS"] != "SUPPORTED"]

        rg1, rg2, rg3 = st.columns(3)
        rg1.metric("Total Relationships", f"{len(rel_gov_df)}")
        rg2.metric("Supported", f"{len(supported)}")
        rg3.metric("Unsupported", f"{len(unsupported)}")

        if not supported.empty:
            _h21 = f'<div class="success-box"> <strong>{len(supported)} supported relationships</strong> — these entity joins are governed and analytically valid. </div>'
            st.markdown(_h21, unsafe_allow_html=True)
            render_beige_board(
                "Supported Relationships",
                supported,
                subtitle="Governed entity joins that are analytically valid",
            )

        if not unsupported.empty:
            _h22 = f'<div class="boundary"> <strong>{len(unsupported)} unsupported relationships</strong> — these entity joins are blocked by governance constraints (primarily the two-island constraint). </div>'
            st.markdown(_h22, unsafe_allow_html=True)
            render_beige_board(
                "Unsupported Relationships",
                unsupported,
                subtitle="Entity joins blocked by two-island or other governance constraints",
            )
    else:
        st.info("No relationship governance data available.")

    # ── Metric Registry ───────────────────────────────────────────────────────
    render_section("Metric Registry")

    if not metric_reg_df.empty:
        if "STATUS" in metric_reg_df.columns:
            status_counts = metric_reg_df["STATUS"].value_counts()
            status_labels = list(status_counts.index)
            mr_cols = st.columns(1 + len(status_labels))
            mr_cols[0].metric("Total Metrics", f"{len(metric_reg_df)}")
            for i, label in enumerate(status_labels):
                mr_cols[1 + i].metric(label, f"{int(status_counts[label])}")
        else:
            st.metric("Total Metrics", f"{len(metric_reg_df)}")

        render_beige_board(
            "Governed Metrics",
            metric_reg_df,
            subtitle="All registered metrics with formulas, sources, and computation status",
        )
    else:
        st.info("No metric registry data available.")

    # ── Two-Island Constraint ─────────────────────────────────────────────────
    render_section("Two-Island Architectural Constraint")

    _h23 = '<div class="boundary"> <strong>Two-Island Constraint</strong><br><br> DataCo and SCMS are <strong>independent source systems</strong> with <strong>no row-level join key</strong>. There is no shared order ID, customer ID, product ID, or shipment ID between the two systems.<br><br> <strong>What is allowed:</strong><br> &bull; Country-aggregate comparison — country name is the only shared dimension<br> &bull; Independent analysis within each source<br> &bull; Side-by-side metric display with clear source attribution<br><br> <strong>What is blocked:</strong><br> &bull; Row-level joins between DataCo and SCMS entities<br> &bull; Queries that imply a direct order&harr;shipment relationship<br> &bull; Blended metrics that mix row-level data from both sources<br><br> The agent is trained to refuse queries that violate this constraint and explain why. </div>'
    st.markdown(_h23, unsafe_allow_html=True)

    # ── Non-Computable Metrics ────────────────────────────────────────────────
    render_section("Non-Computable Metrics")

    _h24 = '<div class="card card-severity-info"> <div class="card-title">Metrics That Cannot Be Computed</div> <div class="card-body"> These standard supply-chain KPIs are registered in the metric registry but <strong>cannot be computed</strong> from available source data. The agent will decline requests for these metrics with an explanation.<br><br> &bull; <strong>Fill Rate</strong> — requires demand vs fulfilled quantity; neither source has partial-fill data<br> &bull; <strong>Days of Inventory (DOI)</strong> — requires inventory on-hand snapshots; no inventory data exists<br> &bull; <strong>Inventory Turnover</strong> — requires COGS and average inventory; no inventory data exists<br> &bull; <strong>Return Rate</strong> — requires return event data; neither source tracks returns<br> &bull; <strong>Perfect Order Rate</strong> — requires multiple quality dimensions not captured in either source </div> <div class="card-source">Governance: METRIC_REGISTRY &middot; Status: NOT_COMPUTABLE</div> </div>'
    st.markdown(_h24, unsafe_allow_html=True)

    # ── Outlier Inclusion Policy ──────────────────────────────────────────────
    render_section("Outlier Inclusion Policy")

    _h25 = f'<div class="card card-severity-warning"> <div class="card-title">Outlier Inclusion Policy</div> <div class="card-body"> The SupplyChainIQ governance framework requires that <strong>all data points be included</strong> in analyses, even statistical outliers. Specifically:<br><br> &bull; <strong>Belize</strong> ({belize_rate:.0f}% logistics cost rate) must always be included in country-level analyses and surfaced explicitly to users<br> &bull; No data point may be silently excluded based on its being an outlier<br> &bull; The agent is trained to present outliers with context rather than filtering them out<br> &bull; Users can filter outliers themselves but the system must not do so automatically<br><br> This policy ensures transparency and prevents data manipulation through selective exclusion. </div> <div class="card-source">Governance: Outlier Inclusion Policy &middot; Enforced by agent + semantic layer</div> </div>'
    st.markdown(_h25, unsafe_allow_html=True)

    # ── Data Readiness Scorecard ──────────────────────────────────────────────
    render_readiness_scorecard(session, render_section, render_beige_board)

    # ── Product & Shipping Analytics ──────────────────────────────────────────
    render_section("Product & Shipping Analytics")

    prod_ship_sub1, prod_ship_sub2 = st.tabs(["Product Categories", "Shipping Modes"])

    with prod_ship_sub1:
        if not product_df.empty:
            render_beige_board(
                "Product Category Performance",
                product_df,
                subtitle="Sales, profit, and order volume by product category — DataCo source",
            )
            if "CATEGORY_NAME" in product_df.columns and "TOTAL_SALES" in product_df.columns:
                st.markdown('<div class="graph-board"><div class="graph-label">Sales by Product Category</div></div>', unsafe_allow_html=True)
                st.bar_chart(product_df.head(15).set_index("CATEGORY_NAME")[["TOTAL_SALES"]])
        else:
            st.info("No product category data available.")

    with prod_ship_sub2:
        if not ship_mode_df.empty:
            render_beige_board(
                "Shipping Mode Analysis",
                ship_mode_df,
                subtitle="Shipping mode performance across source systems",
            )
        else:
            st.info("No shipping mode data available.")

    # ── Top Customers ─────────────────────────────────────────────────────────
    render_section("Top Customers", chip="DataCo")

    if not top_cust_df.empty:
        render_beige_board(
            "Top 50 Customers by Sales",
            top_cust_df,
            subtitle="Top customers ranked by total sales — DataCo source",
            max_rows=50,
        )
    else:
        st.info("No customer data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — METRIC DISAGREEMENT DETECTOR
# ══════════════════════════════════════════════════════════════════════════════
with disagree_tab:
    render_disagreement_detector(session, render_section, render_beige_board)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — EVALUATION
# ══════════════════════════════════════════════════════════════════════════════
with eval_tab:

    _h26 = f'<div class="hero"> <div class="hero-title">Evaluation &amp; Testing</div> <div class="hero-copy"> Semantic smoke tests and agent benchmark results. {total_tests} total tests &middot; {all_passed} passed &middot; {all_failed} failed &middot; {pass_rate:.1f}% pass rate. </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">Total Tests</div> <div class="value">{total_tests}</div> <div class="note">Smoke + Benchmark</div> </div> <div class="hero-kpi"> <div class="label">Passed</div> <div class="value">{all_passed}</div> <div class="note">All suites</div> </div> <div class="hero-kpi"> <div class="label">Failed</div> <div class="value">{all_failed}</div> <div class="note">All suites</div> </div> <div class="hero-kpi"> <div class="label">Pass Rate</div> <div class="value">{pass_rate:.1f}%</div> <div class="note">Overall</div> </div> </div> </div>'
    st.markdown(_h26, unsafe_allow_html=True)

    eval_overview, eval_smoke, eval_bench, eval_detail = st.tabs([
        "Overview", "Smoke Tests", "Agent Benchmarks", "Test Details"
    ])

    # ── Overview ──────────────────────────────────────────────────────────────
    with eval_overview:
        render_section("Test Suite Summary")

        ov1, ov2, ov3, ov4 = st.columns(4)
        ov1.metric("Total Tests", f"{total_tests}")
        ov2.metric("Passed", f"{all_passed}")
        ov3.metric("Failed", f"{all_failed}")
        ov4.metric("Pass Rate", f"{pass_rate:.1f}%")

        # Suite breakdown
        render_kpi_strip([
            ("Smoke Tests", f"{total_smoke}"),
            ("Smoke Passed", f"{smoke_passed}"),
            ("Smoke Failed", f"{smoke_failed}"),
            ("Bench Tests", f"{total_bench}"),
            ("Bench Passed", f"{bench_passed}"),
            ("Bench Failed", f"{bench_failed}"),
        ])

        if pass_rate >= 95:
            _h27 = f'<div class="success-box"> <strong>All suites healthy:</strong> {pass_rate:.1f}% pass rate across {total_tests} tests. The semantic layer and agent are operating within governed expectations. </div>'
            st.markdown(_h27, unsafe_allow_html=True)
        elif pass_rate >= 80:
            _h28 = f'<div class="boundary"> <strong>Attention:</strong> Pass rate is {pass_rate:.1f}%. {all_failed} test(s) failed. Review failing tests for regressions. </div>'
            st.markdown(_h28, unsafe_allow_html=True)
        else:
            _h29 = f'<div class="card card-severity-critical" style="margin:10px 0;"> <div class="card-title">Test Suite Degraded</div> <div class="card-body">Pass rate is {pass_rate:.1f}% — {all_failed} tests failed. Immediate investigation required.</div> </div>'
            st.markdown(_h29, unsafe_allow_html=True)

        if not eval_smoke_summary.empty:
            render_section("Smoke Test Summary")
            render_beige_board(
                "Smoke Test Summary",
                eval_smoke_summary,
                subtitle="Aggregated smoke test results",
            )

        if not eval_bench_summary.empty:
            render_section("Benchmark Summary by Category")
            render_beige_board(
                "Benchmark Summary by Category",
                eval_bench_summary,
                subtitle="Agent benchmark pass rates by test category",
            )

    # ── Smoke Tests ───────────────────────────────────────────────────────────
    with eval_smoke:
        render_section("Semantic Smoke Test Results")

        if not eval_smoke_results.empty:
            # Create display-friendly PASS/FAIL column from PASS_FLAG boolean
            smoke_display = eval_smoke_results.copy()
            smoke_display["RESULT"] = smoke_display["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
            pf_opts = ["PASS", "FAIL"]
            sel_pf = st.multiselect("Filter by result", pf_opts, default=pf_opts, key="smoke_pf_flt")
            filtered_smoke = smoke_display[smoke_display["RESULT"].isin(sel_pf)] if sel_pf else smoke_display

            if filtered_smoke.empty:
                st.info("No test cases match the selected filter.")
            es1, es2, es3 = st.columns(3)
            es1.metric("Shown", f"{len(filtered_smoke)}")
            es2.metric("Total Smoke Tests", f"{total_smoke}")
            smoke_pct = (smoke_passed / max(total_smoke, 1)) * 100
            es3.metric("Smoke Pass Rate", f"{smoke_pct:.1f}%")

            render_beige_board(
                "Smoke Test Results",
                filtered_smoke,
                subtitle="Individual semantic smoke test outcomes",
            )

            if smoke_failed > 0:
                failed_smoke = smoke_display[smoke_display["RESULT"] == "FAIL"]
                if not failed_smoke.empty:
                    _h30 = f'<div class="boundary"> <strong>{smoke_failed} smoke test(s) failed.</strong> Review the failing tests below. </div>'
                    st.markdown(_h30, unsafe_allow_html=True)
                    render_beige_board(
                        "Failed Smoke Tests",
                        failed_smoke,
                        subtitle="Smoke tests that did not pass — investigate for regressions",
                    )
        else:
            st.info("No smoke test results available.")

    # ── Agent Benchmarks ──────────────────────────────────────────────────────
    with eval_bench:
        render_section("Agent Benchmark Suite")

        if not eval_bench_defs.empty:
            st.markdown(
                '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:10px;">'
                'Active benchmark definitions — what the agent is tested against.</div>',
                unsafe_allow_html=True,
            )

            if "CATEGORY" in eval_bench_defs.columns:
                cat_opts = sorted(eval_bench_defs["CATEGORY"].dropna().unique().tolist())
                sel_cat = st.multiselect("Filter by category", cat_opts, default=cat_opts, key="bench_cat_flt")
                filtered_defs = eval_bench_defs[eval_bench_defs["CATEGORY"].isin(sel_cat)] if sel_cat else eval_bench_defs
            else:
                filtered_defs = eval_bench_defs

            bd1, bd2 = st.columns(2)
            bd1.metric("Active Benchmarks", f"{len(eval_bench_defs)}")
            bd2.metric("Shown", f"{len(filtered_defs)}")

            render_beige_board(
                "Benchmark Definitions",
                filtered_defs,
                subtitle="Active test definitions with expected behavior",
            )
        else:
            st.info("No benchmark definitions available.")

        if not eval_bench_results.empty:
            render_section("Benchmark Execution Results")

            st.markdown(
                '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:10px;">'
                'Benchmark execution results.</div>',
                unsafe_allow_html=True,
            )

            bench_display = eval_bench_results.copy()
            if "PASS_FLAG" in bench_display.columns:
                bench_display["RESULT"] = bench_display["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
                br_pf_opts = ["PASS", "FAIL"]
                sel_br_pf = st.multiselect("Filter by result", br_pf_opts, default=br_pf_opts, key="bench_pf_flt")
                filtered_br = bench_display[bench_display["RESULT"].isin(sel_br_pf)] if sel_br_pf else bench_display
            else:
                filtered_br = bench_display

            if filtered_br.empty:
                st.info("No test cases match the selected filter.")
            br1, br2, br3 = st.columns(3)
            br1.metric("Total Benchmark Results", f"{total_bench}")
            br2.metric("Bench Passed", f"{bench_passed}")
            bench_pct = (bench_passed / max(total_bench, 1)) * 100
            br3.metric("Bench Pass Rate", f"{bench_pct:.1f}%")

            render_beige_board(
                "Benchmark Results",
                filtered_br,
                subtitle="Agent benchmark execution outcomes",
            )

            if bench_failed > 0:
                failed_bench = bench_display[bench_display["RESULT"] == "FAIL"]
                if not failed_bench.empty:
                    _h31 = f'<div class="boundary"> <strong>{bench_failed} benchmark test(s) failed.</strong> Review the failing tests below. </div>'
                    st.markdown(_h31, unsafe_allow_html=True)
                    render_beige_board(
                        "Failed Benchmarks",
                        failed_bench,
                        subtitle="Benchmark tests that did not pass — investigate for agent regressions",
                    )
        else:
            st.info("No benchmark results available.")

    # ── Test Details ──────────────────────────────────────────────────────────
    with eval_detail:
        render_section("Detailed Test Results")

        detail_sub1, detail_sub2 = st.tabs(["Smoke Details", "Benchmark Details"])

        with detail_sub1:
            if not eval_smoke_results.empty:
                st.metric("Total Smoke Records", f"{len(eval_smoke_results)}")
                render_beige_board(
                    "All Smoke Test Details",
                    eval_smoke_results,
                    subtitle="Complete smoke test results with test IDs, queries, and outcomes",
                    max_rows=200,
                )
            else:
                st.info("No smoke test details available.")

        with detail_sub2:
            if not eval_bench_results.empty:
                st.metric("Total Benchmark Records", f"{len(eval_bench_results)}")
                render_beige_board(
                    "All Benchmark Details",
                    eval_bench_results,
                    subtitle="Complete benchmark results with test IDs, categories, and outcomes",
                    max_rows=200,
                )
            else:
                st.info("No benchmark details available.")

        # Test health summary
        render_section("Test Health Summary")

        _h32 = f'<div class="card card-severity-{"info" if pass_rate >= 95 else "warning" if pass_rate >= 80 else "critical"}"> <div class="card-title">Overall Test Health</div> <div class="card-body"> <strong>{total_tests}</strong> total tests across smoke and benchmark suites.<br> <strong>{all_passed}</strong> passed, <strong>{all_failed}</strong> failed ({pass_rate:.1f}% pass rate).<br><br> Smoke suite: {smoke_passed}/{total_smoke} passed ({(smoke_passed / max(total_smoke, 1) * 100):.1f}%)<br> Benchmark suite: {bench_passed}/{total_bench} passed ({(bench_passed / max(total_bench, 1) * 100):.1f}%)<br><br> {"All systems nominal. Semantic layer and agent governance operating as expected." if pass_rate >= 95 else "Some tests require attention. Review failing tests for possible regressions." if pass_rate >= 80 else "Test suite degraded. Immediate investigation required."} </div> <div class="card-source">Source: EVALUATION schema &middot; Smoke + Benchmark suites</div> </div>'
        st.markdown(_h32, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    '<div class="footer-line">SupplyChainIQ &middot; Powered by CoCo &middot; Governed supply-chain operating '
    'intelligence &middot; SUPPLYCHAINIQ_COCO</div>',
    unsafe_allow_html=True,
)
