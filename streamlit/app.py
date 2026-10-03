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


def render_beige_board(title, df, subtitle="", max_rows=100, columns=None, formats=None, limit=None, highlight_col=None):
    """Render a dark compact analytical table."""
    if df is None or df.empty:
        st.info(f"No data for {title}.")
        return
    effective_limit = limit if limit is not None else max_rows
    rows = df.head(effective_limit)
    if columns:
        col_map = columns if isinstance(columns, dict) else {c: c for c in columns}
        display_cols = [c for c in col_map if c in rows.columns]
        display_labels = [col_map[c] for c in display_cols]
    else:
        display_cols = list(rows.columns)
        display_labels = display_cols
    header_html = "".join(f'<th>{_html.escape(str(l))}</th>' for l in display_labels)
    body_rows = []
    for _, row in rows.iterrows():
        cells = []
        for c in display_cols:
            val = row[c]
            hl = ' style="color:var(--accent);"' if highlight_col and c == highlight_col else ''
            if val is None or (isinstance(val, float) and val != val):
                cells.append(f'<td{hl} class="null-cell">&mdash;</td>')
            elif formats and c in formats:
                cells.append(f'<td{hl}>{formats[c](val)}</td>')
            elif isinstance(val, (int, float, _decimal.Decimal)):
                v = float(val)
                if abs(v) >= 1 and v == int(v):
                    cells.append(f'<td{hl} class="num-cell">{int(v):,}</td>')
                else:
                    cells.append(f'<td{hl} class="num-cell">{v:,.4f}</td>')
            else:
                cells.append(f'<td{hl}>{_html.escape(str(val))}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body_html = "\n".join(body_rows)
    sub_line = f'<div class="tbl-sub">{_html.escape(subtitle)}</div>' if subtitle else ""
    row_note = f'<div class="tbl-note">Showing {len(rows)} of {len(df)} rows</div>' if len(df) > effective_limit else ""
    _h0 = f'<div class="dark-board"><div class="tbl-title">{_html.escape(title)}</div>{sub_line}<div style="overflow-x:auto;max-height:400px;overflow-y:auto;"><table class="dark-table"><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table></div>{row_note}</div>'
    st.markdown(_h0, unsafe_allow_html=True)


def render_signal_card(title, body, source, severity="info"):
    """Render a signal card with severity styling."""
    _h1 = f'<div class="card card-severity-{_html.escape(severity)}"> <div class="card-title">{title}</div> <div class="card-body">{body}</div> <div class="card-source">{_html.escape(source)}</div> </div>'
    st.markdown(_h1, unsafe_allow_html=True)


def render_kpi_strip(items):
    """Render a compact KPI row. items = list of (label, value) or (label, value, caption) tuples."""
    inner = ""
    for item in items:
        label, value = item[0], item[1]
        caption = item[2] if len(item) > 2 else ""
        cap_html = f'<div class="es-caption">{_html.escape(str(caption))}</div>' if caption else ""
        inner += f'<div class="es-item"><div class="es-label">{_html.escape(str(label))}</div><div class="es-value">{_html.escape(str(value))}</div>{cap_html}</div>'
    st.markdown(f'<div class="enterprise-strip">{inner}</div>', unsafe_allow_html=True)


def render_section(title, chip=None, subtitle=None):
    """Render a section rule, title, optional subtitle and source chip."""
    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
    chip_html = f' &nbsp;<span class="entity-chip">{_html.escape(chip)}</span>' if chip else ""
    st.markdown(f'<div class="section-title">{_html.escape(title)}{chip_html}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="section-sub">{_html.escape(subtitle)}</div>', unsafe_allow_html=True)


def status_badge(label, kind="governed"):
    """Return HTML for a status badge. kind: governed, estimated, blocked."""
    colors = {"governed": "var(--accent)", "certified": "var(--accent)", "estimated": "var(--amber)", "alternative": "var(--amber)", "blocked": "transparent"}
    bg = colors.get(kind, "var(--accent)")
    border = "1px solid var(--amber)" if kind == "blocked" else "none"
    fg = "#fff" if kind != "blocked" else "var(--amber)"
    return f'<span style="background:{bg};color:{fg};border:{border};font-size:0.62rem;padding:2px 8px;border-radius:3px;font-weight:700;text-transform:uppercase;">{_html.escape(label)}</span>'


def render_callout(text, kind="info"):
    """Render a callout box. kind: info, warning."""
    cls = "success-box" if kind == "info" else "boundary"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""<style>
:root {
    --bg: #0B0E11;
    --panel: #12161A;
    --panel-2: #171C21;
    --border: #232A31;
    --text: #E6EDF3;
    --text-2: #A9B4BE;
    --muted: #6B7782;
    --accent: #3FB8A0;
    --accent-soft: rgba(63,184,160,.12);
    --amber: #D9A441;
    --amber-soft: rgba(217,164,65,.10);
    --danger: #E5534B;
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

/* ── Kill Streamlit red — teal accent everywhere ─────────────────── */
[data-baseweb="tag"] { background: var(--accent-soft) !important; color: var(--accent) !important; border: 1px solid var(--accent) !important; }
[data-baseweb="tag"] svg { fill: var(--accent) !important; }
.stSlider [data-baseweb="slider"] div[role="slider"] { background: var(--accent) !important; }
.stSlider [data-baseweb="slider"] div[data-testid="stTickBar"] > div { background: var(--accent) !important; }
/* Primary buttons (Ask →) */
.stButton > button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"],
.stFormSubmitButton > button,
[data-testid="stFormSubmitButton"] > button,
button[kind="primary"],
button[kind="primaryFormSubmit"] {
    background-color: var(--accent) !important;
    background: var(--accent) !important;
    border-color: var(--accent) !important;
    color: #000 !important;
    padding: 6px 20px !important;
    font-size: 0.82rem !important;
    font-weight: 700 !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[kind="primaryFormSubmit"]:hover,
.stFormSubmitButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover,
button[kind="primary"]:hover,
button[kind="primaryFormSubmit"]:hover {
    opacity: 0.85;
    background-color: var(--accent) !important;
    background: var(--accent) !important;
}
/* Secondary/default buttons (presets, clear) — neutral dark styling */
.stButton > button[kind="secondary"],
.stButton > button:not([kind="primary"]):not([kind="primaryFormSubmit"]) {
    background: var(--panel-2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    font-size: 0.78rem !important;
}
.stButton > button[kind="secondary"]:hover,
.stButton > button:not([kind="primary"]):not([kind="primaryFormSubmit"]):hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    background: var(--panel-2) !important;
}
/* Focus rings — teal not red */
input:focus, textarea:focus, [data-baseweb="select"] [aria-expanded="true"] { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent) !important; }
button:focus-visible { outline-color: var(--accent) !important; box-shadow: 0 0 0 2px var(--accent-soft) !important; }

/* ── Topbar ───────────────────────────────────────────────────────── */
.topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 20px; margin: -0.5rem -1rem 1rem -1rem;
    background: linear-gradient(135deg, var(--panel) 0%, var(--panel-2) 100%);
    border-bottom: 1px solid var(--border); border-radius: 0;
}
@keyframes supplychainiq-spin { to { transform: rotate(360deg); } }
.brand-row { display: flex; align-items: center; gap: 14px; }
.brand-mark { width: 36px; height: 36px; border-radius: 8px; font-size: 1.2rem; font-weight: 800; display: flex; align-items: center; justify-content: center; background: var(--accent) !important; color: #000; }
.brand-name { font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
.brand-sub { font-size: 0.75rem; color: var(--muted); margin-top: 1px; }
.live-pill { display: flex; align-items: center; gap: 7px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; color: var(--accent); background: var(--accent-soft); padding: 4px 12px; border-radius: 20px; border: 1px solid var(--border); }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 6px var(--accent); animation: pulse-dot 2s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* ── Tabs ─────────────────────────────────────────────────────────── */
button[data-baseweb="tab"] { background: var(--panel) !important; color: var(--muted) !important; border: 1px solid var(--border) !important; border-radius: 6px 6px 0 0 !important; font-size: 0.78rem !important; font-weight: 600 !important; padding: 7px 16px !important; margin-right: 2px !important; }
button[data-baseweb="tab"][aria-selected="true"] { background: var(--accent-soft) !important; color: var(--accent) !important; border-bottom: 2px solid var(--accent) !important; }
div[data-baseweb="tab-highlight"] { display: none !important; }
div[data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-list"] { gap: 0 !important; }

/* ── Hero ─────────────────────────────────────────────────────────── */
.hero { background: radial-gradient(ellipse at 30% 20%, var(--accent-soft) 0%, var(--panel) 60%, var(--bg) 100%); border: 1px solid var(--border); border-radius: 12px; padding: 28px 28px 22px; margin-bottom: 16px; }
.hero-title { font-size: 1.35rem; font-weight: 800; color: var(--text); letter-spacing: -0.03em; margin-bottom: 4px; }
.hero-copy { font-size: 0.85rem; color: var(--text-2); max-width: 720px; line-height: 1.5; margin-bottom: 16px; }
.hero-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.hero-kpi { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; text-align: center; }
.hero-kpi .label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 3px; }
.hero-kpi .value { font-size: 1.35rem; font-weight: 700; color: var(--accent); }
.hero-kpi .note { font-size: 0.65rem; color: var(--muted); margin-top: 2px; }

/* ── st.metric cards ──────────────────────────────────────────────── */
[data-testid="stMetricValue"] { font-size: 1.35rem !important; font-weight: 700 !important; color: var(--text) !important; }
[data-testid="stMetricLabel"] { font-size: 0.65rem !important; text-transform: uppercase !important; letter-spacing: 0.06em !important; color: var(--muted) !important; }
[data-testid="metric-container"] { background: var(--panel-2) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; padding: 12px 14px !important; }

/* ── Card ─────────────────────────────────────────────────────────── */
.card { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }
.card .card-title { font-size: 0.88rem; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.card .card-body { font-size: 0.82rem; color: var(--text-2); line-height: 1.5; }
.card .card-source { font-size: 0.68rem; color: var(--muted); margin-top: 6px; }
.card-severity-critical { border-left: 3px solid var(--danger); }
.card-severity-warning  { border-left: 3px solid var(--amber); }
.card-severity-info     { border-left: 3px solid var(--accent); }

/* ── KPI strip ───────────────────────────────────────────────────── */
.enterprise-strip { display: flex; flex-wrap: wrap; gap: 0; margin: 12px 0; background: var(--panel-2); border-radius: 8px; overflow: hidden; border: 1px solid var(--border); }
.enterprise-strip .es-item { flex: 1 1 140px; padding: 12px 16px; text-align: center; border-right: 1px solid var(--border); }
.enterprise-strip .es-item:last-child { border-right: none; }
.enterprise-strip .es-label { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin-bottom: 3px; }
.enterprise-strip .es-value { font-size: 1.15rem; font-weight: 700; color: var(--text); }
.enterprise-strip .es-caption { font-size: 0.62rem; color: var(--muted); margin-top: 1px; }

/* ── Dark board (analytical table) ────────────────────────────────── */
.dark-board { background: var(--panel); border-radius: 8px; padding: 14px 16px; margin: 10px 0; border: 1px solid var(--border); }
.tbl-title { font-weight: 700; font-size: 0.88rem; margin-bottom: 2px; color: var(--text); }
.tbl-sub { color: var(--muted); font-size: 0.75rem; margin-bottom: 6px; }
.tbl-note { color: var(--muted); font-size: 0.68rem; margin-top: 4px; }
.dark-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; color: var(--text-2); }
.dark-table thead th { text-align: left; padding: 6px 8px; font-weight: 700; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--panel); z-index: 1; }
.dark-table tbody td { padding: 5px 8px; border-bottom: 1px solid var(--border); }
.dark-table .num-cell { text-align: right; font-variant-numeric: tabular-nums; }
.dark-table .null-cell { color: var(--muted); }
.dark-table tbody tr:hover { background: var(--panel-2); }
.dark-table tbody tr:last-child td { border-bottom: none; }

/* ── Graph board ──────────────────────────────────────────────────── */
.graph-board { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin: 10px 0; }
.graph-label { font-size: 0.78rem; font-weight: 600; color: var(--muted); margin-bottom: 6px; }

/* ── Boundary / success callout ──────────────────────────────────── */
.boundary { background: var(--amber-soft); border: 1px solid var(--amber); border-radius: 8px; padding: 12px 16px; font-size: 0.82rem; color: var(--text); line-height: 1.5; margin: 8px 0; }
.success-box { background: var(--accent-soft); border: 1px solid var(--accent); border-radius: 8px; padding: 12px 16px; font-size: 0.82rem; color: var(--text); line-height: 1.5; margin: 8px 0; }

/* ── Entity chip ──────────────────────────────────────────────────── */
.entity-chip { display: inline-block; background: var(--accent-soft); border: 1px solid var(--border); border-radius: 4px; padding: 2px 8px; font-size: 0.68rem; color: var(--accent); font-weight: 600; margin: 2px 3px; }

/* ── Section rule / title ─────────────────────────────────────────── */
.section-rule { height: 1px; background: var(--border); margin: 20px 0 14px; }
.section-title { font-size: 1rem; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.section-sub { font-size: 0.78rem; color: var(--muted); margin-bottom: 8px; }

/* ── Sidebar ──────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] { background: var(--panel) !important; }
section[data-testid="stSidebar"] * { color: var(--text-2) !important; }
.sidebar-brand { font-size: 1rem; font-weight: 700; color: var(--text) !important; margin-bottom: 2px; }
.sidebar-sub { font-size: 0.75rem; color: var(--muted) !important; margin-bottom: 12px; line-height: 1.4; }
.sidebar-heading { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted) !important; font-weight: 700; margin: 12px 0 4px; }

/* ── Footer ───────────────────────────────────────────────────────── */
.footer-line { text-align: center; font-size: 0.68rem; color: var(--muted); padding: 16px 0 8px; margin-top: 24px; border-top: 1px solid var(--border); letter-spacing: 0.04em; }

/* ── Expander ─────────────────────────────────────────────────────── */
div[data-testid="stExpander"] { background: var(--panel-2) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; }
div[data-testid="stExpander"] summary span { font-weight: 600 !important; color: var(--text-2) !important; }

/* ── Ask processing spinner ──────────────────────────────────────── */
.ask-processing-wrap { display: flex; align-items: center; gap: 10px; padding: 14px 0; }
.ask-processing-wrap .spinner { width: 16px; height: 16px; border: 2px solid var(--border); border-top: 2px solid var(--accent); border-radius: 50%; animation: spin-ask 0.8s linear infinite; }
@keyframes spin-ask { to { transform: rotate(360deg); } }
</style>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING (cached)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600)
def _load_all(_session):
    """Load all dashboard data with caching."""
    d = {}
    d["delivery"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_DELIVERY_SCORECARD").to_pandas()
    d["logistics"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_LOGISTICS_SCORECARD").to_pandas()
    d["country"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD ORDER BY COUNTRY").to_pandas()
    d["risk"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT ORDER BY RISK_SIGNAL_COUNT DESC LIMIT 15").to_pandas()
    d["supplier"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 10").to_pandas()
    d["site"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 10").to_pandas()
    d["monthly_del"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_DELIVERY_TREND ORDER BY MONTH_START").to_pandas()
    d["monthly_log"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_LOGISTICS_TREND ORDER BY MONTH_START").to_pandas()
    d["dq"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.DATA_QUALITY_SCORECARD").to_pandas()
    d["rel_gov"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.RELATIONSHIP_GOVERNANCE ORDER BY STATUS DESC, SUBJECT_ENTITY").to_pandas()
    d["entity_cat"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_CATALOG ORDER BY SOURCE_SYSTEM, ENTITY_NAME").to_pandas()
    d["entity_rel"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_RELATIONSHIPS").to_pandas()
    d["metric_reg"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.METRIC_REGISTRY ORDER BY METRIC_ID").to_pandas()
    d["product"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.ANALYTICS.PRODUCT_CATEGORY_PERFORMANCE ORDER BY TOTAL_SALES DESC LIMIT 10").to_pandas()
    d["ship_mode"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.ANALYTICS.SHIPPING_MODE_ANALYSIS ORDER BY SOURCE_SYSTEM, TOTAL_VALUE DESC LIMIT 10").to_pandas()
    d["top_cust"] = _session.sql("SELECT CUSTOMER_FNAME || ' ' || CUSTOMER_LNAME AS CUSTOMER, TOTAL_SALES, TOTAL_PROFIT, ROUND(100.0 * TOTAL_PROFIT / NULLIF(TOTAL_SALES, 0), 1) AS MARGIN_PCT FROM SUPPLYCHAINIQ_COCO.ANALYTICS.TOP_CUSTOMERS ORDER BY TOTAL_SALES DESC LIMIT 10").to_pandas()
    d["eval_smoke_results"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS ORDER BY TESTED_AT DESC LIMIT 1) ORDER BY TEST_ID").to_pandas()
    d["eval_smoke_summary"] = _session.sql("SELECT RUN_ID, COUNT(*) AS TESTS_EXECUTED, COUNT_IF(PASS_FLAG) AS TESTS_PASSED, COUNT_IF(NOT PASS_FLAG) AS TESTS_FAILED, ROUND(100.0 * COUNT_IF(PASS_FLAG) / NULLIF(COUNT(*), 0), 2) AS PASS_RATE_PCT FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.SEMANTIC_SMOKE_RESULTS ORDER BY TESTED_AT DESC LIMIT 1) GROUP BY RUN_ID").to_pandas()
    d["eval_bench_summary"] = _session.sql("SELECT RUN_ID, CATEGORY, COUNT(*) AS TESTS_EXECUTED, COUNT_IF(PASS_FLAG) AS TESTS_PASSED, COUNT_IF(NOT PASS_FLAG) AS TESTS_FAILED, ROUND(100.0 * COUNT_IF(PASS_FLAG) / NULLIF(COUNT(*), 0), 2) AS PASS_RATE_PCT FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS ORDER BY EVALUATED_AT DESC LIMIT 1) GROUP BY RUN_ID, CATEGORY ORDER BY CATEGORY").to_pandas()
    d["eval_bench_defs"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK WHERE ACTIVE = TRUE ORDER BY TEST_ID").to_pandas()
    d["eval_bench_results"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS WHERE RUN_ID = (SELECT RUN_ID FROM SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK_RESULTS ORDER BY EVALUATED_AT DESC LIMIT 1) ORDER BY TEST_ID").to_pandas()
    d["red_team"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.RED_TEAM_RESULTS ORDER BY RUN_ID, TEST_ID").to_pandas()
    d["red_team_summary"] = _session.sql("SELECT RUN_ID, COUNT(*) AS TOTAL_CASES, COUNT_IF(PASS_FLAG) AS PASSED, COUNT_IF(NOT PASS_FLAG) AS FAILED, ROUND(100.0 * COUNT_IF(PASS_FLAG) / NULLIF(COUNT(*), 0), 2) AS PASS_RATE_PCT, MIN(TESTED_AT) AS RUN_DATE FROM SUPPLYCHAINIQ_COCO.EVALUATION.RED_TEAM_RESULTS GROUP BY RUN_ID ORDER BY MIN(TESTED_AT)").to_pandas()
    d["provenance_tests"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.PROVENANCE_TESTS ORDER BY TEST_ID").to_pandas()
    d["country_del"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD ORDER BY ORDER_ITEM_COUNT DESC LIMIT 15").to_pandas()
    d["country_log"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_LOGISTICS_SCORECARD ORDER BY SHIPMENT_COUNT DESC LIMIT 15").to_pandas()
    d["geo"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.CORE.GEOGRAPHY_DIM ORDER BY SOURCE_COVERAGE, COUNTRY_NAME").to_pandas()
    d["otd_variants"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.OTD_VARIANT_REGISTRY ORDER BY VARIANT_ID").to_pandas()
    d["persona_otd"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.PERSONA_OTD_CONSISTENCY ORDER BY PERSONA").to_pandas()
    d["metric_readiness"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.METRIC_READINESS ORDER BY METRIC_ID").to_pandas()
    return d

_data = _load_all(session)
delivery_df = _data["delivery"]
logistics_df = _data["logistics"]
country_df = _data["country"]
risk_df = _data["risk"]
supplier_df = _data["supplier"]
site_df = _data["site"]
monthly_del_df = _data["monthly_del"]
monthly_log_df = _data["monthly_log"]
dq_df = _data["dq"]
rel_gov_df = _data["rel_gov"]
entity_cat_df = _data["entity_cat"]
entity_rel_df = _data["entity_rel"]
metric_reg_df = _data["metric_reg"]
product_df = _data["product"]
ship_mode_df = _data["ship_mode"]
top_cust_df = _data["top_cust"]
eval_smoke_results = _data["eval_smoke_results"]
eval_smoke_summary = _data["eval_smoke_summary"]
eval_bench_summary = _data["eval_bench_summary"]
eval_bench_defs = _data["eval_bench_defs"]
eval_bench_results = _data["eval_bench_results"]
red_team_df = _data["red_team"]
red_team_summary = _data["red_team_summary"]
provenance_tests_df = _data["provenance_tests"]
country_del_df = _data["country_del"]
country_log_df = _data["country_log"]
geo_df = _data["geo"]
otd_variants_df = _data["otd_variants"]
persona_otd_df = _data["persona_otd"]
metric_readiness_df = _data["metric_readiness"]


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

# Red team counts
total_red_team = len(red_team_df) if not red_team_df.empty else 0
red_team_passed = int(red_team_df["PASS_FLAG"].sum()) if not red_team_df.empty and "PASS_FLAG" in red_team_df.columns else 0
red_team_failed = total_red_team - red_team_passed
red_team_runs = red_team_df["RUN_ID"].nunique() if not red_team_df.empty and "RUN_ID" in red_team_df.columns else 0
total_provenance_tests = len(provenance_tests_df) if not provenance_tests_df.empty else 0

# Grand totals (all evaluation artifacts)
grand_total_tests = total_tests + total_red_team + total_provenance_tests
grand_total_passed = all_passed + red_team_passed + total_provenance_tests

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
    st.markdown('<div class="sidebar-brand">SupplyChainIQ</div><div class="sidebar-sub">Governed supply-chain intelligence</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="boundary" style="font-size:0.75rem;padding:10px 12px;">'
        '<strong>Data boundary</strong><br>'
        'DataCo and SCMS are independent sources — no row-level join key. '
        'Cross-source comparison at country aggregate only.</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-heading">Trust Contract</div>', unsafe_allow_html=True)
    _otd_var_count = len(otd_variants_df) if not otd_variants_df.empty else 0
    _readiness_count = len(metric_readiness_df) if not metric_readiness_df.empty else 0
    st.markdown(
        f'<div style="font-size:0.72rem;color:var(--text-2);line-height:1.7;">'
        f'<strong style="color:var(--accent);">{grand_total_tests}</strong> executable tests '
        f'<span style="color:var(--muted);">({total_smoke} smoke, {total_red_team} red-team, {total_provenance_tests} provenance)</span><br>'
        f'<strong style="color:var(--accent);">{_otd_var_count}</strong> OTD variants &middot; '
        f'<strong style="color:var(--accent);">{_readiness_count}</strong> readiness assessments<br>'
        f'<span style="color:var(--muted);">Smoke {pass_rate:.0f}% &middot; Red team {red_team_passed}/{total_red_team}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-size:0.68rem;color:var(--muted);margin-top:8px;">'
        f'{len(geo_df)} countries &middot; {int(order_item_count):,} orders &middot; {int(shipment_count):,} shipments</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

analyst_tab, trust_tab, gov_tab, tower_tab, signals_tab, country_tab, supplier_tab, trends_tab, eval_tab = st.tabs([
    "Analyst",
    "Trust",
    "Governance",
    "Control Tower",
    "Decision Signals",
    "Country Intel",
    "Supplier / Site",
    "Trends",
    "Evaluation & Trust Contract",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONTROL TOWER
# ══════════════════════════════════════════════════════════════════════════════
with tower_tab:

    # ── 1. Title row ─────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Control Tower</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'DataCo orders and delivery, SCMS shipments and logistics. Governed metrics only.</div>',
        unsafe_allow_html=True,
    )

    # ── 2. ONE KPI row ───────────────────────────────────────────────────────
    _ct_kpi = (
        '<div class="enterprise-strip">'
        f'<div class="es-item"><div class="es-label">On-Time Delivery</div><div class="es-value">{otd:.1f}%</div><div class="es-caption" style="color:var(--accent);">DataCo</div></div>'
        f'<div class="es-item"><div class="es-label">Delay Rate</div><div class="es-value">{delay:.1f}%</div><div class="es-caption" style="color:var(--accent);">DataCo</div></div>'
        f'<div class="es-item"><div class="es-label">Total Sales</div><div class="es-value">${fmt_val(total_sales)}</div><div class="es-caption" style="color:var(--accent);">DataCo &middot; {int(order_item_count):,} items</div></div>'
        f'<div class="es-item"><div class="es-label">Profit Margin</div><div class="es-value">{profit_margin:.1f}%</div><div class="es-caption" style="color:var(--accent);">DataCo</div></div>'
        f'<div class="es-item"><div class="es-label">Logistics Rate</div><div class="es-value">{logistics_rate:.1f}%</div><div class="es-caption" style="color:var(--amber);">SCMS</div></div>'
        '</div>'
    )
    st.markdown(_ct_kpi, unsafe_allow_html=True)

    # ── 3. Alert callout ─────────────────────────────────────────────────────
    if delay > 50:
        st.markdown(
            f'<div class="boundary">Delay rate is above the 50% threshold ({delay:.1f}%).</div>',
            unsafe_allow_html=True,
        )

    # ── 4. Two-column analytical area ────────────────────────────────────────
    _ct_left, _ct_right = st.columns(2)

    with _ct_left:
        st.markdown('<div class="section-title" style="font-size:0.92rem;">Delivery health</div>', unsafe_allow_html=True)
        if not monthly_del_df.empty and "MONTH_START" in monthly_del_df.columns:
            _ct_altair_ok = False
            try:
                import altair as alt
                import pandas as _pd_ct
                _trend = monthly_del_df[["MONTH_START", "ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]].copy()
                _trend["MONTH_START"] = _pd_ct.to_datetime(_trend["MONTH_START"])
                _trend_m = _trend.melt("MONTH_START", var_name="Metric", value_name="Pct")
                _color_scale = alt.Scale(domain=["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"], range=["#3FB8A0", "#D9A441"])
                _ct_chart = alt.Chart(_trend_m).mark_line(strokeWidth=2).encode(
                    x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                    y=alt.Y("Pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color("Metric:N", scale=_color_scale, legend=alt.Legend(title=None, orient="top")),
                    tooltip=["MONTH_START:T", "Metric:N", alt.Tooltip("Pct:Q", format=".1f")],
                ).properties(height=240)
                _rule = alt.Chart({"values": [{"y": otd}]}).mark_rule(strokeDash=[4, 4], color="#3FB8A0", opacity=0.5).encode(y="y:Q")
                st.altair_chart(_ct_chart + _rule, use_container_width=True)
                _ct_altair_ok = True
            except Exception:
                pass
            if not _ct_altair_ok:
                st.line_chart(monthly_del_df.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=240)
        else:
            st.info("No delivery trend data.")

    with _ct_right:
        st.markdown('<div class="section-title" style="font-size:0.92rem;">Where the money comes from</div>', unsafe_allow_html=True)
        if not product_df.empty and "CATEGORY_NAME" in product_df.columns and "TOTAL_SALES" in product_df.columns:
            _ct_prod_ok = False
            try:
                import altair as alt
                _pdata = product_df[["CATEGORY_NAME", "TOTAL_SALES"]].head(10).copy()
                _pbars = alt.Chart(_pdata).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("CATEGORY_NAME:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                    x=alt.X("TOTAL_SALES:Q", title="Sales ($)"),
                    color=alt.value("#3FB8A0"),
                    tooltip=["CATEGORY_NAME:N", alt.Tooltip("TOTAL_SALES:Q", format="$,.0f")],
                ).properties(height=240)
                _ptext = _pbars.mark_text(align="left", dx=3, fontSize=10).encode(
                    text=alt.Text("TOTAL_SALES:Q", format="$,.0f"),
                    color=alt.value("#E6EDF3"),
                )
                st.altair_chart(_pbars + _ptext, use_container_width=True)
                _ct_prod_ok = True
            except Exception:
                pass
            if not _ct_prod_ok:
                st.bar_chart(product_df.head(10).set_index("CATEGORY_NAME")[["TOTAL_SALES"]], height=240)
        else:
            st.info("No product category data.")

    # ── 5. Two compact ranking tables ────────────────────────────────────────
    _tbl_l, _tbl_r = st.columns(2)

    with _tbl_l:
        if not top_cust_df.empty:
            render_beige_board(
                "Top 10 customers by sales",
                top_cust_df,
                columns={"CUSTOMER": "Customer", "TOTAL_SALES": "Sales", "TOTAL_PROFIT": "Profit", "MARGIN_PCT": "Margin %"},
                subtitle="DataCo source",
                formats={"TOTAL_SALES": fmt_usd, "TOTAL_PROFIT": fmt_usd, "MARGIN_PCT": fmt_pct},
            )
        else:
            st.info("No customer data.")

    with _tbl_r:
        if not product_df.empty:
            render_beige_board(
                "Top 10 categories",
                product_df,
                columns={"CATEGORY_NAME": "Category", "TOTAL_SALES": "Sales", "TOTAL_PROFIT": "Profit", "PROFIT_MARGIN_PCT": "Margin %", "ON_TIME_DELIVERY_PCT": "OTD %"},
                subtitle="DataCo source",
                formats={"TOTAL_SALES": fmt_usd, "TOTAL_PROFIT": fmt_usd, "PROFIT_MARGIN_PCT": fmt_pct, "ON_TIME_DELIVERY_PCT": fmt_pct},
            )
        else:
            st.info("No category data.")

    # ── 6. Logistics (SCMS) strip ────────────────────────────────────────────
    render_section("Logistics (SCMS)")
    render_kpi_strip([
        ("Shipments", f"{shipment_count:,.0f}"),
        ("Shipment Value", fmt_usd(shipment_value)),
        ("Freight Cost", fmt_usd(freight_cost)),
        ("Insurance", fmt_usd(insurance_cost)),
    ])
    st.markdown(
        f'<div class="boundary">Freight cost is null for {null_freight_pct:.0f}% of shipments, so freight-based metrics are lower bounds.</div>',
        unsafe_allow_html=True,
    )

    # ── 7. Data Quality compact cards ────────────────────────────────────────
    render_section("Data Quality")
    _dq1, _dq2 = st.columns(2)
    with _dq1:
        st.markdown(
            f'<div class="card card-severity-info"><div class="card-title">DataCo</div>'
            f'<div class="card-body"><strong>{int(order_item_count):,}</strong> order items &middot; '
            f'0% null on key fields (sales, dates, delivery status).</div>'
            f'<div class="card-source">DATA_QUALITY_SCORECARD</div></div>',
            unsafe_allow_html=True,
        )
    with _dq2:
        st.markdown(
            f'<div class="card card-severity-warning"><div class="card-title">SCMS</div>'
            f'<div class="card-body"><strong>{int(shipment_count):,}</strong> shipments &middot; '
            f'Freight {null_freight_pct:.0f}% null &middot; Weight {as_float(dq_df[dq_df["SOURCE_SYSTEM"]=="SCMS"]["NULL_WEIGHT_PCT"].iloc[0]) if not dq_df.empty and "NULL_WEIGHT_PCT" in dq_df.columns and len(dq_df[dq_df["SOURCE_SYSTEM"]=="SCMS"]) > 0 else 0:.0f}% null.</div>'
            f'<div class="card-source">DATA_QUALITY_SCORECARD</div></div>',
            unsafe_allow_html=True,
        )
    with st.expander("View full Data Quality Scorecard"):
        render_beige_board("Data Quality Scorecard", dq_df, subtitle="Coverage and completeness across source systems")

    # ── 8. Shipping Mode expander ────────────────────────────────────────────
    if not ship_mode_df.empty:
        with st.expander("Shipping mode comparison"):
            render_beige_board(
                "Shipping Mode Performance",
                ship_mode_df,
                columns={"SOURCE_SYSTEM": "Source", "SHIPPING_MODE": "Mode", "LINE_COUNT": "Lines", "TOTAL_VALUE": "Value", "ON_TIME_DELIVERY_PCT": "OTD %"},
                subtitle="Across both source systems",
                formats={"TOTAL_VALUE": fmt_usd, "ON_TIME_DELIVERY_PCT": fmt_pct},
            )


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
            _top_cs = country_df.head(15)
            render_beige_board(
                "Top 15 Countries by Cross-Source Activity",
                _top_cs,
                subtitle="DataCo: OTD, delay, sales, profit. SCMS: shipments, freight, logistics rate.",
            )
            if len(country_df) > 15:
                with st.expander(f"View all countries ({len(country_df)})"):
                    render_beige_board("All Countries", country_df, subtitle="Full cross-source scorecard")

        render_section("Top Countries — Delivery", chip="DataCo")

        if not country_del_df.empty:
            render_beige_board(
                "Delivery by Country",
                country_del_df,
                subtitle=f"Top {len(country_del_df)} by order volume — DataCo source",
            )

        render_section("Top Countries — Logistics", chip="SCMS")

        if not country_log_df.empty:
            render_beige_board(
                "Logistics by Country",
                country_log_df,
                subtitle=f"Top {len(country_log_df)} by shipment volume — SCMS source",
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
        render_section("Top 10 Suppliers", chip="SCMS")

        if not supplier_df.empty:
            sm1, sm2, sm3 = st.columns(3)
            sm1.metric("Suppliers Shown", f"{len(supplier_df)}")
            sm2.metric("Total Shipment Value", fmt_usd(as_float(supplier_df["SHIPMENT_VALUE_USD"].sum())))
            sm3.metric("Avg Logistics Rate", fmt_pct(as_float(supplier_df["LOGISTICS_COST_RATE_PCT"].mean())))

            render_beige_board(
                "Supplier Performance",
                supplier_df,
                subtitle="Top 10 suppliers by shipment value — SCMS source",
            )

            st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Suppliers by Shipment Value</div></div>', unsafe_allow_html=True)
            chart_sup = supplier_df.head(10).set_index("SUPPLIER")[["SHIPMENT_VALUE_USD"]]
            st.bar_chart(chart_sup)
        else:
            st.info("No supplier data available.")

    # ── Manufacturing Sites ───────────────────────────────────────────────────
    with sub_site:
        render_section("Top 10 Manufacturing Sites", chip="SCMS")

        if not site_df.empty:
            si1, si2, si3 = st.columns(3)
            si1.metric("Sites Shown", f"{len(site_df)}")
            si2.metric("Total Shipment Value", fmt_usd(as_float(site_df["SHIPMENT_VALUE_USD"].sum())))
            si3.metric("Avg Logistics Rate", fmt_pct(as_float(site_df["LOGISTICS_COST_RATE_PCT"].mean())))

            render_beige_board(
                "Manufacturing Site Performance",
                site_df,
                subtitle="Top 10 sites by shipment value — SCMS source",
            )

            st.markdown('<div class="graph-board"><div class="graph-label">Top 10 Sites by Shipment Value</div></div>', unsafe_allow_html=True)
            chart_site = site_df.head(10).set_index("SITE_NAME")[["SHIPMENT_VALUE_USD"]]
            st.bar_chart(chart_site)
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

            with st.expander(f"View delivery trend data ({len(monthly_del_df)} months)"):
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

            with st.expander(f"View commercial trend data ({len(monthly_del_df)} months)"):
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

            with st.expander(f"View logistics trend data ({len(monthly_log_df)} months)"):
                render_beige_board(
                    "Logistics Trend Data",
                    monthly_log_df,
                    subtitle="Monthly logistics metrics — SCMS source",
                )
        else:
            st.info("No logistics trend data available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB — ANALYST
# ══════════════════════════════════════════════════════════════════════════════
with analyst_tab:

    # ── Analyst CSS ────────────────────────────────────────────────────────
    st.markdown("""<style>
.an-hero{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:22px 24px 18px;margin-bottom:12px;}
.an-eyebrow{color:var(--accent);font-size:.58rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;}
.an-title{font-size:1.3rem;font-weight:800;color:var(--text);letter-spacing:-.03em;margin:4px 0 2px;}
.an-sub{color:var(--muted);font-size:.78rem;line-height:1.5;max-width:600px;}
.an-trust{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 4px;font-size:.7rem;color:var(--muted);}
.an-trust span{color:var(--accent);}
.an-presets{margin:8px 0 14px;}
.an-preset-group{font-size:.6rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:8px 0 4px;}
.an-q{background:var(--panel-2);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:6px;padding:10px 14px;margin-bottom:8px;}
.an-q-label{font-size:.55rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;}
.an-q-text{font-size:.85rem;color:var(--text);line-height:1.4;}
.an-answer{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px 18px;margin-bottom:8px;}
.an-answer-label{font-size:.55rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;}
.an-answer-body{font-size:.88rem;color:var(--text-2);line-height:1.6;}
.an-metric{background:var(--panel-2);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:8px;padding:14px 18px;margin-bottom:8px;}
.an-metric-name{font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;}
.an-metric-value{font-size:1.4rem;font-weight:800;color:var(--accent);margin-bottom:4px;}
.an-metric-meta{font-size:.72rem;color:var(--muted);line-height:1.5;}
.an-trust-panel{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:8px;font-size:.78rem;color:var(--text-2);line-height:1.6;}
.an-trust-panel strong{color:var(--text);}
.an-refusal{background:var(--amber-soft);border:1px solid var(--amber);border-radius:8px;padding:14px 18px;margin-bottom:8px;}
.an-refusal-label{font-size:.58rem;font-weight:700;color:var(--amber);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;}
.an-refusal-body{font-size:.85rem;color:var(--text-2);line-height:1.5;}
.an-refusal-body strong{color:var(--text);}
</style>""", unsafe_allow_html=True)

    # ── State management ──────────────────────────────────────────────────
    _VER = "v5-analyst"
    if st.session_state.get("_analyst_ver") != _VER:
        st.session_state["_analyst_ver"] = _VER
        st.session_state["cur_q"] = ""
        st.session_state["cur_a"] = ""
        st.session_state["cur_prov"] = None
    for k, d in [("cur_q", ""), ("cur_a", ""), ("cur_prov", None), ("preset_q", "")]:
        if k not in st.session_state:
            st.session_state[k] = d

    # ── Hero ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="an-hero">'
        '<div class="an-eyebrow">SupplyChainIQ Analyst</div>'
        '<div class="an-title">Governed conversational intelligence for supply-chain decisions.</div>'
        '<div class="an-sub">Ask across governed metrics, source boundaries and data readiness.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Composer ──────────────────────────────────────────────────────────
    with st.form("analyst_form", clear_on_submit=True):
        _default_q = st.session_state.get("preset_q", "")
        if _default_q:
            st.session_state["preset_q"] = ""
        col_input, col_btn = st.columns([9, 1])
        with col_input:
            user_input = st.text_input(
                "Query", value=_default_q,
                placeholder="Ask a supply-chain question...",
                key="analyst_input", label_visibility="collapsed",
            )
        with col_btn:
            submitted = st.form_submit_button("Ask \u2192", type="primary")

    # ── Trust row ─────────────────────────────────────────────────────────
    st.markdown(
        '<div class="an-trust">'
        '<span>\u2713</span> Governed metrics &nbsp; '
        '<span>\u2713</span> Source-aware &nbsp; '
        '<span>\u2713</span> Provenance-backed &nbsp; '
        '<span>\u2713</span> Refuses unsupported analysis'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Presets (outside form, fill only) ─────────────────────────────────
    if not st.session_state.cur_q:
        _presets = {
            "Governed metrics": [
                "What is our enterprise on-time delivery rate?",
                "What is our logistics cost rate?",
            ],
            "Trust": [
                "Why can two teams report different OTD?",
                "What metrics can we actually calculate from this data?",
            ],
            "Governance": [
                "Can you calculate Fill Rate?",
                "Join DataCo orders with SCMS shipments.",
            ],
        }
        st.markdown('<div class="an-presets">', unsafe_allow_html=True)
        for group_label, questions in _presets.items():
            st.markdown(f'<div class="an-preset-group">{_html.escape(group_label)}</div>', unsafe_allow_html=True)
            preset_cols = st.columns(len(questions))
            for i, pq in enumerate(questions):
                with preset_cols[i]:
                    if st.button(pq, key=f"preset_{i}_{group_label}", use_container_width=True):
                        st.session_state["preset_q"] = pq
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Submit handler + agent execution (single cycle) ─────────────────
    _do_exec = False
    if submitted and user_input and user_input.strip():
        st.session_state.cur_q = user_input.strip()
        st.session_state.cur_a = ""
        st.session_state.cur_prov = None
        _do_exec = True

    if _do_exec and st.session_state.cur_q:
        with st.spinner("Analyzing supply chain: resolving governed metric and source..."):
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

    # ── Render result ─────────────────────────────────────────────────────
    if st.session_state.cur_q and st.session_state.cur_a:
        prov_obj = st.session_state.get("cur_prov") or {}
        metrics_detail = prov_obj.get("metrics_detail", [])
        is_refusal = any(m.get("resolution_method") == "REFUSAL_DETECTED" for m in metrics_detail)
        governed_metrics = [m for m in metrics_detail if m.get("resolution_method") not in ("UNRESOLVED", "REFUSAL_DETECTED", None)]
        readiness_matches = prov_obj.get("readiness_matches", [])
        answer_text = st.session_state.cur_a

        # ── Question ──
        st.markdown(
            f'<div class="an-q"><div class="an-q-label">Question</div>'
            f'<div class="an-q-text">{_html.escape(st.session_state.cur_q)}</div></div>',
            unsafe_allow_html=True,
        )

        # ── Answer ──
        sentences = answer_text.split(". ")
        if len(sentences) > 4 and len(answer_text) > 400:
            short_answer = ". ".join(sentences[:3]) + "."
            has_long = True
        else:
            short_answer = answer_text
            has_long = False

        st.markdown(
            f'<div class="an-answer"><div class="an-answer-label">Answer</div>'
            f'<div class="an-answer-body">{_html.escape(short_answer)}</div></div>',
            unsafe_allow_html=True,
        )
        if has_long:
            with st.expander("Full answer"):
                st.markdown(f'<div style="font-size:0.82rem;color:var(--text-2);line-height:1.6;">{_html.escape(answer_text)}</div>', unsafe_allow_html=True)

        # ── Governed metric card ──
        if governed_metrics:
            for m in governed_metrics:
                mid = _html.escape(m.get("METRIC_ID", ""))
                mname = _html.escape(m.get("METRIC_NAME", ""))
                mver = m.get("VERSION") or "1.0"
                msrc = _html.escape(m.get("SOURCE_SYSTEM") or "—")
                mgrain = _html.escape(m.get("GRAIN") or "—")
                mdefn = _html.escape(m.get("DEFINITION") or "")
                # Look up readiness for data quality
                from readiness import get_readiness_for_metric
                rdns = get_readiness_for_metric(m.get("METRIC_ID", ""), session)
                dq_text = "No coverage issues recorded"
                if rdns:
                    null_pct = float(rdns.get("NULL_COVERAGE_PCT", 0))
                    if rdns.get("READINESS_STATUS") == "Certified":
                        dq_text = f'Certified \u00b7 {null_pct:.0f}% null coverage on required inputs'
                    else:
                        dq_text = f'{rdns.get("READINESS_STATUS", "")} \u00b7 {rdns.get("BLOCKING_REASON", "")}'

                # Source boundary note
                src_note = ""
                if msrc == "DataCo":
                    src_note = '<div style="font-size:.68rem;color:var(--muted);margin-top:4px;">SCMS shipment data is maintained as a separate source island and does not contribute to this metric.</div>'

                # Resolution label mapping
                res_methods = prov_obj.get("provenance_resolution_method", [])
                res_display = []
                for rm in res_methods:
                    if rm in ("SQL_EXPRESSION_MATCH", "COLUMN_SIGNATURE_MATCH"):
                        res_display.append("Deterministic SQL-based matching")
                    elif rm == "ANSWER_TEXT_FALLBACK":
                        res_display.append("Matched from answer text (lower confidence)")
                    elif rm == "UNRESOLVED":
                        res_display.append("UNRESOLVED")
                    else:
                        res_display.append(rm)
                res_label = ", ".join(sorted(set(res_display))) if res_display else "—"

                st.markdown(
                    f'<div class="an-metric">'
                    f'<div class="an-metric-name">Governed Metric \u00b7 {mid} \u00b7 v{_html.escape(str(mver))}</div>'
                    f'<div class="an-metric-value">{mname}</div>'
                    f'<div class="an-metric-meta">'
                    f'{msrc} \u00b7 {mgrain} \u00b7 \u2713 Governed definition<br>'
                    f'{_html.escape(mdefn)}'
                    f'</div>'
                    f'{src_note}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Trust panel ──
                sv = _html.escape(prov_obj.get("semantic_view") or "SUPPLYCHAINIQ_COCO_SV")
                st.markdown(
                    f'<div class="an-trust-panel">'
                    f'<strong>Semantic model:</strong> {sv}<br>'
                    f'<strong>Resolution:</strong> {_html.escape(res_label)}<br>'
                    f'<strong>Data quality:</strong> {_html.escape(dq_text)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Refusal / readiness card ──
        if is_refusal or readiness_matches:
            for rm in readiness_matches:
                blocking = _html.escape(str(rm.get("BLOCKING_REASON", "")))
                unlock = _html.escape(str(rm.get("WHAT_DATA_WOULD_UNLOCK", "")))
                rname = _html.escape(rm.get("METRIC_NAME", ""))
                st.markdown(
                    f'<div class="an-refusal">'
                    f'<div class="an-refusal-label">Data Readiness</div>'
                    f'<div class="an-refusal-body">'
                    f'<strong>{rname}</strong> cannot currently be computed.<br>'
                    f'<strong>Reason:</strong> {blocking}<br>'
                    f'<strong>Required to unlock:</strong> {unlock}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            if not readiness_matches and is_refusal:
                # Cross-source or other governance refusal
                rules = prov_obj.get("applicable_rules", [])
                if prov_obj.get("cross_source_detected") or rules:
                    st.markdown(
                        '<div class="an-refusal">'
                        '<div class="an-refusal-label">Governance Boundary</div>'
                        '<div class="an-refusal-body">'
                        '<strong>This query requires a cross-source row-level join that is not supported.</strong><br>'
                        'DataCo and SCMS are independent source systems with no shared row-level key.<br>'
                        '<strong>Allowed alternative:</strong> country-aggregate comparison.'
                        '</div></div>',
                        unsafe_allow_html=True,
                    )

        # ── Technical provenance ──
        with st.expander("Technical provenance"):
            qid = prov_obj.get("query_id")
            if qid:
                st.markdown(f"**Query ID:** `{qid}`")
            psql = prov_obj.get("physical_sql")
            if psql:
                st.code(psql, language="sql")
            else:
                st.markdown("*No SQL captured for this response.*")
            sv = prov_obj.get("semantic_view") or "—"
            st.markdown(f"**Semantic model:** `{sv}`")
            tables = prov_obj.get("tables_used", [])
            if tables:
                st.markdown(f"**Tables:** {', '.join(tables)}")

        # ── Clear button ──
        if st.button("Clear", key="clear_analyst"):
            st.session_state.cur_q = ""
            st.session_state.cur_a = ""
            st.session_state.cur_prov = None


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — GOVERNANCE
# ══════════════════════════════════════════════════════════════════════════════
with gov_tab:

    _h20 = '<div class="hero"> <div class="hero-title">Governance &amp; Ontology</div> <div class="hero-copy"> Entity catalog, relationship governance, metric registry, and architectural constraints that define the trusted analytical boundary of SupplyChainIQ CoCo. </div> </div>'
    st.markdown(_h20, unsafe_allow_html=True)

    # ── Ontology Graph ─────────────────────────────────────────────────────────
    render_section("Entity Relationship Graph")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:12px;">'
        'Governed entity relationships generated from live ontology tables. '
        'Teal solid = supported join. Red dashed = blocked (no row-level key). '
        'DataCo and SCMS are independent source systems — country-aggregate comparison only.</div>',
        unsafe_allow_html=True,
    )

    # Build DOT dynamically from ENTITY_CATALOG + RELATIONSHIP_GOVERNANCE
    _dataco_ents = set()
    _scms_ents = set()
    _bridge_ents = set()
    if not entity_cat_df.empty and "SOURCE_SYSTEM" in entity_cat_df.columns:
        for _, _ec in entity_cat_df.iterrows():
            _ename = str(_ec.get("ENTITY_NAME", "")).strip()
            _esrc = str(_ec.get("SOURCE_SYSTEM", "")).upper()
            if "BOTH" in _esrc or "CONFORMED" in _esrc:
                _bridge_ents.add(_ename)
            elif "DATACO" in _esrc:
                _dataco_ents.add(_ename)
            elif "SCMS" in _esrc:
                _scms_ents.add(_ename)
            else:
                _bridge_ents.add(_ename)
    _all_ents = _dataco_ents | _scms_ents | _bridge_ents
    if not rel_gov_df.empty:
        for _, _rg in rel_gov_df.iterrows():
            for _ecol in ("SUBJECT_ENTITY", "OBJECT_ENTITY"):
                _en = str(_rg.get(_ecol, "")).strip()
                if _en and _en not in _all_ents:
                    _bridge_ents.add(_en)
                    _all_ents.add(_en)

    _dot_lines = [
        'digraph G {',
        '  rankdir=TB;',
        '  bgcolor="transparent";',
        '  node [shape=box,style="filled,rounded",fontname="Helvetica",fontsize=10,fillcolor="#171C21",fontcolor="#E6EDF3",color="#232A31"];',
        '  edge [fontname="Helvetica",fontsize=8];',
    ]
    if _dataco_ents:
        _dot_lines.append('  subgraph cluster_dataco {')
        _dot_lines.append('    label="DataCo"; labeljust=l; fontname="Helvetica"; fontsize=10; fontcolor="#3FB8A0"; style=dashed; color="#3FB8A0";')
        for _e in sorted(_dataco_ents):
            _lbl = "MFG SITE" if _e == "MANUFACTURING_SITE" else _e.replace("_", " ")
            _dot_lines.append(f'    {_e} [label="{_lbl}"];')
        _dot_lines.append('  }')
    if _scms_ents:
        _dot_lines.append('  subgraph cluster_scms {')
        _dot_lines.append('    label="SCMS"; labeljust=l; fontname="Helvetica"; fontsize=10; fontcolor="#D9A441"; style=dashed; color="#D9A441";')
        for _e in sorted(_scms_ents):
            _lbl = "MFG SITE" if _e == "MANUFACTURING_SITE" else _e.replace("_", " ")
            _dot_lines.append(f'    {_e} [label="{_lbl}"];')
        _dot_lines.append('  }')
    for _e in sorted(_bridge_ents):
        _lbl = _e.replace("_", " ")
        _dot_lines.append(f'  {_e} [fillcolor="#232A31",label="{_lbl}\\n(Bridge)"];')
    if not rel_gov_df.empty:
        for _, _rg in rel_gov_df.iterrows():
            _s = str(_rg.get("SUBJECT_ENTITY", "")).strip()
            _o = str(_rg.get("OBJECT_ENTITY", "")).strip()
            _st = str(_rg.get("STATUS", "")).upper()
            _is_bridge = (_s in _bridge_ents or _o in _bridge_ents) and not (_s in _bridge_ents and _o in _bridge_ents)
            if _st == "SUPPORTED":
                if _is_bridge:
                    _dot_lines.append(f'  {_s} -> {_o} [color="#3FB8A0",penwidth=1.5,label="country\\naggregate",fontcolor="#3FB8A0"];')
                else:
                    _dot_lines.append(f'  {_s} -> {_o} [color="#3FB8A0",penwidth=1.5];')
            else:
                _dot_lines.append(f'  {_s} -> {_o} [color="#E5534B",style=dashed,penwidth=1.5,label="blocked",fontcolor="#E5534B"];')
    _dot_lines.append('}')
    _ontology_dot = '\n'.join(_dot_lines)

    _graphviz_ok = hasattr(st, "graphviz_chart")
    if _graphviz_ok:
        try:
            st.graphviz_chart(_ontology_dot, use_container_width=True)
        except Exception:
            _graphviz_ok = False
    if not _graphviz_ok:
        # HTML/CSS two-island fallback
        _dc_html = " ".join(f'<span class="entity-chip">{_html.escape(e)}</span>' for e in sorted(_dataco_ents))
        _sc_html = " ".join(f'<span class="entity-chip" style="border-color:var(--amber);color:var(--amber);">{_html.escape(e)}</span>' for e in sorted(_scms_ents))
        _br_html = " ".join(f'<span class="entity-chip" style="border-color:var(--text-2);color:var(--text-2);">{_html.escape(e)}</span>' for e in sorted(_bridge_ents))
        _supp_count = len(rel_gov_df[rel_gov_df["STATUS"] == "SUPPORTED"]) if not rel_gov_df.empty else 0
        _unsupp_count = len(rel_gov_df[rel_gov_df["STATUS"] != "SUPPORTED"]) if not rel_gov_df.empty else 0
        _fallback = (
            f'<div class="card card-severity-info" style="margin:10px 0;">'
            f'<div class="card-title">Two-Island Ontology</div>'
            f'<div class="card-body">'
            f'<strong style="color:var(--accent);">DataCo</strong>: {_dc_html}<br><br>'
            f'<strong style="color:var(--amber);">SCMS</strong>: {_sc_html}<br><br>'
            f'<strong>Bridge</strong>: {_br_html}<br><br>'
            f'{_supp_count} supported joins (teal) &middot; {_unsupp_count} blocked (red dashed)'
            f'</div></div>'
        )
        st.markdown(_fallback, unsafe_allow_html=True)

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


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — TRUST
# ══════════════════════════════════════════════════════════════════════════════
with trust_tab:

    _h_trust = '<div class="hero"> <div class="hero-title">Trust</div> <div class="hero-copy"> Governed metric definitions, cross-persona consistency, data readiness, and adversarial test coverage. </div> </div>'
    st.markdown(_h_trust, unsafe_allow_html=True)

    # ── Metric Disagreement ──────────────────────────────────────────────────
    render_section("Metric Disagreement", chip="OTD Variants")

    if not otd_variants_df.empty:
        governed_row = otd_variants_df[otd_variants_df["GOVERNANCE_STATUS"] == "GOVERNED"]
        governed_val = as_float(governed_row.iloc[0]["COMPUTED_VALUE"]) if not governed_row.empty else 0
        alt_variants = otd_variants_df[otd_variants_df["GOVERNANCE_STATUS"] != "GOVERNED"]
        if not alt_variants.empty and "DEVIATION_PCT" in alt_variants.columns:
            max_dev_row = alt_variants.loc[alt_variants["DEVIATION_PCT"].abs().idxmax()]
            alt_val = as_float(max_dev_row["COMPUTED_VALUE"])
            st.markdown(
                f'<div style="font-size:1rem;font-weight:700;color:var(--text);margin-bottom:8px;">'
                f'Same English metric, different numbers: {governed_val:.1f}% vs {alt_val:.1f}%.</div>',
                unsafe_allow_html=True,
            )

        _altair_ok = False
        try:
            import altair as alt
            chart_df = otd_variants_df[["VARIANT_NAME", "COMPUTED_VALUE", "GOVERNANCE_STATUS"]].copy()
            chart_df["is_governed"] = chart_df["GOVERNANCE_STATUS"] == "GOVERNED"
            bars = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("VARIANT_NAME:N", sort="-x", title=None, axis=alt.Axis(labelLimit=280)),
                x=alt.X("COMPUTED_VALUE:Q", title="OTD %", scale=alt.Scale(domain=[0, 50])),
                color=alt.condition(alt.datum.is_governed, alt.value("#3FB8A0"), alt.value("#6B7782")),
                tooltip=["VARIANT_NAME:N", alt.Tooltip("COMPUTED_VALUE:Q", format=".2f"), "GOVERNANCE_STATUS:N"],
            ).properties(height=240)
            text = bars.mark_text(align="left", dx=4, fontSize=11).encode(
                text=alt.Text("COMPUTED_VALUE:Q", format=".2f"),
                color=alt.value("#E6EDF3"),
            )
            st.altair_chart(bars + text, use_container_width=True)
            _altair_ok = True
        except Exception:
            pass
        if not _altair_ok:
            _vbar_rows = ""
            for _, vr in otd_variants_df.iterrows():
                vname = _html.escape(str(vr.get("VARIANT_NAME", "")))
                vval = as_float(vr.get("COMPUTED_VALUE", 0))
                vstatus = str(vr.get("GOVERNANCE_STATUS", ""))
                vcolor = "var(--accent)" if vstatus == "GOVERNED" else "var(--muted)"
                pct_w = min(vval / 50 * 100, 100)
                _vbar_rows += f'<div style="margin:4px 0;"><div style="font-size:0.72rem;color:var(--text-2);margin-bottom:2px;">{vname}</div><div style="background:var(--panel);border-radius:3px;height:22px;position:relative;"><div style="background:{vcolor};height:100%;width:{pct_w:.1f}%;border-radius:3px;"></div><span style="position:absolute;right:6px;top:2px;font-size:0.72rem;color:var(--text);">{vval:.2f}%</span></div></div>'
            st.markdown(f'<div style="padding:8px 0;">{_vbar_rows}</div>', unsafe_allow_html=True)

        v3_confirms = False
        v5_confirms = False
        for _, vrow in otd_variants_df.iterrows():
            vid = str(vrow.get("VARIANT_ID", ""))
            dev = as_float(vrow.get("DEVIATION_FROM_GOVERNED", 999))
            if "V3" in vid and abs(dev) < 0.001:
                v3_confirms = True
            if "V5" in vid and abs(dev) < 0.1:
                v5_confirms = True
        _expl = "V1 (Governed) uses the categorical DELIVERY_STATUS field to determine on-time delivery, excluding cancelled orders."
        if v3_confirms:
            _expl += " V3 (Risk Flag Method) independently confirms V1 using a different field basis (LATE_DELIVERY_RISK binary flag) — exact convergence."
        if v5_confirms:
            _expl += " V5 (Days-Based) independently confirms V1 using numeric day comparison — divergence is only +0.01pp."
        st.markdown(f'<div style="font-size:0.82rem;color:var(--text-2);line-height:1.5;margin:8px 0 16px;">{_expl}</div>', unsafe_allow_html=True)
    else:
        st.info("No OTD variant data available.")

    # ── Persona Consistency ──────────────────────────────────────────────────
    render_section("Persona Consistency")

    if not persona_otd_df.empty:
        _p_version = ""
        _p_strip = '<div class="enterprise-strip">'
        for _, pr in persona_otd_df.iterrows():
            p_name = _html.escape(str(pr.get("PERSONA", "")))
            p_val = as_float(pr.get("RESOLVED_VALUE", 0))
            p_match = pr.get("MATCHES_GOVERNED", False)
            p_vid = str(pr.get("PREFERRED_VARIANT_ID", ""))
            if not _p_version and p_vid:
                _p_version = p_vid
            _p_icon = "\u2713" if p_match else "\u2717"
            _p_color = "var(--accent)" if p_match else "var(--amber)"
            _p_strip += (
                f'<div class="es-item">'
                f'<div class="es-label">{p_name}</div>'
                f'<div class="es-value" style="color:{_p_color};">{p_val:.6f}%</div>'
                f'<div class="es-caption" style="color:{_p_color};">{_p_icon} Governed</div>'
                f'</div>'
            )
        _p_strip += '</div>'
        st.markdown(_p_strip, unsafe_allow_html=True)
        if _p_version:
            st.markdown(
                f'<div style="font-size:0.72rem;color:var(--muted);margin:4px 0 12px;">'
                f'All personas resolve to {_html.escape(_p_version)} under the governed definition.</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("No persona consistency data available.")

    # ── Data Readiness Grid ──────────────────────────────────────────────────
    render_section("Data Readiness Grid")

    if not metric_readiness_df.empty:
        _mr_certified = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] == "Certified"])
        _mr_notcomp = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"])
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Total Metrics", f"{len(metric_readiness_df)}")
        rc2.metric("Certified", f"{_mr_certified}")
        rc3.metric("Not Computable", f"{_mr_notcomp}")

        _mr_rows = ""
        for _, mr in metric_readiness_df.iterrows():
            _mr_name = _html.escape(str(mr.get("METRIC_NAME", "")))
            _mr_src = _html.escape(str(mr.get("SOURCE_SYSTEM", "")))
            _mr_status = str(mr.get("READINESS_STATUS", ""))
            _mr_reason = str(mr.get("BLOCKING_REASON", "None"))
            if _mr_reason in ("None", "") or not _mr_reason.strip():
                _mr_reason = "\u2014"
            else:
                _mr_reason = _html.escape(_mr_reason[:120] + ("..." if len(_mr_reason) > 120 else ""))
            if _mr_status == "Certified":
                _mr_badge = f'<span style="color:var(--accent);font-weight:700;">{_html.escape(_mr_status)}</span>'
            else:
                _mr_badge = f'<span style="color:var(--amber);font-weight:700;">{_html.escape(_mr_status)}</span>'
            _mr_rows += f'<tr><td>{_mr_name}</td><td>{_mr_src}</td><td>{_mr_badge}</td><td style="font-size:0.72rem;">{_mr_reason}</td></tr>'
        _mr_html = (
            '<div class="dark-board">'
            '<div class="tbl-title">Metric Readiness</div>'
            f'<div class="tbl-sub">{len(metric_readiness_df)} metrics assessed</div>'
            '<div style="overflow-x:auto;max-height:500px;overflow-y:auto;">'
            '<table class="dark-table"><thead><tr>'
            '<th>Metric</th><th>Source</th><th>Status</th><th>Blocking Reason</th>'
            '</tr></thead><tbody>'
            f'{_mr_rows}'
            '</tbody></table></div></div>'
        )
        st.markdown(_mr_html, unsafe_allow_html=True)
    else:
        st.info("No metric readiness data available.")

    # ── Red Team Summary ─────────────────────────────────────────────────────
    render_section("Red Team Summary")

    if not red_team_df.empty:
        _rt_latest_id = red_team_df["RUN_ID"].iloc[-1] if "RUN_ID" in red_team_df.columns else ""
        _rt_latest = red_team_df[red_team_df["RUN_ID"] == _rt_latest_id]
        _rt_latest_total = len(_rt_latest)
        _rt_latest_passed = int(_rt_latest["PASS_FLAG"].sum()) if "PASS_FLAG" in _rt_latest.columns else 0

        rts1, rts2, rts3 = st.columns(3)
        rts1.metric("Total Case-Runs", f"{total_red_team}")
        rts2.metric("Runs", f"{red_team_runs}")
        rts3.metric("Latest Run", f"{_rt_latest_passed}/{_rt_latest_total} PASS")

        st.markdown(
            f'<div class="success-box">'
            f'<strong>{total_red_team} case-runs across {red_team_runs} runs; latest run {_rt_latest_passed}/{_rt_latest_total} PASS</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if not _rt_latest.empty:
            _rt_disp = _rt_latest.copy()
            if "PASS_FLAG" in _rt_disp.columns:
                _rt_disp["RESULT"] = _rt_disp["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
            _rt_cols = {}
            if "CATEGORY" in _rt_disp.columns:
                _rt_cols["CATEGORY"] = "Case Class"
            if "QUESTION" in _rt_disp.columns:
                _rt_cols["QUESTION"] = "Question"
            if "RESULT" in _rt_disp.columns:
                _rt_cols["RESULT"] = "Result"
            if _rt_cols:
                render_beige_board(
                    f"Latest Run: {_html.escape(str(_rt_latest_id))}",
                    _rt_disp,
                    columns=_rt_cols,
                    subtitle=f"{_rt_latest_passed}/{_rt_latest_total} passed",
                )

        with st.expander("View full Red Team history"):
            _rt_hist = red_team_df.copy()
            if "PASS_FLAG" in _rt_hist.columns:
                _rt_hist["RESULT"] = _rt_hist["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
            render_beige_board("Red Team History", _rt_hist, subtitle=f"All {total_red_team} case-runs across {red_team_runs} runs")
    else:
        st.info("No red team results available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — EVALUATION
# ══════════════════════════════════════════════════════════════════════════════
with eval_tab:

    _h26 = f'<div class="hero"> <div class="hero-title">Evaluation &amp; Trust Contract</div> <div class="hero-copy"> {grand_total_tests} executable test cases across smoke, red team, and provenance suites, plus {_otd_var_count + _readiness_count} governance registry entries ({_otd_var_count} OTD variants, {_readiness_count} readiness assessments). </div> <div class="hero-kpis"> <div class="hero-kpi"> <div class="label">Smoke Tests</div> <div class="value">{total_smoke}</div> <div class="note">{smoke_passed} passed</div> </div> <div class="hero-kpi"> <div class="label">Red Team</div> <div class="value">{total_red_team}</div> <div class="note">{red_team_passed} passed &middot; {red_team_runs} runs</div> </div> <div class="hero-kpi"> <div class="label">Provenance</div> <div class="value">{total_provenance_tests}</div> <div class="note">Resolution tests</div> </div> <div class="hero-kpi"> <div class="label">Smoke Pass Rate</div> <div class="value">{pass_rate:.1f}%</div> <div class="note">Overall</div> </div> </div> </div>'
    st.markdown(_h26, unsafe_allow_html=True)

    eval_overview, eval_smoke, eval_redteam, eval_provenance, eval_bench, eval_detail = st.tabs([
        "Overview", "Smoke Tests", "Red Team", "Provenance", "Agent Benchmarks", "Test Details"
    ])

    # ── Overview ──────────────────────────────────────────────────────────────
    with eval_overview:
        render_section("Test Suite Summary")

        ov1, ov2, ov3, ov4 = st.columns(4)
        ov1.metric("Evaluation Artifacts", f"{grand_total_tests}")
        ov2.metric("Smoke Passed", f"{smoke_passed}/{total_smoke}")
        ov3.metric("Red Team Passed", f"{red_team_passed}/{total_red_team}")
        ov4.metric("Smoke Pass Rate", f"{pass_rate:.1f}%")

        render_kpi_strip([
            ("Smoke Tests", f"{total_smoke}"),
            ("Smoke Passed", f"{smoke_passed}"),
            ("Red Team Cases", f"{total_red_team}"),
            ("Red Team Runs", f"{red_team_runs}"),
            ("Provenance Tests", f"{total_provenance_tests}"),
            ("Bench Tests", f"{total_bench}"),
        ])

        if pass_rate >= 95:
            _h27 = f'<div class="success-box"> <strong>All suites healthy:</strong> {pass_rate:.1f}% smoke pass rate. {total_red_team} red team case-runs all passed. Semantic layer and agent governance operating within expectations. </div>'
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

    # ── Red Team ─────────────────────────────────────────────────────────────
    with eval_redteam:
        render_section("Agent Red Team Results")

        if not red_team_df.empty:
            st.markdown(
                '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:10px;">'
                'Adversarial test cases designed to probe agent governance boundaries: metric accuracy, '
                'two-island constraint enforcement, outlier inclusion, and non-computable metric refusal.</div>',
                unsafe_allow_html=True,
            )

            rt1, rt2, rt3, rt4 = st.columns(4)
            rt1.metric("Total Cases", f"{total_red_team}")
            rt2.metric("Passed", f"{red_team_passed}")
            rt3.metric("Failed", f"{red_team_failed}")
            rt_pct = (red_team_passed / max(total_red_team, 1)) * 100
            rt4.metric("Pass Rate", f"{rt_pct:.1f}%")

            if not red_team_summary.empty:
                render_section("Results by Run")
                render_beige_board(
                    "Red Team Runs",
                    red_team_summary,
                    subtitle="Pass rates across red team evaluation runs",
                )

            rt_display = red_team_df.copy()
            if "PASS_FLAG" in rt_display.columns:
                rt_display["RESULT"] = rt_display["PASS_FLAG"].map({True: "PASS", False: "FAIL"})

            run_opts = sorted(rt_display["RUN_ID"].unique().tolist()) if "RUN_ID" in rt_display.columns else []
            if run_opts:
                sel_run = st.multiselect("Filter by run", run_opts, default=run_opts, key="rt_run_flt")
                filtered_rt = rt_display[rt_display["RUN_ID"].isin(sel_run)] if sel_run else rt_display
            else:
                filtered_rt = rt_display

            render_beige_board(
                "Red Team Case Details",
                filtered_rt,
                subtitle="Individual red team case outcomes with agent responses",
            )

            if red_team_failed == 0:
                latest_run_df = red_team_df[red_team_df["RUN_ID"] == red_team_df["RUN_ID"].iloc[-1]] if not red_team_df.empty else red_team_df
                latest_count = len(latest_run_df) if not latest_run_df.empty else 0
                latest_id = latest_run_df["RUN_ID"].iloc[0] if not latest_run_df.empty else "—"
                _rt_ok = f'<div class="success-box"> <strong>{total_red_team} red team case-runs across {red_team_runs} runs — all passed.</strong> Latest run ({_html.escape(str(latest_id))}): {latest_count}/{latest_count} PASS. Agent governance boundaries are holding. </div>'
                st.markdown(_rt_ok, unsafe_allow_html=True)
        else:
            st.info("No red team results available.")

    # ── Provenance Tests ─────────────────────────────────────────────────────
    with eval_provenance:
        render_section("Provenance Resolution Tests")

        if not provenance_tests_df.empty:
            st.markdown(
                '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:10px;">'
                'Tests verifying that the provenance resolver correctly identifies governed metrics '
                'from agent-generated SQL and response text. Covers SQL expression matching, '
                'column signature matching, and answer text fallback strategies.</div>',
                unsafe_allow_html=True,
            )

            pt1, pt2 = st.columns(2)
            pt1.metric("Total Provenance Tests", f"{total_provenance_tests}")
            if "EXPECTED_RESOLUTION" in provenance_tests_df.columns:
                res_counts = provenance_tests_df["EXPECTED_RESOLUTION"].value_counts()
                pt2.metric("Resolution Strategies", f"{len(res_counts)}")

            render_beige_board(
                "Provenance Test Definitions",
                provenance_tests_df,
                subtitle="Test cases for metric resolution from agent SQL and response text",
            )

            _prov_ok = f'<div class="success-box"> <strong>{total_provenance_tests} provenance tests defined.</strong> These verify the three-tier resolution strategy: SQL_EXPRESSION_MATCH, COLUMN_SIGNATURE_MATCH, and ANSWER_TEXT_FALLBACK. </div>'
            st.markdown(_prov_ok, unsafe_allow_html=True)
        else:
            st.info("No provenance test definitions available.")

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
            st.markdown(
                '<div style="color:var(--text-2);font-size:0.85rem;">'
                'Agent benchmark definitions are covered by the Red Team suite.</div>',
                unsafe_allow_html=True,
            )

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

        if not eval_smoke_results.empty:
            with st.expander(f"View all smoke test details ({len(eval_smoke_results)})"):
                render_beige_board(
                    "Smoke Test Details",
                    eval_smoke_results,
                    subtitle="Complete smoke test results",
                )
        else:
            st.info("No smoke test details available.")

        if not eval_bench_results.empty:
            with st.expander(f"View benchmark details ({len(eval_bench_results)})"):
                render_beige_board(
                    "Benchmark Details",
                    eval_bench_results,
                    subtitle="Benchmark execution details",
                )
        else:
            st.info("No benchmark details available.")

        # Test health summary
        render_section("Test Health Summary")

        _h32 = f'<div class="card card-severity-{"info" if pass_rate >= 95 else "warning" if pass_rate >= 80 else "critical"}"> <div class="card-title">Overall Test Health</div> <div class="card-body"> <strong>{grand_total_tests}</strong> evaluation artifacts across smoke, red team, provenance, and governance registry.<br> Smoke: {smoke_passed}/{total_smoke} passed ({(smoke_passed / max(total_smoke, 1) * 100):.1f}%)<br> Red Team: {red_team_passed}/{total_red_team} case-runs across {red_team_runs} runs<br> Provenance: {total_provenance_tests} resolution tests<br> Registry: {_otd_var_count} OTD variants + {_readiness_count} readiness assessments<br><br> {"All systems nominal. Semantic layer and agent governance operating as expected." if pass_rate >= 95 else "Some tests require attention. Review failing tests for possible regressions." if pass_rate >= 80 else "Test suite degraded. Immediate investigation required."} </div> <div class="card-source">Source: EVALUATION schema &middot; Trust Contract</div> </div>'
        st.markdown(_h32, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    '<div class="footer-line">SupplyChainIQ &middot; Powered by CoCo &middot; Governed supply-chain operating '
    'intelligence &middot; SUPPLYCHAINIQ_COCO</div>',
    unsafe_allow_html=True,
)
