"""
Phase 3 — Data Readiness Scorecard
Renders metric readiness assessment in the Governance tab and provides
readiness lookup for the provenance/refusal experience.
"""
import streamlit as st
import html as _html


@st.cache_data(ttl=600)
def _load_metric_readiness(_session):
    return _session.sql(
        "SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.METRIC_READINESS ORDER BY READINESS_STATUS, METRIC_ID"
    ).to_pandas()


def get_readiness_for_metric(metric_name, session):
    """Look up readiness info for a metric by name or partial match.
    Returns dict or None."""
    df = _load_metric_readiness(session)
    if df.empty:
        return None
    name_lower = metric_name.lower()
    for _, row in df.iterrows():
        if name_lower in row["METRIC_NAME"].lower() or name_lower in row["METRIC_ID"].lower():
            return row.to_dict()
    return None


def get_readiness_for_text(text, session):
    """Scan agent response text for mentions of non-computable metrics and return readiness info."""
    df = _load_metric_readiness(session)
    if df.empty:
        return []
    nc = df[df["READINESS_STATUS"] == "Not Computable"]
    matches = []
    text_lower = text.lower()
    for _, row in nc.iterrows():
        name_lower = row["METRIC_NAME"].lower()
        id_lower = row["METRIC_ID"].lower().replace("_", " ")
        if name_lower in text_lower or id_lower in text_lower:
            matches.append(row.to_dict())
    return matches


def render_readiness_scorecard(session, render_section, render_beige_board):
    df = _load_metric_readiness(session)
    if df.empty:
        st.info("No metric readiness data available.")
        return

    certified = df[df["READINESS_STATUS"] == "Certified"]
    not_comp = df[df["READINESS_STATUS"] == "Not Computable"]
    n_cert = len(certified)
    n_nc = len(not_comp)
    cert_zero_null = len(certified[certified["NULL_COVERAGE_PCT"] == 0])
    cert_with_null = len(certified[certified["NULL_COVERAGE_PCT"] > 0])

    # Hero
    hero_html = (
        '<div class="hero">'
        '<div class="hero-title">Data Readiness Scorecard</div>'
        '<div class="hero-copy">'
        'Assesses computability of every canonical supply-chain metric against actual source data. '
        'Certified metrics have governed definitions and all required inputs. '
        'Not Computable metrics are explicitly documented with blocking reasons and what data would unlock them.'
        '</div>'
        '<div class="hero-kpis">'
        f'<div class="hero-kpi"><div class="label">Total Metrics</div><div class="value">{len(df)}</div><div class="note">Canonical set</div></div>'
        f'<div class="hero-kpi"><div class="label">Certified</div><div class="value">{n_cert}</div><div class="note">{cert_zero_null} perfect, {cert_with_null} with data notes</div></div>'
        f'<div class="hero-kpi"><div class="label">Not Computable</div><div class="value">{n_nc}</div><div class="note">Missing inputs</div></div>'
        f'<div class="hero-kpi"><div class="label">Readiness</div><div class="value">{100*n_cert//len(df)}%</div><div class="note">{n_cert}/{len(df)} certified</div></div>'
        '</div></div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    # Certified metrics
    render_section("Certified Metrics")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:12px;">'
        'These metrics have governed definitions and all required inputs present in source data.</div>',
        unsafe_allow_html=True,
    )

    for _, row in certified.iterrows():
        null_pct = float(row["NULL_COVERAGE_PCT"])
        null_note = ""
        if null_pct > 0:
            null_note = (
                f' <span style="background:var(--amber);color:#000;font-size:0.65rem;'
                f'padding:1px 6px;border-radius:3px;margin-left:6px;">'
                f'{null_pct:.1f}% null coverage</span>'
            )

        card_html = (
            f'<div style="background:var(--panel);border:1px solid var(--border);'
            f'border-left:3px solid var(--green);border-radius:8px;padding:14px 18px;margin-bottom:10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="color:var(--text);font-weight:700;font-size:0.95rem;">'
            f'{_html.escape(row["METRIC_NAME"])}{null_note}</span>'
            f'<span style="background:var(--green);color:#fff;font-size:0.65rem;'
            f'padding:2px 8px;border-radius:3px;font-weight:700;">CERTIFIED</span>'
            f'</div>'
            f'<div style="color:var(--text-2);font-size:0.82rem;margin-top:4px;">'
            f'<strong>Source:</strong> {_html.escape(row["SOURCE_SYSTEM"])} &nbsp; '
            f'<strong>Grain:</strong> {_html.escape(row["GRAIN"])} &nbsp; '
            f'<strong>Inputs:</strong> {_html.escape(row["REQUIRED_INPUTS"])}'
            f'</div>'
            f'<div style="color:var(--muted);font-size:0.78rem;margin-top:4px;">'
            f'<code style="font-size:0.75rem;">{_html.escape(str(row["GOVERNED_DEFINITION"] or ""))}</code>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    # Not Computable metrics
    render_section("Not Computable Metrics")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:12px;">'
        'These canonical supply-chain metrics cannot be computed from available source data. '
        'The agent will decline requests for these metrics with an explanation.</div>',
        unsafe_allow_html=True,
    )

    for _, row in not_comp.iterrows():
        card_html = (
            f'<div style="background:var(--panel);border:1px solid var(--border);'
            f'border-left:3px solid var(--amber);border-radius:8px;padding:14px 18px;margin-bottom:10px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<span style="color:var(--text);font-weight:700;font-size:0.95rem;">'
            f'{_html.escape(row["METRIC_NAME"])}</span>'
            f'<span style="background:var(--amber);color:#000;font-size:0.65rem;'
            f'padding:2px 8px;border-radius:3px;font-weight:700;">NOT COMPUTABLE</span>'
            f'</div>'
            f'<div style="color:var(--text-2);font-size:0.82rem;margin-top:6px;">'
            f'<strong>Required inputs:</strong> {_html.escape(row["REQUIRED_INPUTS"])}'
            f'</div>'
            f'<div style="color:#e8ae55;font-size:0.82rem;margin-top:4px;">'
            f'<strong>Blocking reason:</strong> {_html.escape(str(row["BLOCKING_REASON"] or ""))}'
            f'</div>'
            f'<div style="color:var(--green);font-size:0.82rem;margin-top:4px;">'
            f'<strong>What would unlock:</strong> {_html.escape(str(row["WHAT_DATA_WOULD_UNLOCK"] or ""))}'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    # Summary table
    render_section("Full Readiness Registry")
    display_cols = ["METRIC_ID", "METRIC_NAME", "READINESS_STATUS", "SOURCE_SYSTEM",
                    "NULL_COVERAGE_PCT", "INPUTS_PRESENT"]
    display_df = df[display_cols] if all(c in df.columns for c in display_cols) else df
    render_beige_board(
        "Metric Readiness",
        display_df,
        subtitle=f"{len(df)} metrics assessed — {n_cert} certified, {n_nc} not computable",
    )
