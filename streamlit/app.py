import streamlit as st
import json as _json
import html as _html
import decimal as _decimal
import base64 as _b64
import pathlib as _pathlib
from snowflake.snowpark.context import get_active_session
from provenance import parse_agent_response, build_provenance, render_provenance_card
from disagreement import render_disagreement_detector
from readiness import render_readiness_scorecard

def _load_brand_mark():
    try:
        _logo_path = _pathlib.Path(__file__).parent / "supplychainiq_symbol.png"
        _logo_bytes = _logo_path.read_bytes()
        _logo_b64 = _b64.b64encode(_logo_bytes).decode()
        return f'<img src="data:image/png;base64,{_logo_b64}" style="width:36px;height:36px;object-fit:contain;border-radius:6px;" alt="SQ">'
    except Exception:
        return '<div class="brand-mark-fallback">SQ</div>'

_BRAND_MARK_HTML = _load_brand_mark()

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
.brand-mark { width: 36px; height: 36px; border-radius: 6px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.brand-mark-fallback { width: 36px; height: 36px; border-radius: 8px; font-size: 0.85rem; font-weight: 800; display: flex; align-items: center; justify-content: center; background: var(--accent) !important; color: #000; letter-spacing: -0.04em; }
.brand-name { font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
.brand-sub { font-size: 0.75rem; color: var(--muted); margin-top: 1px; }
.live-pill { display: flex; align-items: center; gap: 7px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; color: var(--accent); background: var(--accent-soft); padding: 4px 12px; border-radius: 20px; border: 1px solid var(--border); }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 6px var(--accent); animation: pulse-dot 2s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* ── Tabs ─────────────────────────────────────────────────────────── */
button[data-baseweb="tab"] { background: var(--panel) !important; color: #A9B4BE !important; border: 1px solid var(--border) !important; border-radius: 6px 6px 0 0 !important; font-size: 0.7rem !important; font-weight: 700 !important; letter-spacing: 0.04em !important; text-transform: uppercase !important; padding: 8px 10px !important; margin-right: 2px !important; }
button[data-baseweb="tab"][aria-selected="true"] { background: var(--accent-soft) !important; color: var(--accent) !important; border-bottom: 2px solid var(--accent) !important; font-weight: 700 !important; box-shadow: 0 2px 8px rgba(63,184,160,.18) !important; }
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
    d["supplier_costrate"] = _session.sql("SELECT SUPPLIER, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD WHERE SHIPMENT_VALUE_USD >= 100000 AND LOGISTICS_COST_RATE_PCT IS NOT NULL ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 5").to_pandas()
    d["supplier_below_thresh"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD WHERE SHIPMENT_VALUE_USD < 100000").to_pandas()
    d["site"] = _session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 10").to_pandas()
    d["site_25"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT, COUNTRIES_SERVED, SHIPMENT_LINE_COUNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 25").to_pandas()
    d["site_top5"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 5").to_pandas()
    d["site_costrate"] = _session.sql("SELECT SITE_NAME, SHIPMENT_VALUE_USD, FREIGHT_COST_USD, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD WHERE SHIPMENT_VALUE_USD >= 100000 AND LOGISTICS_COST_RATE_PCT IS NOT NULL ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 5").to_pandas()
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
    d["country_log_rate"] = _session.sql("SELECT COUNTRY, LOGISTICS_COST_RATE_PCT, SHIPMENT_COUNT, FREIGHT_COST_USD FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_LOGISTICS_SCORECARD WHERE LOGISTICS_COST_RATE_PCT IS NOT NULL ORDER BY LOGISTICS_COST_RATE_PCT DESC LIMIT 10").to_pandas()
    d["belize_log"] = _session.sql("SELECT COUNTRY, LOGISTICS_COST_RATE_PCT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_LOGISTICS_SCORECARD WHERE COUNTRY = 'Belize'").to_pandas()
    d["supplier_total_count"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.CORE.SUPPLIER_DIM").to_pandas()
    d["site_total_count"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.CORE.MANUFACTURING_SITE_DIM").to_pandas()
    d["cross_source_count"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD").to_pandas()
    d["cross_source_both"] = _session.sql("SELECT COUNT(*) AS CNT FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD WHERE SOURCE_COVERAGE = 'BOTH'").to_pandas()
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
belize_log_df = _data["belize_log"]
supplier_total_count_df = _data["supplier_total_count"]
site_total_count_df = _data["site_total_count"]
cross_source_count_df = _data["cross_source_count"]
cross_source_both_df = _data["cross_source_both"]
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

# Supplier/site counts (from authoritative dimension tables, not LIMIT 10)
supplier_count = int(supplier_total_count_df.iloc[0]["CNT"]) if not supplier_total_count_df.empty else 0
site_count = int(site_total_count_df.iloc[0]["CNT"]) if not site_total_count_df.empty else 0

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
# Latest run (by timestamp in red_team_summary)
_rt_latest_run = ""
_rt_latest_cases = 0
_rt_latest_passed = 0
if not red_team_summary.empty:
    _rt_last = red_team_summary.iloc[-1]
    _rt_latest_run = str(_rt_last.get("RUN_ID", ""))
    _rt_latest_cases = int(_rt_last.get("TOTAL_CASES", 0))
    _rt_latest_passed = int(_rt_last.get("PASSED", 0))
total_provenance_tests = len(provenance_tests_df) if not provenance_tests_df.empty else 0

# Grand totals (all evaluation artifacts)
grand_total_tests = total_tests + total_red_team + total_provenance_tests
grand_total_passed = all_passed + red_team_passed + total_provenance_tests

# Belize outlier (dedicated query, not from LIMIT 15 by shipment count)
belize_rate = as_float(belize_log_df.iloc[0]["LOGISTICS_COST_RATE_PCT"]) if not belize_log_df.empty else 0


# ══════════════════════════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════════════════════════

_h2 = f'<div class="topbar"> <div class="brand-row"> <div class="brand-mark">{_BRAND_MARK_HTML}</div> <div> <div class="brand-name">SupplyChainIQ</div> <div class="brand-sub">Powered by CoCo</div> </div> </div> <div class="live-pill"><span class="live-dot"></span> LIVE &middot; SNOWFLAKE</div> </div>'
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
        "source": "ENTERPRISE_DELIVERY_SCORECARD \u00b7 OTD_PCT"})

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
    _s5_total_val = as_float(shipment_value)  # authoritative total from ENTERPRISE_LOGISTICS_SCORECARD
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
            _nc_short = _html.escape(_nc_reason[:80].rsplit(" ", 1)[0] + "...") if _nc_reason and len(_nc_reason) > 80 else (_html.escape(_nc_reason) if _nc_reason else "\u2014")
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
                f'{len(_both_df)} countries with both delay and logistics data plotted (GEOGRAPHY_DIM: {len(geo_df)} canonical, {geo_both} in both systems).</div>',
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

    # ── Analyst CSS with premium glow system ──────────────────────────────
    st.markdown("""<style>
/* ── Analyst glow variables ── */
:root {
    --glow-primary: rgba(63,184,160,.35);
    --glow-secondary: rgba(63,184,160,.18);
    --glow-subtle: rgba(63,184,160,.08);
}

/* ── Analyst header ── */
.an-header{margin-bottom:8px;position:relative;}
.an-label{font-size:.58rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);text-shadow:0 0 12px var(--glow-secondary);margin-bottom:4px;}
.an-title{font-size:1.35rem;font-weight:700;color:var(--text);letter-spacing:-.02em;margin:0 0 3px;}
.an-subtitle{font-size:.82rem;color:var(--text-2);line-height:1.4;margin:0 0 2px;}
.an-desc{font-size:.72rem;color:var(--muted);line-height:1.4;}

/* ── Composer glow ── */
.an-composer-row [data-testid="stTextInput"] input {
    background: var(--panel-2) !important;
    border: 1px solid rgba(63,184,160,.3) !important;
    border-radius: 10px !important;
    box-shadow: 0 0 12px var(--glow-subtle), 0 1px 3px rgba(0,0,0,.3) !important;
    color: var(--text) !important;
    padding: 10px 14px !important;
    font-size: .88rem !important;
    transition: box-shadow .2s, border-color .2s;
}
.an-composer-row [data-testid="stTextInput"] input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 20px var(--glow-primary), 0 0 40px var(--glow-subtle), 0 1px 4px rgba(0,0,0,.4) !important;
    outline: none !important;
}
.an-composer-row [data-testid="stTextInput"] input::placeholder {
    color: var(--muted) !important;
    opacity: .7;
}

/* ── Trust strip ── */
.an-trust-strip{display:flex;gap:22px;flex-wrap:wrap;margin:10px 0 16px;font-size:.68rem;color:var(--muted);letter-spacing:.01em;}
.an-trust-strip .an-ti{display:flex;align-items:center;gap:5px;}
.an-trust-strip .an-tc{color:var(--accent);font-size:.72rem;font-weight:600;text-shadow:0 0 6px var(--glow-subtle);}

/* ── Suggestion chips ── */
.an-sg-label{font-size:.58rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin:14px 0 5px;}

/* ── Active tab glow ── */
button[data-baseweb="tab"][aria-selected="true"] {
    box-shadow: 0 2px 8px var(--glow-secondary) !important;
}

/* ── Question card ── */
.an-q{background:var(--panel-2);border-left:3px solid var(--accent);border-radius:4px;padding:10px 14px;margin-bottom:10px;}
.an-q-label{font-size:.55rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;}
.an-q-text{font-size:.85rem;color:var(--text);line-height:1.4;}

/* ── Answer card with glow ── */
.an-answer{background:var(--panel);border:1px solid rgba(63,184,160,.2);border-radius:8px;padding:16px 18px;margin-bottom:10px;box-shadow:0 0 16px var(--glow-subtle),0 1px 3px rgba(0,0,0,.2);}
.an-answer-label{font-size:.55rem;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;text-shadow:0 0 8px var(--glow-subtle);}
.an-answer-body{font-size:.88rem;color:var(--text-2);line-height:1.6;}

/* ── Governed metric card with subtle glow ── */
.an-metric{background:var(--panel-2);border-left:3px solid var(--accent);border-radius:6px;padding:12px 16px;margin-bottom:10px;box-shadow:0 0 10px var(--glow-subtle);}
.an-metric-name{font-size:.62rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;}
.an-metric-value{font-size:1.3rem;font-weight:700;color:var(--accent);margin-bottom:3px;text-shadow:0 0 10px var(--glow-secondary);}
.an-metric-meta{font-size:.72rem;color:var(--muted);line-height:1.5;}

/* ── Trust panel ── */
.an-trust-panel{background:var(--panel-2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;margin-bottom:10px;font-size:.75rem;color:var(--text-2);line-height:1.6;}
.an-trust-panel strong{color:var(--text);}

/* ── Refusal (amber, no teal glow) ── */
.an-refusal{background:var(--amber-soft);border:1px solid var(--amber);border-radius:6px;padding:12px 16px;margin-bottom:10px;}
.an-refusal-label{font-size:.58rem;font-weight:700;color:var(--amber);text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;}
.an-refusal-body{font-size:.82rem;color:var(--text-2);line-height:1.5;}
.an-refusal-body strong{color:var(--text);}

/* ── Subtle background radial glow behind composer ── */
.an-workspace{position:relative;}
.an-workspace::before{content:"";position:absolute;top:40px;left:50%;transform:translateX(-50%);width:70%;height:120px;background:radial-gradient(ellipse,var(--glow-subtle) 0%,transparent 70%);pointer-events:none;z-index:0;}
</style>""", unsafe_allow_html=True)

    # ── State management ──────────────────────────────────────────────────
    _VER = "v7-analyst"
    if st.session_state.get("_analyst_ver") != _VER:
        st.session_state["_analyst_ver"] = _VER
        st.session_state["cur_q"] = ""
        st.session_state["cur_a"] = ""
        st.session_state["cur_prov"] = None
    for k, d in [("cur_q", ""), ("cur_a", ""), ("cur_prov", None), ("preset_q", ""), ("_exec_pending", False)]:
        if k not in st.session_state:
            st.session_state[k] = d

    # ── on_change callback for Enter-to-submit ────────────────────────────
    def _on_analyst_input_change():
        _val = st.session_state.get("analyst_input", "").strip()
        if _val:
            st.session_state["_exec_pending"] = True

    # ── Compact editorial header ──────────────────────────────────────────
    st.markdown('<div class="an-workspace">', unsafe_allow_html=True)
    st.markdown(
        '<div class="an-header">'
        '<div class="an-label">SupplyChainIQ</div>'
        '<div class="an-title">Analyst</div>'
        '<div class="an-subtitle">Governed conversational intelligence for supply-chain decisions.</div>'
        '<div class="an-desc">Ask across governed metrics, source boundaries and data readiness.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Composer (NO form — text_input with on_change for Enter) ──────────
    _pending_preset = st.session_state.get("preset_q", "")
    if _pending_preset:
        st.session_state["analyst_input"] = _pending_preset
        st.session_state["preset_q"] = ""

    st.markdown('<div class="an-composer-row">', unsafe_allow_html=True)
    _cc_input, _cc_btn = st.columns([9, 1])
    with _cc_input:
        user_input = st.text_input(
            "Query",
            placeholder="Ask a supply-chain question...",
            key="analyst_input",
            label_visibility="collapsed",
            on_change=_on_analyst_input_change,
        )
    with _cc_btn:
        ask_clicked = st.button("Ask", type="primary", key="analyst_ask_btn", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)  # close an-workspace

    # ── Trust strip ───────────────────────────────────────────────────────
    st.markdown(
        '<div class="an-trust-strip">'
        '<div class="an-ti"><span class="an-tc">&check;</span> Governed metrics</div>'
        '<div class="an-ti"><span class="an-tc">&check;</span> Source-aware</div>'
        '<div class="an-ti"><span class="an-tc">&check;</span> Provenance-backed</div>'
        '<div class="an-ti"><span class="an-tc">&check;</span> Refuses unsupported analysis</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Suggestion chips (fill-only, outside form) ────────────────────────
    if not st.session_state.cur_q:
        _presets = {
            "Governed Metrics": [
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
        for _grp_label, _grp_qs in _presets.items():
            st.markdown(f'<div class="an-sg-label">{_html.escape(_grp_label)}</div>', unsafe_allow_html=True)
            _pcols = st.columns(len(_grp_qs))
            for _pi, _pq in enumerate(_grp_qs):
                with _pcols[_pi]:
                    if st.button(_pq, key=f"preset_{_pi}_{_grp_label}", use_container_width=True):
                        st.session_state["preset_q"] = _pq

    # ── Single execution path (Enter via on_change OR Ask button) ─────────
    _do_exec = False
    _q_val = (user_input or "").strip()

    if ask_clicked and _q_val:
        _do_exec = True
    elif st.session_state.get("_exec_pending") and _q_val:
        _do_exec = True

    st.session_state["_exec_pending"] = False

    if _do_exec and _q_val:
        st.session_state.cur_q = _q_val
        st.session_state.cur_a = ""
        st.session_state.cur_prov = None
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
                msrc = _html.escape(m.get("SOURCE_SYSTEM") or "\u2014")
                mgrain = _html.escape(m.get("GRAIN") or "\u2014")
                mdefn = _html.escape(m.get("DEFINITION") or "")
                from readiness import get_readiness_for_metric
                rdns = get_readiness_for_metric(m.get("METRIC_ID", ""), session)
                dq_text = "No coverage issues recorded"
                if rdns:
                    null_pct = float(rdns.get("NULL_COVERAGE_PCT", 0))
                    if rdns.get("READINESS_STATUS") == "Certified":
                        dq_text = f'Certified \u00b7 {null_pct:.0f}% null coverage on required inputs'
                    else:
                        dq_text = f'{rdns.get("READINESS_STATUS", "")} \u00b7 {rdns.get("BLOCKING_REASON", "")}'

                src_note = ""
                if msrc == "DataCo":
                    src_note = '<div style="font-size:.68rem;color:var(--muted);margin-top:4px;">SCMS shipment data is maintained as a separate source island and does not contribute to this metric.</div>'

                res_methods = prov_obj.get("provenance_resolution_method", [])
                res_display = []
                for rm_method in res_methods:
                    if rm_method in ("SQL_EXPRESSION_MATCH", "COLUMN_SIGNATURE_MATCH"):
                        res_display.append("Deterministic SQL-based matching")
                    elif rm_method == "ANSWER_TEXT_FALLBACK":
                        res_display.append("Matched from answer text (lower confidence)")
                    elif rm_method == "UNRESOLVED":
                        res_display.append("UNRESOLVED")
                    else:
                        res_display.append(rm_method)
                res_label = ", ".join(sorted(set(res_display))) if res_display else "\u2014"

                st.markdown(
                    f'<div class="an-metric">'
                    f'<div class="an-metric-name">{mid} \u00b7 v{_html.escape(str(mver))}</div>'
                    f'<div class="an-metric-value">{mname}</div>'
                    f'<div class="an-metric-meta">'
                    f'{msrc} \u00b7 {mgrain} \u00b7 Governed<br>'
                    f'{_html.escape(mdefn)}'
                    f'</div>'
                    f'{src_note}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                sv = _html.escape(prov_obj.get("semantic_view") or "SUPPLYCHAINIQ_COCO_SV")
                st.markdown(
                    f'<div class="an-trust-panel">'
                    f'<strong>Semantic model:</strong> {sv}<br>'
                    f'<strong>Resolution:</strong> {_html.escape(res_label)}<br>'
                    f'<strong>Data quality:</strong> {_html.escape(dq_text)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Refusal / readiness card (question-aware filtering) ──
        if is_refusal or readiness_matches:
            # Non-computable metric aliases for question-level detection
            _nc_aliases = {
                "fill rate": "FILL_RATE",
                "days of inventory": "DAYS_OF_INVENTORY",
                "doi": "DAYS_OF_INVENTORY",
                "landed cost": "LANDED_COST",
                "inventory turnover": "INVENTORY_TURNOVER",
                "return rate": "RETURN_RATE",
                "perfect order": "PERFECT_ORDER_RATE",
                "perfect order rate": "PERFECT_ORDER_RATE",
            }
            _q_lower = st.session_state.cur_q.lower()
            _asked_ids = []
            for _alias, _mid in _nc_aliases.items():
                if _alias in _q_lower and _mid not in _asked_ids:
                    _asked_ids.append(_mid)

            if _asked_ids and readiness_matches:
                _primary = [rm for rm in readiness_matches if rm.get("METRIC_ID") in _asked_ids]
                _secondary = [rm for rm in readiness_matches if rm.get("METRIC_ID") not in _asked_ids]
                # Preserve order from question
                _primary.sort(key=lambda rm: _asked_ids.index(rm.get("METRIC_ID")) if rm.get("METRIC_ID") in _asked_ids else 999)
            elif readiness_matches:
                _primary = readiness_matches
                _secondary = []
            else:
                _primary = []
                _secondary = []

            def _render_readiness_card(rm_item):
                blocking = _html.escape(str(rm_item.get("BLOCKING_REASON", "")))
                unlock = _html.escape(str(rm_item.get("WHAT_DATA_WOULD_UNLOCK", "")))
                rname = _html.escape(rm_item.get("METRIC_NAME", ""))
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

            for _rm_p in _primary:
                _render_readiness_card(_rm_p)
            if _secondary:
                with st.expander(f"Other non-computable metrics ({len(_secondary)})"):
                    for _rm_s in _secondary:
                        _render_readiness_card(_rm_s)

            if not readiness_matches and is_refusal:
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
            elif is_refusal:
                st.markdown("*No SQL generated: this request was refused under governance.*")
            else:
                st.markdown("*No SQL captured for this response.*")
            sv_prov = prov_obj.get("semantic_view")
            if sv_prov:
                st.markdown(f"**Semantic model:** `{sv_prov}`")
            elif is_refusal:
                st.markdown("**Semantic model:** governance refusal (no model invoked)")
            else:
                st.markdown("**Semantic model:** \u2014")
            tables = prov_obj.get("tables_used", [])
            if tables:
                st.markdown(f"**Tables:** {', '.join(tables)}")

        # ── Clear ──
        if st.button("Clear", key="clear_analyst"):
            st.session_state.cur_q = ""
            st.session_state.cur_a = ""
            st.session_state.cur_prov = None


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — GOVERNANCE
# ══════════════════════════════════════════════════════════════════════════════
with gov_tab:

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Governance</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Definitions, relationships, readiness and analytical boundaries behind governed supply-chain answers.</div>',
        unsafe_allow_html=True,
    )

    # ── Governance status strip (live counts) ────────────────────────────────
    _gov_metric_cnt = len(metric_reg_df) if not metric_reg_df.empty else 0
    _gov_ready_cnt = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] == "Certified"]) if not metric_readiness_df.empty else 0
    _gov_blocked_cnt = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"]) if not metric_readiness_df.empty else 0
    _gov_sup_rel = len(rel_gov_df[rel_gov_df["STATUS"] == "SUPPORTED"]) if not rel_gov_df.empty else 0
    _gov_unsup_rel = len(rel_gov_df[rel_gov_df["STATUS"] != "SUPPORTED"]) if not rel_gov_df.empty else 0
    _gov_strip = (
        '<div class="enterprise-strip" style="margin-bottom:16px;">'
        f'<div class="es-item"><div class="es-label">Governed Metrics</div><div class="es-value" style="color:var(--accent);">{_gov_metric_cnt}</div></div>'
        f'<div class="es-item"><div class="es-label">Ready</div><div class="es-value" style="color:var(--accent);">{_gov_ready_cnt}</div></div>'
        f'<div class="es-item"><div class="es-label">Blocked</div><div class="es-value" style="color:var(--amber);">{_gov_blocked_cnt}</div></div>'
        f'<div class="es-item"><div class="es-label">Supported Rels</div><div class="es-value" style="color:var(--accent);">{_gov_sup_rel}</div></div>'
        f'<div class="es-item"><div class="es-label">Unsupported Rels</div><div class="es-value" style="color:var(--amber);">{_gov_unsup_rel}</div></div>'
        '</div>'
    )
    st.markdown(_gov_strip, unsafe_allow_html=True)

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    gov_metrics_tab, gov_rels_tab, gov_ready_tab, gov_otd_tab = st.tabs([
        "Metrics", "Relationships", "Readiness", "OTD Variants"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # METRICS
    # ══════════════════════════════════════════════════════════════════════════
    with gov_metrics_tab:
        if not metric_reg_df.empty:
            render_beige_board(
                "Governed metrics",
                metric_reg_df,
                columns={"METRIC_ID": "Metric ID", "METRIC_NAME": "Metric", "DEFINITION": "Definition",
                         "SOURCE_SYSTEM": "Source", "GRAIN": "Grain", "STATUS": "Status"},
                subtitle=f"{_gov_metric_cnt} governed metrics",
                highlight_col="STATUS",
            )
            with st.expander("View governed calculations"):
                for _, _mr in metric_reg_df.iterrows():
                    _mid = _html.escape(str(_mr.get("METRIC_ID", "")))
                    _mname = _html.escape(str(_mr.get("METRIC_NAME", "")))
                    _mver = _html.escape(str(_mr.get("VERSION", "1.0")))
                    _msrc = _html.escape(str(_mr.get("SOURCE_SYSTEM", "")))
                    _mgrain = _html.escape(str(_mr.get("GRAIN", "")))
                    _mdef = _html.escape(str(_mr.get("DEFINITION", "")))
                    _msql = _html.escape(str(_mr.get("SQL_EXPRESSION", "")))
                    st.markdown(
                        f'<div class="card" style="border-left:3px solid var(--accent);margin-bottom:8px;">'
                        f'<div class="card-title">{_mname} <span style="color:var(--muted);font-size:0.68rem;">({_mid} v{_mver})</span></div>'
                        f'<div class="card-body" style="font-size:0.78rem;">{_mdef}<br>'
                        f'<span style="color:var(--muted);">{_msrc} \u00b7 {_mgrain}</span></div>'
                        f'<div style="font-family:monospace;font-size:0.7rem;color:var(--muted);margin-top:4px;background:var(--panel);padding:6px 8px;border-radius:4px;">{_msql}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No metric registry data available.")
        st.markdown('<div style="font-size:0.68rem;color:var(--muted);margin-top:8px;">Source: SEMANTIC.METRIC_REGISTRY</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # RELATIONSHIPS
    # ══════════════════════════════════════════════════════════════════════════
    with gov_rels_tab:
        # Ontology graph (reuse existing live DOT generation)
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

        _dot_lines = ['digraph G {', '  rankdir=TB;', '  bgcolor="transparent";',
            '  node [shape=box,style="filled,rounded",fontname="Helvetica",fontsize=10,fillcolor="#171C21",fontcolor="#E6EDF3",color="#232A31"];',
            '  edge [fontname="Helvetica",fontsize=8];']
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
            _dot_lines.append(f'  {_e} [fillcolor="#232A31",label="{_e.replace("_"," ")}\\n(Bridge)"];')
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
                    _dot_lines.append(f'  {_s} -> {_o} [color="#D9A441",style=dashed,penwidth=1.5,label="blocked",fontcolor="#D9A441"];')
        _dot_lines.append('}')
        _graphviz_ok = hasattr(st, "graphviz_chart")
        if _graphviz_ok:
            try:
                st.graphviz_chart('\n'.join(_dot_lines), use_container_width=True)
            except Exception:
                _graphviz_ok = False
        if not _graphviz_ok:
            _dc_html = " ".join(f'<span class="entity-chip">{_html.escape(e)}</span>' for e in sorted(_dataco_ents))
            _sc_html = " ".join(f'<span class="entity-chip" style="border-color:var(--amber);color:var(--amber);">{_html.escape(e)}</span>' for e in sorted(_scms_ents))
            st.markdown(f'<div class="card card-severity-info"><div class="card-body"><strong style="color:var(--accent);">DataCo</strong>: {_dc_html}<br><br><strong style="color:var(--amber);">SCMS</strong>: {_sc_html}</div></div>', unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:0.75rem;color:var(--muted);margin:4px 0 12px;">'
            'Teal solid = supported join. Amber dashed = blocked (no row-level key). '
            'Country-aggregate comparison is permitted; row-level source joining is not.</div>',
            unsafe_allow_html=True,
        )

        # Relationship governance table
        if not rel_gov_df.empty:
            _supported = rel_gov_df[rel_gov_df["STATUS"] == "SUPPORTED"]
            _unsupported = rel_gov_df[rel_gov_df["STATUS"] != "SUPPORTED"]
            render_beige_board(
                f"Supported relationships ({len(_supported)})",
                _supported,
                columns={"SUBJECT_ENTITY": "From", "RELATIONSHIP": "Relationship", "OBJECT_ENTITY": "To",
                         "STATUS": "Status", "LEFT_KEY": "Join Key", "EVIDENCE": "Evidence"},
                subtitle="Governed entity joins that are analytically valid",
            )
            if not _unsupported.empty:
                st.markdown(
                    f'<div class="boundary" style="margin:8px 0;">'
                    f'<strong>{len(_unsupported)} unsupported relationships</strong> \u2014 blocked by governance constraints.</div>',
                    unsafe_allow_html=True,
                )
                render_beige_board(
                    "Unsupported relationships",
                    _unsupported,
                    columns={"SUBJECT_ENTITY": "From", "RELATIONSHIP": "Relationship", "OBJECT_ENTITY": "To",
                             "STATUS": "Status", "NOTES": "Reason"},
                    subtitle="Entity joins blocked by two-island or other governance constraints",
                )

        with st.expander("View entity catalog"):
            if not entity_cat_df.empty:
                render_beige_board("Entity Catalog", entity_cat_df, subtitle="All governed entities")
        st.markdown('<div style="font-size:0.68rem;color:var(--muted);margin-top:8px;">Source: ONTOLOGY.RELATIONSHIP_GOVERNANCE \u00b7 ONTOLOGY.ENTITY_CATALOG</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # READINESS
    # ══════════════════════════════════════════════════════════════════════════
    with gov_ready_tab:
        if not metric_readiness_df.empty:
            _r_ready = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] == "Certified"])
            _r_blocked = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"])
            _r_strip = (
                '<div class="enterprise-strip" style="margin-bottom:12px;">'
                f'<div class="es-item"><div class="es-label">Ready</div><div class="es-value" style="color:var(--accent);">{_r_ready}</div></div>'
                f'<div class="es-item"><div class="es-label">Blocked</div><div class="es-value" style="color:var(--amber);">{_r_blocked}</div></div>'
                f'<div class="es-item"><div class="es-label">Total</div><div class="es-value">{len(metric_readiness_df)}</div></div>'
                '</div>'
            )
            st.markdown(_r_strip, unsafe_allow_html=True)

            # Readiness matrix
            _rdy_rows = ""
            for _, _rr in metric_readiness_df.iterrows():
                _rn = _html.escape(str(_rr.get("METRIC_NAME", "")))
                _rs = str(_rr.get("READINESS_STATUS", ""))
                _rsrc = _html.escape(str(_rr.get("SOURCE_SYSTEM", "")))
                _rnull = as_float(_rr.get("NULL_COVERAGE_PCT", 0))
                _rblock = str(_rr.get("BLOCKING_REASON", ""))
                _runlock = str(_rr.get("WHAT_DATA_WOULD_UNLOCK", ""))
                if _rs == "Certified":
                    _rbadge = f'<span style="color:var(--accent);font-weight:700;">Certified</span>'
                    _reason = f'Caveat: {_rnull:.0f}% null (excluded)' if _rnull > 0 else '\u2014'
                else:
                    _rbadge = f'<span style="color:var(--amber);font-weight:700;">Blocked</span>'
                    _reason = _html.escape(_rblock[:100] + ("..." if len(_rblock) > 100 else "")) if _rblock and _rblock != "None" else "\u2014"
                _rdy_rows += f'<tr><td>{_rn}</td><td>{_rsrc}</td><td>{_rbadge}</td><td style="font-size:0.72rem;">{_reason}</td></tr>'

            st.markdown(
                '<div class="dark-board"><div class="tbl-title">Metric Readiness</div>'
                f'<div class="tbl-sub">{len(metric_readiness_df)} metrics assessed</div>'
                '<div style="overflow-x:auto;max-height:500px;overflow-y:auto;"><table class="dark-table"><thead><tr>'
                '<th>Metric</th><th>Source</th><th>Readiness</th><th>Coverage / Blocking Reason</th>'
                f'</tr></thead><tbody>{_rdy_rows}</tbody></table></div></div>',
                unsafe_allow_html=True,
            )

            # Blocked detail expander
            _blocked = metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"]
            if not _blocked.empty:
                with st.expander(f"Blocked metrics detail ({len(_blocked)})"):
                    for _, _br in _blocked.iterrows():
                        _bn = _html.escape(str(_br.get("METRIC_NAME", "")))
                        _bb = _html.escape(str(_br.get("BLOCKING_REASON", "")))
                        _bu_raw = _html.escape(str(_br.get("WHAT_DATA_WOULD_UNLOCK", "")))
                        _bu_display = _bu_raw if _bu_raw and _bu_raw != "None" else "\u2014"
                        st.markdown(
                            f'<div class="card" style="border-left:3px solid var(--amber);margin-bottom:8px;">'
                            f'<div class="card-title">{_bn}</div>'
                            f'<div class="card-body" style="font-size:0.78rem;">'
                            f'<strong>Blocked:</strong> {_bb}<br>'
                            f'<strong>Required to unlock:</strong> {_bu_display}'
                            f'</div></div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.info("No readiness data available.")
        st.markdown('<div style="font-size:0.68rem;color:var(--muted);margin-top:8px;">Source: EVALUATION.METRIC_READINESS</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # OTD VARIANTS
    # ══════════════════════════════════════════════════════════════════════════
    with gov_otd_tab:
        st.markdown(
            '<div style="font-size:0.85rem;color:var(--text-2);margin-bottom:12px;">'
            'Different OTD definitions can produce different answers. The governed variant is canonical.</div>',
            unsafe_allow_html=True,
        )
        if not otd_variants_df.empty:
            render_beige_board(
                f"OTD Variant Registry ({len(otd_variants_df)} variants)",
                otd_variants_df,
                columns={"VARIANT_NAME": "Variant", "GOVERNANCE_STATUS": "Status",
                         "DENOMINATOR_TREATMENT": "Denominator", "NUMERATOR_LOGIC": "Numerator",
                         "COMPUTED_VALUE": "OTD %", "DEVIATION_FROM_GOVERNED": "Deviation"},
                subtitle="Each variant represents a valid but different interpretation of On-Time Delivery",
                highlight_col="GOVERNANCE_STATUS",
                formats={"COMPUTED_VALUE": fmt_pct, "DEVIATION_FROM_GOVERNED": fmt_pct},
            )
            _gov_v = otd_variants_df[otd_variants_df["GOVERNANCE_STATUS"] == "GOVERNED"]
            if not _gov_v.empty:
                _gval = as_float(_gov_v.iloc[0].get("COMPUTED_VALUE", 0))
                _gdesc = _html.escape(str(_gov_v.iloc[0].get("DESCRIPTION", "")))
                st.markdown(
                    f'<div class="success-box" style="font-size:0.82rem;">'
                    f'<strong>Canonical: {_gval:.2f}%</strong> \u2014 {_gdesc}</div>',
                    unsafe_allow_html=True,
                )
            with st.expander("Variant methodology details"):
                for _, _vr in otd_variants_df.iterrows():
                    _vn = _html.escape(str(_vr.get("VARIANT_NAME", "")))
                    _vs = _html.escape(str(_vr.get("GOVERNANCE_STATUS", "")))
                    _vd = _html.escape(str(_vr.get("DESCRIPTION", "")))
                    _vm = _html.escape(str(_vr.get("METHODOLOGY", "")))
                    _vc = "var(--accent)" if _vs == "GOVERNED" else "var(--muted)"
                    st.markdown(
                        f'<div class="card" style="border-left:3px solid {_vc};margin-bottom:8px;">'
                        f'<div class="card-title">{_vn} <span style="font-size:0.65rem;color:{_vc};">{_vs}</span></div>'
                        f'<div class="card-body" style="font-size:0.78rem;">{_vd}<br>'
                        f'<span style="color:var(--muted);">Methodology: {_vm}</span></div></div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No OTD variant data available.")
        st.markdown('<div style="font-size:0.68rem;color:var(--muted);margin-top:8px;">Source: EVALUATION.OTD_VARIANT_REGISTRY</div>', unsafe_allow_html=True)

    # ── Governance principle ──────────────────────────────────────────────────
    st.markdown(
        '<div class="card card-severity-info" style="margin-top:16px;">'
        '<div class="card-title">Governance principle</div>'
        '<div class="card-body" style="font-size:0.82rem;">'
        'SupplyChainIQ distinguishes between what is defined, what is computable, '
        'which relationships are permitted, and what the system must refuse. '
        'Blocked metrics and unsupported joins are intentional governance decisions, not errors.'
        '</div></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — TRUST
# ══════════════════════════════════════════════════════════════════════════════
with trust_tab:

    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Trust</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:16px;">'
        'Evidence that the governed definition, data boundaries and Agent behavior remain aligned.</div>',
        unsafe_allow_html=True,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — SAME METRIC, DIFFERENT NUMBERS
    # ══════════════════════════════════════════════════════════════════════════
    render_section("Same English metric, different numbers")

    if not otd_variants_df.empty:
        _tv_gov = otd_variants_df[otd_variants_df["GOVERNANCE_STATUS"] == "GOVERNED"]
        _tv_gov_val = as_float(_tv_gov.iloc[0]["COMPUTED_VALUE"]) if not _tv_gov.empty else 0
        _tv_alts = otd_variants_df[otd_variants_df["GOVERNANCE_STATUS"] != "GOVERNED"]
        _tv_max_div = _tv_alts.loc[_tv_alts["DEVIATION_FROM_GOVERNED"].abs().idxmax()] if not _tv_alts.empty else None
        _tv_max_val = as_float(_tv_max_div["COMPUTED_VALUE"]) if _tv_max_div is not None else _tv_gov_val
        st.markdown(
            f'<div style="font-size:1.05rem;font-weight:700;color:var(--text);margin-bottom:10px;">'
            f'On-time delivery is {_tv_gov_val:.1f}% or {_tv_max_val:.1f}%, depending on the definition.</div>',
            unsafe_allow_html=True,
        )

        # Altair chart: 0-100 axis, dynamic color by agreement
        _tv_chart_ok = False
        try:
            import altair as alt
            _tv_df = otd_variants_df[["VARIANT_NAME", "COMPUTED_VALUE", "GOVERNANCE_STATUS", "DEVIATION_FROM_GOVERNED"]].copy()
            _agree_threshold = 0.05
            def _tv_color(row):
                if row["GOVERNANCE_STATUS"] == "GOVERNED":
                    return "governed"
                elif abs(as_float(row["DEVIATION_FROM_GOVERNED"])) <= _agree_threshold:
                    return "agrees"
                else:
                    return "diverges"
            _tv_df["_color_cat"] = _tv_df.apply(_tv_color, axis=1)
            _tv_cscale = alt.Scale(domain=["governed", "agrees", "diverges"], range=["#3FB8A0", "#2A8A78", "#D9A441"])
            _tv_bars = alt.Chart(_tv_df).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("VARIANT_NAME:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("COMPUTED_VALUE:Q", title="OTD %", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("_color_cat:N", scale=_tv_cscale, legend=None),
                tooltip=["VARIANT_NAME:N", alt.Tooltip("COMPUTED_VALUE:Q", format=".2f"), "GOVERNANCE_STATUS:N"],
            ).properties(height=220)
            _tv_text = _tv_bars.mark_text(align="left", dx=4, fontSize=11).encode(
                text=alt.Text("COMPUTED_VALUE:Q", format=".2f"),
                color=alt.value("#E6EDF3"),
            )
            st.altair_chart(_tv_bars + _tv_text, use_container_width=True)
            _tv_chart_ok = True
        except Exception:
            pass
        if not _tv_chart_ok:
            for _, _vr in otd_variants_df.iterrows():
                _vn = _html.escape(str(_vr.get("VARIANT_NAME", "")))
                _vv = as_float(_vr.get("COMPUTED_VALUE", 0))
                _vs = str(_vr.get("GOVERNANCE_STATUS", ""))
                _vdev = abs(as_float(_vr.get("DEVIATION_FROM_GOVERNED", 999)))
                _vc = "var(--accent)" if _vs == "GOVERNED" else ("var(--accent)" if _vdev <= 0.05 else "var(--amber)")
                _pw = min(_vv, 100)
                st.markdown(f'<div style="margin:3px 0;"><div style="font-size:0.72rem;color:var(--text-2);">{_vn}</div><div style="background:var(--panel);border-radius:3px;height:20px;position:relative;"><div style="background:{_vc};height:100%;width:{_pw:.1f}%;border-radius:3px;"></div><span style="position:absolute;right:6px;top:1px;font-size:0.72rem;color:var(--text);">{_vv:.2f}%</span></div></div>', unsafe_allow_html=True)

        # Three-column explainer
        _ex1, _ex2, _ex3 = st.columns(3)
        with _ex1:
            _g_desc = _html.escape(str(_tv_gov.iloc[0].get("DESCRIPTION", ""))[:120]) if not _tv_gov.empty else ""
            st.markdown(f'<div class="card" style="border-left:3px solid var(--accent);"><div class="card-title" style="font-size:0.78rem;">Governed (V1)</div><div class="card-body" style="font-size:0.72rem;">{_g_desc}</div></div>', unsafe_allow_html=True)
        with _ex2:
            _v4 = otd_variants_df[otd_variants_df["VARIANT_ID"].str.contains("V4", na=False)]
            _v4_desc = _html.escape(str(_v4.iloc[0].get("DESCRIPTION", ""))[:120]) if not _v4.empty else "Strict on-time only."
            st.markdown(f'<div class="card" style="border-left:3px solid var(--amber);"><div class="card-title" style="font-size:0.78rem;">Biggest divergence (V4)</div><div class="card-body" style="font-size:0.72rem;">{_v4_desc}</div></div>', unsafe_allow_html=True)
        with _ex3:
            _v3 = otd_variants_df[otd_variants_df["VARIANT_ID"].str.contains("V3", na=False)]
            _v3_desc = "V3 and V5 independently confirm V1 from different field bases."
            if not _v3.empty:
                _v3_desc = _html.escape(str(_v3.iloc[0].get("DESCRIPTION", ""))[:100]) + " V5 also confirms via numeric comparison."
            st.markdown(f'<div class="card" style="border-left:3px solid var(--accent);"><div class="card-title" style="font-size:0.78rem;">Independent confirmation (V3, V5)</div><div class="card-body" style="font-size:0.72rem;">{_v3_desc}</div></div>', unsafe_allow_html=True)

        with st.expander("Variant details"):
            for _, _vr in otd_variants_df.iterrows():
                _vid = _html.escape(str(_vr.get("VARIANT_ID", "")))
                _vn = _html.escape(str(_vr.get("VARIANT_NAME", "")))
                _vgs = str(_vr.get("GOVERNANCE_STATUS", ""))
                _vdesc = _html.escape(str(_vr.get("DESCRIPTION", "")))
                _vnum = _html.escape(str(_vr.get("NUMERATOR_LOGIC", "")))
                _vden = _html.escape(str(_vr.get("DENOMINATOR_TREATMENT", "")))
                _vsql = _html.escape(str(_vr.get("SQL_EXPRESSION", "")))
                _vmeth = _html.escape(str(_vr.get("METHODOLOGY", "")))
                _vc = "var(--accent)" if _vgs == "GOVERNED" else "var(--muted)"
                st.markdown(
                    f'<div class="card" style="border-left:3px solid {_vc};margin-bottom:6px;">'
                    f'<div class="card-title" style="font-size:0.78rem;">{_vn} <span style="color:{_vc};font-size:0.62rem;">{_vgs}</span></div>'
                    f'<div class="card-body" style="font-size:0.72rem;">{_vdesc}<br>'
                    f'<strong>Numerator:</strong> {_vnum}<br><strong>Denominator:</strong> {_vden}<br>'
                    f'<strong>Method:</strong> {_vmeth}</div>'
                    f'<div style="font-family:monospace;font-size:0.65rem;color:var(--muted);margin-top:4px;background:var(--panel);padding:4px 6px;border-radius:3px;">{_vsql}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("No OTD variant data available.")

    # ── Persona Consistency ──────────────────────────────────────────────────
    render_section("Persona Consistency")

    if not persona_otd_df.empty:
        _p_all_match = all(persona_otd_df["MATCHES_GOVERNED"]) if "MATCHES_GOVERNED" in persona_otd_df.columns else False
        _p_version = str(persona_otd_df.iloc[0].get("PREFERRED_VARIANT_ID", "")) if not persona_otd_df.empty else ""
        _pcols = st.columns(len(persona_otd_df))
        for _pi, (_, _pr) in enumerate(persona_otd_df.iterrows()):
            with _pcols[_pi]:
                _pn = _html.escape(str(_pr.get("PERSONA", "")))
                _pv = as_float(_pr.get("RESOLVED_VALUE", 0))
                _pm = _pr.get("MATCHES_GOVERNED", False)
                _pc = "var(--accent)" if _pm else "var(--amber)"
                _pd_full = str(_pr.get("PERSONA_DESCRIPTION", ""))
                _pd = _html.escape(_pd_full[:80].rsplit(" ", 1)[0] + "..." if len(_pd_full) > 80 else _pd_full)
                st.markdown(
                    f'<div class="card" style="border-left:3px solid {_pc};text-align:center;">'
                    f'<div class="card-title" style="font-size:0.88rem;">{_pn}</div>'
                    f'<div style="font-size:1.3rem;font-weight:800;color:{_pc};margin:6px 0;">{_pv:.6f}%</div>'
                    f'<div style="font-size:0.68rem;color:var(--muted);">{_pd}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        if _p_all_match:
            st.markdown(
                f'<div class="success-box" style="font-size:0.82rem;text-align:center;margin-top:4px;">'
                f'All personas resolve to the same governed definition ({_html.escape(_p_version)}).</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="boundary" style="font-size:0.82rem;">Persona consistency mismatch detected.</div>', unsafe_allow_html=True)
    else:
        st.info("No persona consistency data available.")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — WHAT CAN WE ACTUALLY CALCULATE?
    # ══════════════════════════════════════════════════════════════════════════
    render_section("What can we actually calculate?")

    if not metric_readiness_df.empty:
        _tr_cert = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] == "Certified"])
        _tr_block = len(metric_readiness_df[metric_readiness_df["READINESS_STATUS"] != "Certified"])
        st.markdown(
            f'<div style="font-size:0.92rem;color:var(--text);margin-bottom:10px;">'
            f'<strong style="color:var(--accent);">{_tr_cert} certified</strong>, '
            f'<strong style="color:var(--amber);">{_tr_block} not computable</strong></div>',
            unsafe_allow_html=True,
        )

        _tr_rows = ""
        for _, _rr in metric_readiness_df.iterrows():
            _rn = _html.escape(str(_rr.get("METRIC_NAME", "")))
            _rsrc = _html.escape(str(_rr.get("SOURCE_SYSTEM", "")))
            _rs = str(_rr.get("READINESS_STATUS", ""))
            _rblock = str(_rr.get("BLOCKING_REASON", ""))
            _runlock = str(_rr.get("WHAT_DATA_WOULD_UNLOCK", ""))
            _rnull = as_float(_rr.get("NULL_COVERAGE_PCT", 0))
            if _rs == "Certified":
                _rbadge = '<span style="color:var(--accent);font-weight:700;">Certified</span>'
                _rreason = f'Caveat: {_rnull:.0f}% null coverage (excluded from aggregation)' if _rnull > 0 else "\u2014"
                _runlock_d = "\u2014"
            else:
                _rbadge = '<span style="color:var(--amber);font-weight:700;">Not Computable</span>'
                _rreason = _html.escape(_rblock[:100] + ("..." if len(_rblock) > 100 else "")) if _rblock and _rblock != "None" else "\u2014"
                _runlock_d = _html.escape(_runlock[:80] + ("..." if len(_runlock) > 80 else "")) if _runlock and _runlock != "None" else "\u2014"
            _tr_rows += f'<tr><td>{_rn}</td><td>{_rsrc}</td><td>{_rbadge}</td><td style="font-size:0.72rem;">{_rreason}</td><td style="font-size:0.72rem;">{_runlock_d}</td></tr>'
        st.markdown(
            '<div class="dark-board"><div class="tbl-title">Metric Readiness</div>'
            f'<div class="tbl-sub">{len(metric_readiness_df)} metrics assessed</div>'
            '<div style="overflow-x:auto;max-height:500px;overflow-y:auto;"><table class="dark-table"><thead><tr>'
            '<th>Metric</th><th>Source</th><th>Status</th><th>Blocking Reason</th><th>Required to Unlock</th>'
            f'</tr></thead><tbody>{_tr_rows}</tbody></table></div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No readiness data available.")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — DOES THE AGENT HOLD THE LINE?
    # ══════════════════════════════════════════════════════════════════════════
    render_section("Does the agent hold the line?")

    if not red_team_df.empty:
        _rt_latest_id = _rt_latest_run if _rt_latest_run else (red_team_df["RUN_ID"].iloc[-1] if "RUN_ID" in red_team_df.columns else "")
        _rt_latest = red_team_df[red_team_df["RUN_ID"] == _rt_latest_id]
        _rt_latest_total = len(_rt_latest)
        _rt_latest_passed = int(_rt_latest["PASS_FLAG"].sum()) if "PASS_FLAG" in _rt_latest.columns else 0

        st.markdown(
            f'<div class="success-box" style="font-size:0.92rem;">'
            f'<strong>Latest run {_rt_latest_passed}/{_rt_latest_total} PASS</strong>; '
            f'{total_red_team} case-runs across {red_team_runs} runs</div>',
            unsafe_allow_html=True,
        )

        if not _rt_latest.empty:
            _rt_disp = _rt_latest.copy()
            if "PASS_FLAG" in _rt_disp.columns:
                _rt_disp["RESULT"] = _rt_disp["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
            render_beige_board(
                f"Latest: {_html.escape(str(_rt_latest_id))}",
                _rt_disp,
                columns={"CATEGORY": "Case Class", "EXPECTED_BEHAVIOR": "Expected", "RESULT": "Result"} if all(c in _rt_disp.columns for c in ["CATEGORY", "EXPECTED_BEHAVIOR", "RESULT"]) else {"CATEGORY": "Case Class", "QUESTION": "Question", "RESULT": "Result"} if all(c in _rt_disp.columns for c in ["CATEGORY", "QUESTION", "RESULT"]) else None,
                subtitle=f"{_rt_latest_passed}/{_rt_latest_total} passed",
            )

        with st.expander("View full Red Team history"):
            _rt_hist = red_team_df.copy()
            if "PASS_FLAG" in _rt_hist.columns:
                _rt_hist["RESULT"] = _rt_hist["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
            render_beige_board("Red Team History", _rt_hist, subtitle=f"All {total_red_team} case-runs across {red_team_runs} runs")

        st.markdown(
            '<div style="font-size:0.72rem;color:var(--muted);margin-top:8px;font-style:italic;">'
            'The agent follows governed formulas through its instructions; red-team tests verify behavior but are not a mathematical guarantee.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No red team results available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — EVALUATION & TRUST CONTRACT
# ══════════════════════════════════════════════════════════════════════════════
with eval_tab:

    st.markdown(
        '<div class="section-title" style="font-size:1.35rem;margin-bottom:2px;">Evaluation &amp; Trust Contract</div>'
        '<div style="font-size:0.82rem;color:var(--muted);margin-bottom:14px;">'
        'Executable validation contract behind SupplyChainIQ governed answers.</div>',
        unsafe_allow_html=True,
    )

    # ── KPI row ──────────────────────────────────────────────────────────────
    _ev_exec = total_smoke + total_red_team + total_provenance_tests
    _ev_kpi = (
        '<div class="enterprise-strip" style="margin-bottom:6px;">'
        f'<div class="es-item"><div class="es-label">Executable Tests</div><div class="es-value">{_ev_exec}</div></div>'
        f'<div class="es-item"><div class="es-label">Smoke Pass Rate</div><div class="es-value" style="color:var(--accent);">{pass_rate:.0f}%</div></div>'
        f'<div class="es-item"><div class="es-label">Red Team</div><div class="es-value">{red_team_passed}/{total_red_team} PASS</div><div class="es-caption">{red_team_runs} runs, latest {_rt_latest_passed}/{_rt_latest_cases}</div></div>'
        f'<div class="es-item"><div class="es-label">Provenance Tests</div><div class="es-value">{total_provenance_tests}</div></div>'
        '</div>'
    )
    st.markdown(_ev_kpi, unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.68rem;color:var(--muted);margin-bottom:14px;">'
        f'{_ev_exec} executable tests (smoke, red-team case-runs, provenance). '
        f'{_otd_var_count} OTD variants and {_readiness_count} readiness assessments are registry entries, not tests.</div>',
        unsafe_allow_html=True,
    )

    # ── Sub-tabs (no Red Team — lives in Trust) ──────────────────────────────
    eval_overview, eval_smoke_tab, eval_prov_tab, eval_detail_tab = st.tabs([
        "Overview", "Smoke Tests", "Provenance", "Details"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # OVERVIEW
    # ══════════════════════════════════════════════════════════════════════════
    with eval_overview:
        # Suite summary cards
        _suite_html = '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px;">'
        _suite_html += (
            f'<div class="card card-severity-info"><div class="card-title">Smoke</div>'
            f'<div class="card-body">{smoke_passed}/{total_smoke} passed ({pass_rate:.0f}%)<br>'
            f'<span style="font-size:0.72rem;color:var(--muted);">Validates core governed UI/semantic behavior.</span></div></div>'
        )
        _suite_html += (
            f'<div class="card card-severity-info"><div class="card-title">Red Team</div>'
            f'<div class="card-body">{red_team_passed}/{total_red_team} across {red_team_runs} runs<br>'
            f'<span style="font-size:0.72rem;color:var(--muted);">Tests Agent governance boundaries and refusal behavior.</span></div></div>'
        )
        _suite_html += (
            f'<div class="card card-severity-info"><div class="card-title">Provenance</div>'
            f'<div class="card-body">{total_provenance_tests} resolution tests<br>'
            f'<span style="font-size:0.72rem;color:var(--muted);">Tests whether answers resolve to governed metric evidence.</span></div></div>'
        )
        _suite_html += '</div>'
        st.markdown(_suite_html, unsafe_allow_html=True)

        if pass_rate >= 95:
            st.markdown(
                f'<div class="success-box" style="font-size:0.82rem;">'
                f'<strong>All suites healthy:</strong> {pass_rate:.1f}% smoke pass rate. '
                f'{red_team_passed}/{total_red_team} red-team case-runs passed. '
                f'Governance operating within expectations.</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div style="font-size:0.78rem;color:var(--muted);margin-top:8px;">'
            'Red Team evidence is presented in Trust.</div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # SMOKE TESTS
    # ══════════════════════════════════════════════════════════════════════════
    with eval_smoke_tab:
        if not eval_smoke_results.empty:
            _sm1, _sm2, _sm3 = st.columns(3)
            _sm1.metric("Total", f"{total_smoke}")
            _sm2.metric("Passed", f"{smoke_passed}")
            _sm_pct = (smoke_passed / max(total_smoke, 1)) * 100
            _sm3.metric("Pass Rate", f"{_sm_pct:.1f}%")

            with st.expander(f"View smoke test results ({total_smoke})"):
                _smoke_disp = eval_smoke_results.copy()
                _smoke_disp["RESULT"] = _smoke_disp["PASS_FLAG"].map({True: "PASS", False: "FAIL"})
                render_beige_board("Smoke Tests", _smoke_disp,
                    columns={"TEST_ID": "Test", "EXPECTED_VALUE": "Expected", "ACTUAL_VALUE": "Actual", "RESULT": "Result"},
                    subtitle="Latest run")

            if smoke_failed > 0:
                _failed = eval_smoke_results[~eval_smoke_results["PASS_FLAG"]].copy()
                _failed["RESULT"] = "FAIL"
                st.markdown(f'<div class="boundary"><strong>{smoke_failed} test(s) failed.</strong></div>', unsafe_allow_html=True)
                render_beige_board("Failed Tests", _failed,
                    columns={"TEST_ID": "Test", "EXPECTED_VALUE": "Expected", "ACTUAL_VALUE": "Actual"},
                    subtitle="Investigate for regressions")
        else:
            st.info("No smoke test results available.")

    # ══════════════════════════════════════════════════════════════════════════
    # PROVENANCE
    # ══════════════════════════════════════════════════════════════════════════
    with eval_prov_tab:
        if not provenance_tests_df.empty:
            _pv1, _pv2 = st.columns(2)
            _pv1.metric("Provenance Tests", f"{total_provenance_tests}")
            if "EXPECTED_RESOLUTION" in provenance_tests_df.columns:
                _pv2.metric("Resolution Strategies", f"{provenance_tests_df['EXPECTED_RESOLUTION'].nunique()}")

            st.markdown(
                '<div style="color:var(--text-2);font-size:0.82rem;margin-bottom:10px;">'
                'Verifies the three-tier resolution strategy: SQL_EXPRESSION_MATCH, '
                'COLUMN_SIGNATURE_MATCH, and ANSWER_TEXT_FALLBACK.</div>',
                unsafe_allow_html=True,
            )
            render_beige_board("Provenance Test Definitions", provenance_tests_df,
                subtitle="Test cases for metric resolution from agent SQL and response text")
        else:
            st.info("No provenance test definitions available.")

    # ══════════════════════════════════════════════════════════════════════════
    # DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    with eval_detail_tab:
        if not eval_smoke_results.empty:
            with st.expander(f"Smoke test details ({len(eval_smoke_results)})"):
                render_beige_board("Smoke Details", eval_smoke_results, subtitle="Complete smoke results")
        if not eval_bench_results.empty:
            with st.expander(f"Benchmark details ({len(eval_bench_results)})"):
                render_beige_board("Benchmark Details", eval_bench_results, subtitle="Benchmark execution details")
        if not eval_smoke_summary.empty:
            with st.expander("Smoke summary"):
                render_beige_board("Smoke Summary", eval_smoke_summary, subtitle="Aggregated results")

        # Test health
        _health_sev = "info" if pass_rate >= 95 else "warning" if pass_rate >= 80 else "critical"
        _health_msg = "All systems nominal." if pass_rate >= 95 else "Some tests require attention." if pass_rate >= 80 else "Immediate investigation required."
        st.markdown(
            f'<div class="card card-severity-{_health_sev}" style="margin-top:10px;">'
            f'<div class="card-title">Test Health</div>'
            f'<div class="card-body">'
            f'<strong>{_ev_exec}</strong> executable tests. '
            f'Smoke: {smoke_passed}/{total_smoke}. '
            f'Red Team: {red_team_passed}/{total_red_team} across {red_team_runs} runs. '
            f'Provenance: {total_provenance_tests}. '
            f'Registry: {_otd_var_count} OTD variants + {_readiness_count} readiness assessments.<br>'
            f'{_health_msg}'
            f'</div></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    '<div class="footer-line">SupplyChainIQ &middot; Powered by CoCo &middot; Governed supply-chain operating '
    'intelligence &middot; SUPPLYCHAINIQ_COCO</div>',
    unsafe_allow_html=True,
)
