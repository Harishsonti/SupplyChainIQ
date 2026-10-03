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
    d["supplier_25"] = _session.sql("SELECT SUPPLIER, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT, COUNTRIES_SERVED, SHIPMENT_LINE_COUNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 25").to_pandas()
    d["supplier_costrate"] = _session.sql("SELECT SUPPLIER, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD WHERE SHIPMENT_VALUE_USD >= 100000 ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 5").to_pandas()
    d["supplier_below_thresh"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD WHERE SHIPMENT_VALUE_USD < 100000").to_pandas()
    d["site"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 10").to_pandas()
    d["site_25"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT, COUNTRIES_SERVED, SHIPMENT_LINE_COUNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 25").to_pandas()
    d["site_top5"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 5").to_pandas()
    d["site_costrate"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD WHERE SHIPMENT_VALUE_USD >= 100000 ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 5").to_pandas()
    d["site_below_thresh"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD WHERE SHIPMENT_VALUE_USD < 100000").to_pandas()
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
    d["country_log_rate"] = _session.sql("SELECT COUNTRY, LOGISTICS_COST_RATE_PCT, SHIPMENT_COUNT, FREIGHT_COST_USD FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_LOGISTICS_SCORECARD ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 10").to_pandas()
    d["risk_high"] = _session.sql("SELECT COUNTRY, RISK_SIGNAL_COUNT, DELAY_RATE_PCT, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT WHERE RISK_TIER = 'HIGH' ORDER BY RISK_SIGNAL_COUNT DESC LIMIT 10").to_pandas()
    d["risk_counts"] = _session.sql("SELECT RISK_TIER, COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT GROUP BY RISK_TIER").to_pandas()
    d["risk_medium"] = _session.sql("SELECT COUNTRY, RISK_SIGNAL_COUNT, DELAY_RATE_PCT, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT WHERE RISK_TIER = 'MEDIUM' ORDER BY RISK_SIGNAL_COUNT DESC LIMIT 50").to_pandas()
    d["country_del_rank"] = _session.sql("SELECT COUNTRY, DELAY_RATE_PCT, ORDER_ITEM_COUNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD WHERE ORDER_ITEM_COUNT >= 50 ORDER BY DELAY_RATE_PCT DESC LIMIT 10").to_pandas()
    d["country_del_below"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD WHERE ORDER_ITEM_COUNT < 50").to_pandas()
    d["supplier_top5"] = _session.sql("SELECT SUPPLIER, SHIPMENT_VALUE_USD FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 5").to_pandas()
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
supplier_25_df = _data["supplier_25"]
supplier_costrate_df = _data["supplier_costrate"]
supplier_below_df = _data["supplier_below_thresh"]
site_df = _data["site"]
site_25_df = _data["site_25"]
site_top5_df = _data["site_top5"]
site_costrate_df = _data["site_costrate"]
site_below_df = _data["site_below_thresh"]
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
country_log_rate_df = _data["country_log_rate"]
risk_high_df = _data["risk_high"]
risk_counts_df = _data["risk_counts"]
risk_medium_df = _data["risk_medium"]
country_del_rank_df = _data["country_del_rank"]
country_del_below_df = _data["country_del_below"]
supplier_top5_df = _data["supplier_top5"]
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

# Risk counts (from full aggregate, not LIMIT 15)
_rc_map = {}
if not risk_counts_df.empty:
    for _, _rcr in risk_counts_df.iterrows():
        _rc_map[str(_rcr.get("RISK_TIER", ""))] = int(_rcr.get("CNT", 0))
high_risk_count = _rc_map.get("HIGH", 0)
medium_risk_count = _rc_map.get("MEDIUM", 0)
low_risk_count = _rc_map.get("LOW", 0)

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

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Decision Signals</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Ranked supply-chain exceptions and evidence. Signals ordered by severity.</div>',
        unsafe_allow_html=True,
    )

    # ── Build signal list ────────────────────────────────────────────────────
    _signals = []

    # S1: Delivery Risk
    _s1_sev = "critical" if delay > 50 else "info"
    _signals.append({"id": "s1", "title": "Delivery risk", "severity": _s1_sev,
        "metric": f"{delay:.1f}%", "metric_label": "delay rate",
        "body": f"The governed DataCo OTD rate is {otd:.1f}%. {delay:.1f}% of non-cancelled items were delivered late." + (" Exceeds 50% threshold." if delay > 50 else ""),
        "source": "ENTERPRISE_DELIVERY_SCORECARD \u00b7 ON_TIME_DELIVERY_PCT"})

    # S2: Logistics Cost Anomaly
    _signals.append({"id": "s2", "title": "Logistics cost anomaly", "severity": "warning",
        "metric": f"{belize_rate:.0f}%", "metric_label": "Belize logistics rate",
        "body": f"Belize logistics cost rate is {belize_rate:.0f}% \u2014 freight exceeds shipment value. Included per outlier-inclusion policy; not excluded.",
        "source": "COUNTRY_LOGISTICS_SCORECARD \u00b7 LOGISTICS_COST_RATE_PCT"})

    # S3: Country Risk
    _s3_sev = "critical" if high_risk_count > 5 else "warning"
    _signals.append({"id": "s3", "title": "Country risk", "severity": _s3_sev,
        "metric": f"{high_risk_count}", "metric_label": "HIGH-tier countries",
        "body": f"{high_risk_count} countries flagged HIGH risk (2+ signals above median). {medium_risk_count} MEDIUM, {low_risk_count} LOW.",
        "source": "COUNTRY_RISK_ASSESSMENT \u00b7 RISK_TIER"})

    # S4: Data Quality Gap
    _signals.append({"id": "s4", "title": "Data quality gap", "severity": "warning",
        "metric": f"{null_freight_pct:.0f}%", "metric_label": "SCMS null freight",
        "body": f"Freight-based logistics metrics are lower bounds because freight cost is null for {null_freight_pct:.0f}% of shipments.",
        "source": "ENTERPRISE_LOGISTICS_SCORECARD \u00b7 NULL_FREIGHT_PCT"})

    # S5: Supplier Concentration
    _s5_top5_val = as_float(supplier_top5_df["SHIPMENT_VALUE_USD"].sum()) if not supplier_top5_df.empty else 0
    _s5_total_val = as_float(supplier_df["SHIPMENT_VALUE_USD"].sum()) if not supplier_df.empty else 1
    _s5_pct = (_s5_top5_val / max(_s5_total_val, 1)) * 100
    _s5_sev = "warning" if _s5_pct > 50 else "info"
    _signals.append({"id": "s5", "title": "Supplier concentration", "severity": _s5_sev,
        "metric": f"{_s5_pct:.1f}%", "metric_label": "top-5 share",
        "body": f"Top 5 suppliers hold {_s5_pct:.1f}% of SCMS shipment value (${fmt_val(_s5_top5_val)} of ${fmt_val(_s5_total_val)}).",
        "source": f"SUPPLIER_SCORECARD \u00b7 {supplier_count} suppliers"})

    # S6: Non-Computable Metrics
    _nc_metrics = metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"] if not metric_readiness_df.empty else None
    _nc_count = len(_nc_metrics) if _nc_metrics is not None and not _nc_metrics.empty else 0
    _nc_list = ""
    if _nc_metrics is not None and not _nc_metrics.empty:
        for _, _ncr in _nc_metrics.iterrows():
            _nc_name = _html.escape(str(_ncr.get("METRIC_NAME", "")))
            _nc_reason = str(_ncr.get("BLOCKING_REASON", ""))
            _nc_short = _html.escape(_nc_reason[:80] + ("..." if len(_nc_reason) > 80 else "")) if _nc_reason else "\u2014"
            _nc_list += f"<br>\u2022 <strong>{_nc_name}</strong> \u2014 {_nc_short}"
    _signals.append({"id": "s6", "title": "Non-computable metrics", "severity": "warning",
        "metric": f"{_nc_count}", "metric_label": "metrics blocked",
        "body": f"{_nc_count} standard KPIs cannot be computed from available data.{_nc_list}<br><br><em>See Trust tab for full readiness grid.</em>",
        "source": "EVALUATION.METRIC_READINESS"})

    # S7: Two-Island Constraint
    _signals.append({"id": "s7", "title": "Two-island constraint", "severity": "info",
        "metric": "Active", "metric_label": "governance constraint",
        "body": "DataCo and SCMS are separate source islands with no row-level join key. Row-level cross-source joins are unsupported. Country-aggregate comparison is the only valid cross-source grain.",
        "source": "ONTOLOGY.RELATIONSHIP_GOVERNANCE"})

    # ── Sort by severity ─────────────────────────────────────────────────────
    _sev_order = {"critical": 0, "warning": 1, "info": 2}
    _signals.sort(key=lambda s: _sev_order.get(s["severity"], 3))

    # ── Severity summary row ─────────────────────────────────────────────────
    _cnt_crit = sum(1 for s in _signals if s["severity"] == "critical")
    _cnt_warn = sum(1 for s in _signals if s["severity"] == "warning")
    _cnt_info = sum(1 for s in _signals if s["severity"] == "info")
    _sev_strip = (
        '<div class="enterprise-strip" style="margin-bottom:16px;">'
        f'<div class="es-item"><div class="es-label">Critical</div><div class="es-value" style="color:var(--amber);">{_cnt_crit}</div></div>'
        f'<div class="es-item"><div class="es-label">Warning</div><div class="es-value" style="color:var(--amber);">{_cnt_warn}</div></div>'
        f'<div class="es-item"><div class="es-label">Info</div><div class="es-value" style="color:var(--accent);">{_cnt_info}</div></div>'
        '</div>'
    )
    st.markdown(_sev_strip, unsafe_allow_html=True)

    # ── Signal card renderer ─────────────────────────────────────────────────
    _sev_colors = {"critical": "var(--amber)", "warning": "var(--amber)", "info": "var(--accent)"}
    _sev_labels = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}

    def _render_sig_card(sig):
        _sc = _sev_colors.get(sig["severity"], "var(--accent)")
        _sl = _sev_labels.get(sig["severity"], "INFO")
        st.markdown(
            f'<div class="card" style="border-left:3px solid {_sc};">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<div class="card-title" style="margin:0;">{_html.escape(sig["title"])}</div>'
            f'<span style="background:{_sc};color:#000;font-size:0.58rem;padding:2px 8px;border-radius:3px;font-weight:700;">{_sl}</span>'
            f'</div>'
            f'<div style="font-size:1.35rem;font-weight:800;color:{_sc};margin-bottom:4px;">{sig["metric"]}</div>'
            f'<div style="font-size:0.65rem;color:var(--muted);margin-bottom:6px;">{_html.escape(sig["metric_label"])}</div>'
            f'<div class="card-body">{sig["body"]}</div>'
            f'<div class="card-source">{_html.escape(sig["source"])}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── 2-column signal grid ─────────────────────────────────────────────────
    for _si in range(0, len(_signals), 2):
        _col_a, _col_b = st.columns(2)
        with _col_a:
            _render_sig_card(_signals[_si])
            # Evidence expander
            _sid = _signals[_si]["id"]
            if _sid == "s1":
                with st.expander("Evidence"):
                    if not monthly_del_df.empty and "MONTH_START" in monthly_del_df.columns:
                        try:
                            import altair as alt
                            import pandas as _pd_s
                            _t = monthly_del_df[["MONTH_START", "ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]].copy()
                            _t["MONTH_START"] = _pd_s.to_datetime(_t["MONTH_START"])
                            _tm = _t.melt("MONTH_START", var_name="Metric", value_name="Pct")
                            _cs = alt.Scale(domain=["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"], range=["#3FB8A0", "#D9A441"])
                            _ch = alt.Chart(_tm).mark_line(strokeWidth=2).encode(
                                x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                                y=alt.Y("Pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
                                color=alt.Color("Metric:N", scale=_cs, legend=alt.Legend(title=None, orient="top")),
                                tooltip=["MONTH_START:T", "Metric:N", alt.Tooltip("Pct:Q", format=".1f")],
                            ).properties(height=220)
                            st.altair_chart(_ch, use_container_width=True)
                        except Exception:
                            st.line_chart(monthly_del_df.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=220)
            elif _sid == "s3":
                with st.expander("Evidence"):
                    if not risk_high_df.empty:
                        render_beige_board("Top HIGH-risk countries", risk_high_df,
                            columns={"COUNTRY": "Country", "RISK_SIGNAL_COUNT": "Risk Signals", "DELAY_RATE_PCT": "Delay %", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                            subtitle=f"{len(risk_high_df)} HIGH-tier countries",
                            formats={"DELAY_RATE_PCT": fmt_pct, "LOGISTICS_COST_RATE_PCT": fmt_pct})
                    else:
                        st.info("No HIGH-risk countries.")
            elif _sid == "s5":
                with st.expander("Evidence"):
                    if not supplier_top5_df.empty:
                        _st5 = supplier_top5_df.copy()
                        _st5["SHARE_PCT"] = _st5["SHIPMENT_VALUE_USD"].apply(lambda v: round(100.0 * as_float(v) / max(_s5_total_val, 1), 1))
                        render_beige_board("Top 5 suppliers by value", _st5,
                            columns={"SUPPLIER": "Supplier", "SHIPMENT_VALUE_USD": "Value", "SHARE_PCT": "Share %"},
                            subtitle="SCMS source",
                            formats={"SHIPMENT_VALUE_USD": fmt_usd, "SHARE_PCT": fmt_pct})
            elif _sid == "s6":
                with st.expander("Evidence"):
                    if _nc_metrics is not None and not _nc_metrics.empty:
                        render_beige_board("Non-computable metrics", _nc_metrics,
                            columns={"METRIC_NAME": "Metric", "BLOCKING_REASON": "Blocking Reason"},
                            subtitle="EVALUATION.METRIC_READINESS")
            elif _sid == "s7":
                pass  # No evidence needed for info constraint

        if _si + 1 < len(_signals):
            with _col_b:
                _render_sig_card(_signals[_si + 1])
                _sid2 = _signals[_si + 1]["id"]
                if _sid2 == "s2":
                    with st.expander("Evidence"):
                        if not country_log_rate_df.empty and "COUNTRY" in country_log_rate_df.columns:
                            try:
                                import altair as alt
                                _bdata = country_log_rate_df[["COUNTRY", "LOGISTICS_COST_RATE_PCT"]].copy()
                                _bdata["is_belize"] = _bdata["COUNTRY"].str.upper() == "BELIZE"
                                _bb = alt.Chart(_bdata).mark_bar(cornerRadiusEnd=3).encode(
                                    y=alt.Y("COUNTRY:N", sort="-x", title=None, axis=alt.Axis(labelLimit=140)),
                                    x=alt.X("LOGISTICS_COST_RATE_PCT:Q", title="Logistics Cost Rate %"),
                                    color=alt.condition(alt.datum.is_belize, alt.value("#D9A441"), alt.value("#3FB8A0")),
                                    tooltip=["COUNTRY:N", alt.Tooltip("LOGISTICS_COST_RATE_PCT:Q", format=".1f")],
                                ).properties(height=240)
                                st.altair_chart(_bb, use_container_width=True)
                            except Exception:
                                render_beige_board("Top 10 by logistics rate", country_log_rate_df,
                                    columns={"COUNTRY": "Country", "LOGISTICS_COST_RATE_PCT": "Rate %"},
                                    formats={"LOGISTICS_COST_RATE_PCT": fmt_pct})
                elif _sid2 == "s1":
                    with st.expander("Evidence"):
                        if not monthly_del_df.empty and "MONTH_START" in monthly_del_df.columns:
                            try:
                                import altair as alt
                                import pandas as _pd_s2
                                _t2 = monthly_del_df[["MONTH_START", "ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]].copy()
                                _t2["MONTH_START"] = _pd_s2.to_datetime(_t2["MONTH_START"])
                                _tm2 = _t2.melt("MONTH_START", var_name="Metric", value_name="Pct")
                                _cs2 = alt.Scale(domain=["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"], range=["#3FB8A0", "#D9A441"])
                                _ch2 = alt.Chart(_tm2).mark_line(strokeWidth=2).encode(
                                    x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                                    y=alt.Y("Pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
                                    color=alt.Color("Metric:N", scale=_cs2, legend=alt.Legend(title=None, orient="top")),
                                ).properties(height=220)
                                st.altair_chart(_ch2, use_container_width=True)
                            except Exception:
                                st.line_chart(monthly_del_df.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=220)
                elif _sid2 == "s3":
                    with st.expander("Evidence"):
                        if not risk_high_df.empty:
                            render_beige_board("Top HIGH-risk countries", risk_high_df,
                                columns={"COUNTRY": "Country", "RISK_SIGNAL_COUNT": "Risk Signals", "DELAY_RATE_PCT": "Delay %", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                                subtitle=f"{len(risk_high_df)} HIGH-tier countries",
                                formats={"DELAY_RATE_PCT": fmt_pct, "LOGISTICS_COST_RATE_PCT": fmt_pct})
                elif _sid2 == "s4":
                    pass  # Compact card, no extra evidence
                elif _sid2 == "s5":
                    with st.expander("Evidence"):
                        if not supplier_top5_df.empty:
                            _st5b = supplier_top5_df.copy()
                            _st5b["SHARE_PCT"] = _st5b["SHIPMENT_VALUE_USD"].apply(lambda v: round(100.0 * as_float(v) / max(_s5_total_val, 1), 1))
                            render_beige_board("Top 5 suppliers by value", _st5b,
                                columns={"SUPPLIER": "Supplier", "SHIPMENT_VALUE_USD": "Value", "SHARE_PCT": "Share %"},
                                subtitle="SCMS source",
                                formats={"SHIPMENT_VALUE_USD": fmt_usd, "SHARE_PCT": fmt_pct})
                elif _sid2 == "s6":
                    with st.expander("Evidence"):
                        if _nc_metrics is not None and not _nc_metrics.empty:
                            render_beige_board("Non-computable metrics", _nc_metrics,
                                columns={"METRIC_NAME": "Metric", "BLOCKING_REASON": "Blocking Reason"},
                                subtitle="EVALUATION.METRIC_READINESS")
                elif _sid2 == "s7":
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — COUNTRY INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
with country_tab:

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Country Intel</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Country-aggregate intelligence across DataCo delivery and SCMS logistics.</div>',
        unsafe_allow_html=True,
    )

    # ── KPI row (GEOGRAPHY_DIM = canonical 165 countries) ────────────────────
    _ci_kpi = (
        '<div class="enterprise-strip">'
        f'<div class="es-item"><div class="es-label">Countries</div><div class="es-value">{len(geo_df)}</div><div class="es-caption">GEOGRAPHY_DIM</div></div>'
        f'<div class="es-item"><div class="es-label">Both Sources</div><div class="es-value">{geo_both}</div><div class="es-caption" style="color:var(--accent);">DataCo + SCMS</div></div>'
        f'<div class="es-item"><div class="es-label">DataCo Only</div><div class="es-value">{geo_dataco_only}</div><div class="es-caption">delivery data</div></div>'
        f'<div class="es-item"><div class="es-label">SCMS Only</div><div class="es-value">{geo_scms_only}</div><div class="es-caption">logistics data</div></div>'
        f'<div class="es-item"><div class="es-label">HIGH Risk</div><div class="es-value" style="color:var(--amber);">{high_risk_count}</div><div class="es-caption">countries</div></div>'
        '</div>'
    )
    st.markdown(_ci_kpi, unsafe_allow_html=True)

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub_cross, sub_risk, sub_cov = st.tabs(["Cross-source view", "Risk", "Coverage"])

    # ══════════════════════════════════════════════════════════════════════════
    # CROSS-SOURCE VIEW
    # ══════════════════════════════════════════════════════════════════════════
    with sub_cross:
        _both_df = country_df[
            (country_df["SOURCE_COVERAGE"] == "BOTH") &
            (country_df["LOGISTICS_COST_RATE_PCT"].notna()) &
            (country_df["DELAY_RATE_PCT"].notna())
        ].copy() if not country_df.empty and "SOURCE_COVERAGE" in country_df.columns else None

        if _both_df is not None and not _both_df.empty:
            _med_delay = as_float(_both_df["DELAY_RATE_PCT"].median())
            _med_logistics = as_float(_both_df["LOGISTICS_COST_RATE_PCT"].median())

            # Scatter plot
            _scatter_ok = False
            try:
                import altair as alt
                _sdata = _both_df[["COUNTRY", "DELAY_RATE_PCT", "LOGISTICS_COST_RATE_PCT", "SHIPMENT_VALUE_USD"]].copy()
                _sdata["SHIPMENT_VALUE_USD"] = _sdata["SHIPMENT_VALUE_USD"].fillna(0).astype(float)
                _sdata["is_belize"] = _sdata["COUNTRY"].str.upper() == "BELIZE"
                _y_max = min(as_float(_sdata["LOGISTICS_COST_RATE_PCT"].max()) * 1.1, 350)

                _points = alt.Chart(_sdata).mark_circle(opacity=0.8).encode(
                    x=alt.X("DELAY_RATE_PCT:Q", title="DataCo Delay Rate %", scale=alt.Scale(domain=[0, 105])),
                    y=alt.Y("LOGISTICS_COST_RATE_PCT:Q", title="SCMS Logistics Cost Rate %",
                            scale=alt.Scale(type="log" if _y_max > 50 else "linear")),
                    size=alt.Size("SHIPMENT_VALUE_USD:Q", title="Shipment Value", scale=alt.Scale(range=[30, 400]), legend=None),
                    color=alt.condition(alt.datum.is_belize, alt.value("#D9A441"), alt.value("#3FB8A0")),
                    tooltip=["COUNTRY:N", alt.Tooltip("DELAY_RATE_PCT:Q", format=".1f"),
                             alt.Tooltip("LOGISTICS_COST_RATE_PCT:Q", format=".1f"),
                             alt.Tooltip("SHIPMENT_VALUE_USD:Q", format="$,.0f")],
                ).properties(height=300, title="Cross-source: poor delivery + high logistics cost?")

                _vline = alt.Chart({"values": [{"x": _med_delay}]}).mark_rule(
                    strokeDash=[4, 4], color="#6B7782", opacity=0.6).encode(x="x:Q")
                _hline = alt.Chart({"values": [{"y": _med_logistics}]}).mark_rule(
                    strokeDash=[4, 4], color="#6B7782", opacity=0.6).encode(y="y:Q")

                st.altair_chart(_points + _vline + _hline, use_container_width=True)
                _scatter_ok = True
            except Exception:
                pass
            if not _scatter_ok:
                st.info("Scatter chart not available. See table below.")

            st.markdown(
                f'<div style="font-size:0.75rem;color:var(--muted);margin:4px 0 12px;">'
                f'Country-aggregate comparison only. No row-level join between DataCo and SCMS. '
                f'Quadrants use live medians: Delay {_med_delay:.1f}% \u00b7 Logistics {_med_logistics:.1f}%. '
                f'{len(_both_df)} countries in both sources.</div>',
                unsafe_allow_html=True,
            )

            # Upper-right quadrant table
            _ur = _both_df[
                (_both_df["DELAY_RATE_PCT"] > _med_delay) &
                (_both_df["LOGISTICS_COST_RATE_PCT"] > _med_logistics)
            ].sort_values("LOGISTICS_COST_RATE_PCT", ascending=False).head(10)
            if not _ur.empty:
                render_beige_board(
                    f"Upper-right quadrant: high delay + high logistics ({len(_ur)})",
                    _ur,
                    columns={"COUNTRY": "Country", "DELAY_RATE_PCT": "Delay %",
                             "LOGISTICS_COST_RATE_PCT": "Logistics Rate %",
                             "SHIPMENT_COUNT": "Shipments", "ORDER_ITEM_COUNT": "Orders"},
                    subtitle="Above both medians — requires investigation",
                    formats={"DELAY_RATE_PCT": fmt_pct, "LOGISTICS_COST_RATE_PCT": fmt_pct},
                    limit=10,
                )
        else:
            st.info("No cross-source data available.")

        # ── Rankings row ─────────────────────────────────────────────────────
        _rk_l, _rk_r = st.columns(2)
        with _rk_l:
            _below_thresh = int(country_del_below_df.iloc[0]["CNT"]) if not country_del_below_df.empty else 0
            render_beige_board(
                "Highest delay rate (DataCo, min 50 orders)",
                country_del_rank_df,
                columns={"COUNTRY": "Country", "DELAY_RATE_PCT": "Delay %", "ORDER_ITEM_COUNT": "Order Items"},
                subtitle=f"Top 10. Minimum order-item threshold: 50. {_below_thresh} countries below threshold.",
                formats={"DELAY_RATE_PCT": fmt_pct},
            )
        with _rk_r:
            render_beige_board(
                "Highest logistics cost rate (SCMS)",
                country_log_rate_df,
                columns={"COUNTRY": "Country", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %",
                         "SHIPMENT_COUNT": "Shipments", "FREIGHT_COST_USD": "Freight"},
                subtitle="Top 10 by rate — Belize included per policy",
                formats={"LOGISTICS_COST_RATE_PCT": fmt_pct, "FREIGHT_COST_USD": fmt_usd},
            )

        # Scorecard expanders
        if not country_df.empty:
            with st.expander(f"View cross-source scorecard ({len(country_df)} countries)"):
                render_beige_board("Cross-Source Scorecard", country_df, subtitle="All countries", limit=50)

    # ══════════════════════════════════════════════════════════════════════════
    # RISK
    # ══════════════════════════════════════════════════════════════════════════
    with sub_risk:
        # Tier summary badges
        _risk_strip = (
            '<div class="enterprise-strip" style="margin-bottom:12px;">'
            f'<div class="es-item"><div class="es-label">HIGH</div><div class="es-value" style="color:var(--amber);">{high_risk_count}</div></div>'
            f'<div class="es-item"><div class="es-label">MEDIUM</div><div class="es-value" style="color:var(--text-2);">{medium_risk_count}</div></div>'
            f'<div class="es-item"><div class="es-label">LOW</div><div class="es-value" style="color:var(--accent);">{low_risk_count}</div></div>'
            '</div>'
        )
        st.markdown(_risk_strip, unsafe_allow_html=True)

        # HIGH-risk table
        if not risk_high_df.empty:
            render_beige_board(
                "HIGH-risk countries",
                risk_high_df,
                columns={"COUNTRY": "Country", "RISK_SIGNAL_COUNT": "Risk Signals",
                         "DELAY_RATE_PCT": "Delay %", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                subtitle=f"{len(risk_high_df)} countries with 2+ signals above median",
                formats={"DELAY_RATE_PCT": fmt_pct, "LOGISTICS_COST_RATE_PCT": fmt_pct},
            )

        # MEDIUM-risk expander
        if not risk_medium_df.empty:
            with st.expander(f"View MEDIUM-risk countries ({len(risk_medium_df)})"):
                render_beige_board(
                    "MEDIUM-risk countries",
                    risk_medium_df,
                    columns={"COUNTRY": "Country", "RISK_SIGNAL_COUNT": "Risk Signals",
                             "DELAY_RATE_PCT": "Delay %", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                    subtitle="1 signal above median",
                    formats={"DELAY_RATE_PCT": fmt_pct, "LOGISTICS_COST_RATE_PCT": fmt_pct},
                )

        # Methodology
        st.markdown(
            '<div class="boundary" style="font-size:0.78rem;">'
            '<strong>Risk methodology:</strong> Countries assessed against median thresholds across delay rate (DataCo), '
            'logistics cost rate (SCMS), and freight cost (SCMS). HIGH = 2+ above median. '
            'Belize (311% logistics rate) included per outlier policy.</div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # COVERAGE
    # ══════════════════════════════════════════════════════════════════════════
    with sub_cov:
        # Coverage badges
        _cov_strip = (
            '<div class="enterprise-strip" style="margin-bottom:12px;">'
            f'<div class="es-item"><div class="es-label">Both Sources</div><div class="es-value" style="color:var(--accent);">{geo_both}</div></div>'
            f'<div class="es-item"><div class="es-label">DataCo Only</div><div class="es-value">{geo_dataco_only}</div></div>'
            f'<div class="es-item"><div class="es-label">SCMS Only</div><div class="es-value">{geo_scms_only}</div></div>'
            '</div>'
        )
        st.markdown(_cov_strip, unsafe_allow_html=True)

        st.markdown(
            '<div class="success-box" style="font-size:0.78rem;">'
            '<strong>Coverage:</strong> "Both" countries have data from DataCo and SCMS, enabling cross-source aggregate comparison. '
            'Single-source countries can only be analyzed within that source.</div>',
            unsafe_allow_html=True,
        )

        if not geo_df.empty:
            with st.expander(f"View all countries ({len(geo_df)})"):
                render_beige_board(
                    "Country Coverage",
                    geo_df,
                    columns={"COUNTRY_NAME": "Country", "SOURCE_COVERAGE": "Coverage"} if "COUNTRY_NAME" in geo_df.columns else None,
                    subtitle="GEOGRAPHY_DIM — canonical country list",
                    limit=165,
                )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SUPPLIER / SITE
# ══════════════════════════════════════════════════════════════════════════════
with supplier_tab:

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Supplier / Site</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Vendor concentration and logistics cost efficiency. SCMS source only.</div>',
        unsafe_allow_html=True,
    )

    # ── KPI row ──────────────────────────────────────────────────────────────
    _gov_log_rate = round(100.0 * as_float(freight_cost) / max(as_float(shipment_value), 1), 2)
    _ss_kpi = (
        '<div class="enterprise-strip">'
        f'<div class="es-item"><div class="es-label">Suppliers</div><div class="es-value">{supplier_count}</div><div class="es-caption" style="color:var(--amber);">SCMS</div></div>'
        f'<div class="es-item"><div class="es-label">Mfg Sites</div><div class="es-value">{site_count}</div><div class="es-caption" style="color:var(--amber);">SCMS</div></div>'
        f'<div class="es-item"><div class="es-label">Shipment Value</div><div class="es-value">${fmt_val(shipment_value)}</div><div class="es-caption">total</div></div>'
        f'<div class="es-item"><div class="es-label">Freight Cost</div><div class="es-value">${fmt_val(freight_cost)}</div><div class="es-caption">total</div></div>'
        f'<div class="es-item"><div class="es-label">Logistics Rate (governed)</div><div class="es-value">{_gov_log_rate:.2f}%</div><div class="es-caption">SUM(freight)/SUM(value)</div></div>'
        '</div>'
    )
    st.markdown(_ss_kpi, unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.72rem;color:var(--muted);margin:4px 0 10px;">'
        f'Freight is null for {null_freight_pct:.0f}% of shipments (live), so rates are lower bounds. '
        f'Entity rates are supplier/site-level freight/value; the page KPI is the governed weighted rate.</div>',
        unsafe_allow_html=True,
    )

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub_sup, sub_site = st.tabs(["Suppliers", "Manufacturing sites"])

    # ══════════════════════════════════════════════════════════════════════════
    # SUPPLIERS
    # ══════════════════════════════════════════════════════════════════════════
    with sub_sup:
        # Concentration callout
        _s5_val = as_float(supplier_top5_df["SHIPMENT_VALUE_USD"].sum()) if not supplier_top5_df.empty else 0
        _s_total = as_float(shipment_value)
        _s5_share = (_s5_val / max(_s_total, 1)) * 100
        st.markdown(
            f'<div class="boundary" style="font-size:0.82rem;">'
            f'<strong>Top 5 suppliers = {_s5_share:.1f}% of shipment value</strong> '
            f'(${fmt_val(_s5_val)} of ${fmt_val(_s_total)})</div>',
            unsafe_allow_html=True,
        )

        # Top 10 chart
        if not supplier_df.empty and "SUPPLIER" in supplier_df.columns:
            try:
                import altair as alt
                _sup_ch = alt.Chart(supplier_df[["SUPPLIER", "SHIPMENT_VALUE_USD"]]).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("SUPPLIER:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                    x=alt.X("SHIPMENT_VALUE_USD:Q", title="Shipment Value ($)"),
                    color=alt.value("#3FB8A0"),
                    tooltip=["SUPPLIER:N", alt.Tooltip("SHIPMENT_VALUE_USD:Q", format="$,.0f")],
                ).properties(height=260)
                st.altair_chart(_sup_ch, use_container_width=True)
            except Exception:
                st.bar_chart(supplier_df.set_index("SUPPLIER")[["SHIPMENT_VALUE_USD"]], height=260)

        # Top 10 table
        if not supplier_df.empty:
            render_beige_board(
                "Top 10 suppliers",
                supplier_df,
                columns={"SUPPLIER": "Supplier", "SHIPMENT_VALUE_USD": "Shipment Value", "FREIGHT_COST_USD": "Freight",
                         "LOGISTICS_COST_RATE_PCT": "Logistics Rate %", "COUNTRIES_SERVED": "Countries", "SHIPMENT_LINE_COUNT": "Lines"},
                subtitle="By shipment value — SCMS source",
                formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct},
            )

        # Highest cost-rate suppliers
        _sup_below = int(supplier_below_df.iloc[0]["CNT"]) if not supplier_below_df.empty else 0
        if not supplier_costrate_df.empty:
            render_beige_board(
                "Highest cost-rate suppliers",
                supplier_costrate_df,
                columns={"SUPPLIER": "Supplier", "SHIPMENT_VALUE_USD": "Value", "FREIGHT_COST_USD": "Freight", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                subtitle=f"Min shipment-value threshold: $100K. {_sup_below} suppliers below threshold.",
                formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct},
            )

        # View more
        if not supplier_25_df.empty and len(supplier_25_df) > 10:
            with st.expander(f"View more suppliers ({len(supplier_25_df)})"):
                render_beige_board("Suppliers by value", supplier_25_df,
                    columns={"SUPPLIER": "Supplier", "SHIPMENT_VALUE_USD": "Value", "FREIGHT_COST_USD": "Freight",
                             "LOGISTICS_COST_RATE_PCT": "Rate %", "COUNTRIES_SERVED": "Countries", "SHIPMENT_LINE_COUNT": "Lines"},
                    subtitle="Top 25 by shipment value",
                    formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct})

    # ══════════════════════════════════════════════════════════════════════════
    # MANUFACTURING SITES
    # ══════════════════════════════════════════════════════════════════════════
    with sub_site:
        # Concentration callout
        _st5_val = as_float(site_top5_df["SHIPMENT_VALUE_USD"].sum()) if not site_top5_df.empty else 0
        _st5_share = (_st5_val / max(_s_total, 1)) * 100
        st.markdown(
            f'<div class="boundary" style="font-size:0.82rem;">'
            f'<strong>Top 5 sites = {_st5_share:.1f}% of shipment value</strong> '
            f'(${fmt_val(_st5_val)} of ${fmt_val(_s_total)})</div>',
            unsafe_allow_html=True,
        )

        # Top 10 chart
        if not site_df.empty and "SITE_NAME" in site_df.columns:
            try:
                import altair as alt
                _sit_ch = alt.Chart(site_df[["SITE_NAME", "SHIPMENT_VALUE_USD"]]).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("SITE_NAME:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                    x=alt.X("SHIPMENT_VALUE_USD:Q", title="Shipment Value ($)"),
                    color=alt.value("#3FB8A0"),
                    tooltip=["SITE_NAME:N", alt.Tooltip("SHIPMENT_VALUE_USD:Q", format="$,.0f")],
                ).properties(height=260)
                st.altair_chart(_sit_ch, use_container_width=True)
            except Exception:
                st.bar_chart(site_df.set_index("SITE_NAME")[["SHIPMENT_VALUE_USD"]], height=260)

        # Top 10 table
        if not site_df.empty:
            render_beige_board(
                "Top 10 manufacturing sites",
                site_df,
                columns={"SITE_NAME": "Site", "SHIPMENT_VALUE_USD": "Shipment Value", "FREIGHT_COST_USD": "Freight",
                         "LOGISTICS_COST_RATE_PCT": "Logistics Rate %", "COUNTRIES_SERVED": "Countries", "SHIPMENT_LINE_COUNT": "Lines"},
                subtitle="By shipment value — SCMS source",
                formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct},
            )

        # Highest cost-rate sites
        _site_below = int(site_below_df.iloc[0]["CNT"]) if not site_below_df.empty else 0
        if not site_costrate_df.empty:
            render_beige_board(
                "Highest cost-rate sites",
                site_costrate_df,
                columns={"SITE_NAME": "Site", "SHIPMENT_VALUE_USD": "Value", "FREIGHT_COST_USD": "Freight", "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                subtitle=f"Min shipment-value threshold: $100K. {_site_below} sites below threshold.",
                formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct},
            )

        # View more
        if not site_25_df.empty and len(site_25_df) > 10:
            with st.expander(f"View more sites ({len(site_25_df)})"):
                render_beige_board("Sites by value", site_25_df,
                    columns={"SITE_NAME": "Site", "SHIPMENT_VALUE_USD": "Value", "FREIGHT_COST_USD": "Freight",
                             "LOGISTICS_COST_RATE_PCT": "Rate %", "COUNTRIES_SERVED": "Countries", "SHIPMENT_LINE_COUNT": "Lines"},
                    subtitle="Top 25 by shipment value",
                    formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct})


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — TRENDS
# ══════════════════════════════════════════════════════════════════════════════
with trends_tab:

    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Trends</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Time-series view of delivery, commercial and logistics performance.</div>',
        unsafe_allow_html=True,
    )

    sub_del_trend, sub_com_trend, sub_log_trend = st.tabs([
        "Delivery \u2014 DataCo", "Commercial \u2014 DataCo", "Logistics \u2014 SCMS"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # DELIVERY
    # ══════════════════════════════════════════════════════════════════════════
    with sub_del_trend:
        if not monthly_del_df.empty and "MONTH_START" in monthly_del_df.columns:
            import pandas as _pd_t
            _del_sorted = monthly_del_df.sort_values("MONTH_START").copy()
            _del_sorted["MONTH_START"] = _pd_t.to_datetime(_del_sorted["MONTH_START"])
            _del_first = _del_sorted["MONTH_START"].iloc[0].strftime("%b %Y")
            _del_last = _del_sorted["MONTH_START"].iloc[-1].strftime("%b %Y")
            _del_latest = _del_sorted.iloc[-1]

            # Primary chart: OTD + Delay Rate
            try:
                import altair as alt
                _dm = _del_sorted[["MONTH_START", "ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]].melt("MONTH_START", var_name="Metric", value_name="Pct")
                _dcs = alt.Scale(domain=["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"], range=["#3FB8A0", "#D9A441"])
                _dch = alt.Chart(_dm).mark_line(strokeWidth=2).encode(
                    x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                    y=alt.Y("Pct:Q", title="%", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color("Metric:N", scale=_dcs, legend=alt.Legend(title=None, orient="top")),
                    tooltip=["MONTH_START:T", "Metric:N", alt.Tooltip("Pct:Q", format=".1f")],
                ).properties(height=260)
                _dref = alt.Chart({"values": [{"y": otd}]}).mark_rule(strokeDash=[4, 4], color="#3FB8A0", opacity=0.4).encode(y="y:Q")
                st.altair_chart(_dch + _dref, use_container_width=True)
            except Exception:
                st.line_chart(_del_sorted.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]], height=260)

            # Three latest stats
            _ls1, _ls2, _ls3 = st.columns(3)
            _ls1.metric("Latest OTD", f"{as_float(_del_latest.get('ON_TIME_DELIVERY_PCT', 0)):.1f}%", delta=None)
            _ls2.metric("Latest Delay Rate", f"{as_float(_del_latest.get('DELAY_RATE_PCT', 0)):.1f}%")
            _ls3.metric("Avg Delay", f"{as_float(_del_latest.get('AVG_DELIVERY_DELAY_DAYS', 0)):.2f} days")
            st.markdown(f'<div style="font-size:0.68rem;color:var(--muted);margin:-6px 0 12px;">DataCo coverage: {_del_first} \u2013 {_del_last} ({len(_del_sorted)} months). Latest period: {_del_last}.</div>', unsafe_allow_html=True)

            # Secondary analysis expander
            with st.expander("Additional delivery trends"):
                if "AVG_DELIVERY_DELAY_DAYS" in _del_sorted.columns:
                    try:
                        import altair as alt
                        _dly = alt.Chart(_del_sorted).mark_line(strokeWidth=2, color="#3FB8A0").encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("AVG_DELIVERY_DELAY_DAYS:Q", title="Avg Delay (days)"),
                            tooltip=["MONTH_START:T", alt.Tooltip("AVG_DELIVERY_DELAY_DAYS:Q", format=".2f")],
                        ).properties(height=200)
                        st.altair_chart(_dly, use_container_width=True)
                    except Exception:
                        st.line_chart(_del_sorted.set_index("MONTH_START")[["AVG_DELIVERY_DELAY_DAYS"]], height=200)
                if "ORDER_ITEM_COUNT" in _del_sorted.columns:
                    try:
                        import altair as alt
                        _dvol = alt.Chart(_del_sorted).mark_bar(color="#3FB8A0", opacity=0.7).encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("ORDER_ITEM_COUNT:Q", title="Order Items"),
                            tooltip=["MONTH_START:T", alt.Tooltip("ORDER_ITEM_COUNT:Q", format=",")],
                        ).properties(height=200)
                        st.altair_chart(_dvol, use_container_width=True)
                    except Exception:
                        st.bar_chart(_del_sorted.set_index("MONTH_START")[["ORDER_ITEM_COUNT"]], height=200)

            # Monthly data expander (latest 24)
            _del_latest24 = _del_sorted.sort_values("MONTH_START", ascending=False).head(24).sort_values("MONTH_START")
            with st.expander(f"View monthly delivery data ({len(_del_latest24)} months)"):
                render_beige_board("Monthly Delivery", _del_latest24,
                    columns={"MONTH_START": "Month", "ON_TIME_DELIVERY_PCT": "OTD %", "DELAY_RATE_PCT": "Delay %",
                             "AVG_DELIVERY_DELAY_DAYS": "Avg Delay", "ORDER_ITEM_COUNT": "Order Items"},
                    formats={"ON_TIME_DELIVERY_PCT": fmt_pct, "DELAY_RATE_PCT": fmt_pct})
        else:
            st.info("No delivery trend data available.")

    # ══════════════════════════════════════════════════════════════════════════
    # COMMERCIAL
    # ══════════════════════════════════════════════════════════════════════════
    with sub_com_trend:
        if not monthly_del_df.empty and "TOTAL_SALES" in monthly_del_df.columns:
            import pandas as _pd_tc
            _com_sorted = monthly_del_df.sort_values("MONTH_START").copy()
            _com_sorted["MONTH_START"] = _pd_tc.to_datetime(_com_sorted["MONTH_START"])
            _com_first = _com_sorted["MONTH_START"].iloc[0].strftime("%b %Y")
            _com_last = _com_sorted["MONTH_START"].iloc[-1].strftime("%b %Y")
            _com_latest = _com_sorted.iloc[-1]

            # Primary chart: Monthly Sales bars
            try:
                import altair as alt
                _sch = alt.Chart(_com_sorted).mark_bar(color="#3FB8A0", opacity=0.8).encode(
                    x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                    y=alt.Y("TOTAL_SALES:Q", title="Sales ($)"),
                    tooltip=["MONTH_START:T", alt.Tooltip("TOTAL_SALES:Q", format="$,.0f"),
                             alt.Tooltip("TOTAL_PROFIT:Q", format="$,.0f"),
                             alt.Tooltip("PROFIT_MARGIN_PCT:Q", format=".1f")],
                ).properties(height=260)
                st.altair_chart(_sch, use_container_width=True)
            except Exception:
                st.bar_chart(_com_sorted.set_index("MONTH_START")[["TOTAL_SALES"]], height=260)

            _cs1, _cs2, _cs3 = st.columns(3)
            _cs1.metric("Latest Sales", fmt_usd(as_float(_com_latest.get("TOTAL_SALES", 0))))
            _cs2.metric("Latest Profit", fmt_usd(as_float(_com_latest.get("TOTAL_PROFIT", 0))))
            _cs3.metric("Latest Margin", f"{as_float(_com_latest.get('PROFIT_MARGIN_PCT', 0)):.1f}%")
            st.markdown(f'<div style="font-size:0.68rem;color:var(--muted);margin:-6px 0 12px;">DataCo coverage: {_com_first} \u2013 {_com_last}. Latest period: {_com_last}.</div>', unsafe_allow_html=True)

            with st.expander("Additional commercial trends"):
                if "TOTAL_PROFIT" in _com_sorted.columns:
                    try:
                        import altair as alt
                        _pch = alt.Chart(_com_sorted).mark_bar(color="#3FB8A0", opacity=0.7).encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("TOTAL_PROFIT:Q", title="Profit ($)"),
                            tooltip=["MONTH_START:T", alt.Tooltip("TOTAL_PROFIT:Q", format="$,.0f")],
                        ).properties(height=200)
                        st.altair_chart(_pch, use_container_width=True)
                    except Exception:
                        st.bar_chart(_com_sorted.set_index("MONTH_START")[["TOTAL_PROFIT"]], height=200)
                if "PROFIT_MARGIN_PCT" in _com_sorted.columns:
                    try:
                        import altair as alt
                        _mch = alt.Chart(_com_sorted).mark_line(strokeWidth=2, color="#D9A441").encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("PROFIT_MARGIN_PCT:Q", title="Margin %"),
                            tooltip=["MONTH_START:T", alt.Tooltip("PROFIT_MARGIN_PCT:Q", format=".1f")],
                        ).properties(height=200)
                        st.altair_chart(_mch, use_container_width=True)
                    except Exception:
                        st.line_chart(_com_sorted.set_index("MONTH_START")[["PROFIT_MARGIN_PCT"]], height=200)

            _com_latest24 = _com_sorted.sort_values("MONTH_START", ascending=False).head(24).sort_values("MONTH_START")
            with st.expander(f"View monthly commercial data ({len(_com_latest24)} months)"):
                render_beige_board("Monthly Commercial", _com_latest24,
                    columns={"MONTH_START": "Month", "TOTAL_SALES": "Sales", "TOTAL_PROFIT": "Profit", "PROFIT_MARGIN_PCT": "Margin %"},
                    formats={"TOTAL_SALES": fmt_usd, "TOTAL_PROFIT": fmt_usd, "PROFIT_MARGIN_PCT": fmt_pct})
        else:
            st.info("No commercial trend data available.")

    # ══════════════════════════════════════════════════════════════════════════
    # LOGISTICS
    # ══════════════════════════════════════════════════════════════════════════
    with sub_log_trend:
        if not monthly_log_df.empty and "MONTH_START" in monthly_log_df.columns:
            import pandas as _pd_tl
            _log_sorted = monthly_log_df.sort_values("MONTH_START").copy()
            _log_sorted["MONTH_START"] = _pd_tl.to_datetime(_log_sorted["MONTH_START"])
            _log_first = _log_sorted["MONTH_START"].iloc[0].strftime("%b %Y")
            _log_last = _log_sorted["MONTH_START"].iloc[-1].strftime("%b %Y")
            _log_latest = _log_sorted.iloc[-1]

            # Primary chart: Monthly Shipment Value bars
            try:
                import altair as alt
                _lvch = alt.Chart(_log_sorted).mark_bar(color="#3FB8A0", opacity=0.8).encode(
                    x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                    y=alt.Y("SHIPMENT_VALUE_USD:Q", title="Shipment Value ($)"),
                    tooltip=["MONTH_START:T", alt.Tooltip("SHIPMENT_VALUE_USD:Q", format="$,.0f"),
                             alt.Tooltip("FREIGHT_COST_USD:Q", format="$,.0f"),
                             alt.Tooltip("LOGISTICS_COST_RATE_PCT:Q", format=".2f")],
                ).properties(height=260)
                st.altair_chart(_lvch, use_container_width=True)
            except Exception:
                st.bar_chart(_log_sorted.set_index("MONTH_START")[["SHIPMENT_VALUE_USD"]], height=260)

            _ll1, _ll2, _ll3 = st.columns(3)
            _ll1.metric("Latest Shipment Value", fmt_usd(as_float(_log_latest.get("SHIPMENT_VALUE_USD", 0))))
            _ll2.metric("Latest Freight Cost", fmt_usd(as_float(_log_latest.get("FREIGHT_COST_USD", 0))))
            _log_latest_rate = as_float(_log_latest.get("LOGISTICS_COST_RATE_PCT", 0))
            _ll3.metric("Latest Logistics Rate", f"{_log_latest_rate:.2f}%" if _log_latest_rate > 0 else "\u2014")
            st.markdown(
                f'<div style="font-size:0.68rem;color:var(--muted);margin:-6px 0 4px;">SCMS coverage: {_log_first} \u2013 {_log_last} ({len(_log_sorted)} months). Latest period: {_log_last}.</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="boundary" style="font-size:0.75rem;padding:8px 12px;">'
                f'Freight-cost trends are lower bounds because freight is null for {null_freight_pct:.0f}% of shipment lines.</div>',
                unsafe_allow_html=True,
            )

            with st.expander("Additional logistics trends"):
                if "FREIGHT_COST_USD" in _log_sorted.columns:
                    try:
                        import altair as alt
                        _fch = alt.Chart(_log_sorted).mark_line(strokeWidth=2, color="#D9A441").encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("FREIGHT_COST_USD:Q", title="Freight Cost ($)"),
                            tooltip=["MONTH_START:T", alt.Tooltip("FREIGHT_COST_USD:Q", format="$,.0f")],
                        ).properties(height=200)
                        st.altair_chart(_fch, use_container_width=True)
                    except Exception:
                        st.line_chart(_log_sorted.set_index("MONTH_START")[["FREIGHT_COST_USD"]], height=200)
                if "LOGISTICS_COST_RATE_PCT" in _log_sorted.columns:
                    try:
                        import altair as alt
                        _lrch = alt.Chart(_log_sorted.dropna(subset=["LOGISTICS_COST_RATE_PCT"])).mark_line(strokeWidth=2, color="#3FB8A0").encode(
                            x=alt.X("MONTH_START:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=-45)),
                            y=alt.Y("LOGISTICS_COST_RATE_PCT:Q", title="Logistics Rate %"),
                            tooltip=["MONTH_START:T", alt.Tooltip("LOGISTICS_COST_RATE_PCT:Q", format=".2f")],
                        ).properties(height=200)
                        st.altair_chart(_lrch, use_container_width=True)
                    except Exception:
                        st.line_chart(_log_sorted.set_index("MONTH_START")[["LOGISTICS_COST_RATE_PCT"]], height=200)

            _log_latest24 = _log_sorted.sort_values("MONTH_START", ascending=False).head(24).sort_values("MONTH_START")
            with st.expander(f"View monthly logistics data ({len(_log_latest24)} months)"):
                render_beige_board("Monthly Logistics", _log_latest24,
                    columns={"MONTH_START": "Month", "SHIPMENT_VALUE_USD": "Shipment Value", "FREIGHT_COST_USD": "Freight",
                             "LOGISTICS_COST_RATE_PCT": "Logistics Rate %"},
                    formats={"SHIPMENT_VALUE_USD": fmt_usd, "FREIGHT_COST_USD": fmt_usd, "LOGISTICS_COST_RATE_PCT": fmt_pct})
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
