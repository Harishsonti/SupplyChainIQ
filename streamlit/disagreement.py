"""
Phase 2 — Metric Disagreement Detector
Renders OTD variant comparison, persona consistency, and governed-vs-alternative analysis.
"""
import streamlit as st
import html as _html


def load_variant_registry(session):
    return session.sql(
        "SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.OTD_VARIANT_REGISTRY ORDER BY VARIANT_ID"
    ).to_pandas()


def load_persona_consistency(session):
    return session.sql(
        "SELECT * FROM SUPPLYCHAINIQ_COCO.EVALUATION.PERSONA_OTD_CONSISTENCY ORDER BY PERSONA"
    ).to_pandas()


def _bar_html(value, max_val, color, label, is_governed=False):
    pct = min(100.0, (value / max(max_val, 0.01)) * 100)
    gov_badge = ' <span style="background:var(--green);color:#fff;font-size:0.65rem;padding:1px 6px;border-radius:3px;margin-left:6px;font-weight:700;">GOVERNED</span>' if is_governed else ''
    return (
        f'<div style="margin-bottom:10px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">'
        f'<span style="color:var(--text);font-size:0.82rem;font-weight:600;">{_html.escape(label)}{gov_badge}</span>'
        f'<span style="color:var(--beige);font-size:0.85rem;font-weight:700;">{value:.6f}%</span>'
        f'</div>'
        f'<div style="background:var(--panel-2);border-radius:4px;height:22px;overflow:hidden;border:1px solid var(--border);">'
        f'<div style="width:{pct:.1f}%;height:100%;background:{color};border-radius:3px;transition:width 0.3s;"></div>'
        f'</div>'
        f'</div>'
    )


def render_disagreement_detector(session, render_section, render_beige_board):
    variant_df = load_variant_registry(session)
    persona_df = load_persona_consistency(session)

    if variant_df.empty:
        st.info("No OTD variant data available.")
        return

    governed = variant_df[variant_df["GOVERNANCE_STATUS"] == "GOVERNED"]
    alternatives = variant_df[variant_df["GOVERNANCE_STATUS"] == "ALTERNATIVE"]
    governed_val = float(governed.iloc[0]["COMPUTED_VALUE"]) if not governed.empty else 0.0
    max_val = float(variant_df["COMPUTED_VALUE"].max())

    # ── Hero ──
    n_agree = len(variant_df[variant_df["DEVIATION_FROM_GOVERNED"].abs() < 0.001])
    n_disagree = len(variant_df) - n_agree
    max_dev = float(variant_df["DEVIATION_FROM_GOVERNED"].abs().max())

    hero_html = (
        '<div class="hero">'
        '<div class="hero-title">Metric Disagreement Detector</div>'
        '<div class="hero-copy">'
        'OTD (On-Time Delivery %) can be computed multiple defensible ways from the same source data. '
        'This detector compares the <strong>governed definition</strong> against alternative methodologies '
        'to surface hidden analytical disagreements and validate governance alignment.'
        '</div>'
        '<div class="hero-kpis">'
        f'<div class="hero-kpi"><div class="label">Governed OTD</div><div class="value">{governed_val:.2f}%</div><div class="note">Enterprise standard</div></div>'
        f'<div class="hero-kpi"><div class="label">Variants</div><div class="value">{len(variant_df)}</div><div class="note">1 governed + {len(alternatives)} alternatives</div></div>'
        f'<div class="hero-kpi"><div class="label">Converging</div><div class="value">{n_agree}</div><div class="note">Within 0.001pp</div></div>'
        f'<div class="hero-kpi"><div class="label">Max Deviation</div><div class="value">{max_dev:.2f}pp</div><div class="note">Largest disagreement</div></div>'
        '</div></div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    # ── Visual comparison bars ──
    render_section("OTD Variant Comparison")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:12px;">'
        'Each bar shows a defensible OTD calculation. The governed definition is highlighted in green; '
        'alternatives are shown in amber. Matching values confirm methodological alignment.</div>',
        unsafe_allow_html=True,
    )

    bars_html = '<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:20px;">'
    for _, row in variant_df.iterrows():
        is_gov = row["GOVERNANCE_STATUS"] == "GOVERNED"
        color = "var(--green)" if is_gov else "var(--amber)"
        bars_html += _bar_html(
            float(row["COMPUTED_VALUE"]),
            max_val,
            color,
            row["VARIANT_NAME"],
            is_governed=is_gov,
        )
    bars_html += '</div>'
    st.markdown(bars_html, unsafe_allow_html=True)

    # ── Variant detail cards ──
    render_section("Variant Definitions")

    for _, row in variant_df.iterrows():
        is_gov = row["GOVERNANCE_STATUS"] == "GOVERNED"
        severity = "info" if is_gov else "warning"
        badge = "GOVERNED" if is_gov else "ALTERNATIVE — NOT GOVERNED"
        badge_color = "var(--green)" if is_gov else "var(--amber)"
        dev = float(row["DEVIATION_FROM_GOVERNED"])
        dev_text = "Baseline (0.00pp)" if dev == 0 and is_gov else f"{'+' if dev == 0 else ''}{dev:+.6f}pp ({float(row['DEVIATION_PCT']):+.2f}%)"

        card_html = (
            f'<div class="card card-severity-{severity}" style="margin-bottom:14px;">'
            f'<div class="card-title">{_html.escape(row["VARIANT_NAME"])}'
            f' <span style="background:{badge_color};color:#fff;font-size:0.65rem;padding:2px 8px;border-radius:3px;margin-left:8px;">{badge}</span>'
            f'</div>'
            f'<div class="card-body">'
            f'<strong>Value:</strong> {float(row["COMPUTED_VALUE"]):.6f}% &nbsp;&nbsp; <strong>Deviation:</strong> {dev_text}<br>'
            f'<strong>Methodology:</strong> {_html.escape(row["METHODOLOGY"])}<br>'
            f'<strong>Denominator:</strong> {_html.escape(row["DENOMINATOR_TREATMENT"])} &nbsp;&nbsp; <strong>Numerator:</strong> {_html.escape(row["NUMERATOR_LOGIC"])}<br><br>'
            f'{_html.escape(row["ANALYTICAL_RATIONALE"])}'
            f'</div>'
            f'<div class="card-source">SQL: <code>{_html.escape(row["SQL_EXPRESSION"][:120])}</code></div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    # ── Disagreement analysis ──
    render_section("Disagreement Analysis")

    if n_disagree == 0:
        analysis_html = (
            '<div class="success-box">'
            '<strong>No disagreements detected.</strong> All variants converge with the governed definition. '
            'This indicates strong methodological alignment across all available OTD computation approaches.'
            '</div>'
        )
    else:
        disagree_rows = variant_df[variant_df["DEVIATION_FROM_GOVERNED"].abs() >= 0.001]
        items = []
        for _, row in disagree_rows.iterrows():
            items.append(
                f'&bull; <strong>{_html.escape(row["VARIANT_NAME"])}</strong>: '
                f'{float(row["COMPUTED_VALUE"]):.6f}% '
                f'({float(row["DEVIATION_FROM_GOVERNED"]):+.6f}pp) — '
                f'{_html.escape(row["ANALYTICAL_RATIONALE"][:200])}'
            )
        analysis_html = (
            '<div class="boundary">'
            f'<strong>{n_disagree} variant(s) diverge from the governed definition:</strong><br><br>'
            + '<br>'.join(items)
            + '<br><br><em>These disagreements are analytically defensible but highlight that OTD is sensitive to '
            'denominator treatment and the definition of "on-time." The governed definition is the enterprise standard.</em>'
            '</div>'
        )
    st.markdown(analysis_html, unsafe_allow_html=True)

    # ── Persona consistency ──
    render_section("Persona Consistency")
    st.markdown(
        '<div style="color:var(--text-2);font-size:0.85rem;margin-bottom:12px;">'
        'All three operational personas resolve OTD to the same governed definition and value, '
        'ensuring cross-functional alignment.</div>',
        unsafe_allow_html=True,
    )

    if not persona_df.empty:
        all_match = persona_df["MATCHES_GOVERNED"].all()
        status_class = "success-box" if all_match else "boundary"
        status_text = "All personas resolve to the governed OTD value." if all_match else "WARNING: Not all personas resolve to the governed value."

        st.markdown(f'<div class="{status_class}"><strong>{status_text}</strong></div>', unsafe_allow_html=True)

        for _, row in persona_df.iterrows():
            match_icon = "&#x2705;" if row["MATCHES_GOVERNED"] else "&#x26A0;&#xFE0F;"
            persona_html = (
                f'<div style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px 18px;margin-bottom:10px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<span style="color:var(--text);font-weight:700;font-size:0.95rem;">{match_icon} {_html.escape(row["PERSONA"])}</span>'
                f'<span style="color:var(--beige);font-weight:700;">{float(row["RESOLVED_VALUE"]):.6f}%</span>'
                f'</div>'
                f'<div style="color:var(--text-2);font-size:0.82rem;margin-top:4px;">{_html.escape(row["PERSONA_DESCRIPTION"])}</div>'
                f'<div style="color:var(--muted);font-size:0.78rem;margin-top:4px;">{_html.escape(row["RATIONALE"])}</div>'
                f'</div>'
            )
            st.markdown(persona_html, unsafe_allow_html=True)
    else:
        st.info("No persona consistency data available.")

    # ── Full registry table ──
    render_section("Full Variant Registry")
    display_cols = ["VARIANT_ID", "VARIANT_NAME", "GOVERNANCE_STATUS", "COMPUTED_VALUE",
                    "DEVIATION_FROM_GOVERNED", "METHODOLOGY", "DENOMINATOR_TREATMENT"]
    display_df = variant_df[display_cols] if all(c in variant_df.columns for c in display_cols) else variant_df
    render_beige_board(
        "OTD Variant Registry",
        display_df,
        subtitle=f"{len(variant_df)} variants — 1 governed + {len(alternatives)} alternatives",
    )
