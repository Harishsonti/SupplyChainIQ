import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

st.header("Country Risk Assessment")
st.caption("Cross-source comparison at country-aggregate level (the only valid cross-source join)")

scorecard = session.sql("""
    SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD
    ORDER BY SOURCE_COVERAGE DESC, COUNTRY
""").to_pandas()

tab1, tab2, tab3 = st.tabs(["Cross-Source Scorecard", "Risk Assessment", "Coverage Map"])

with tab1:
    coverage_filter = st.multiselect("Source Coverage", ["BOTH", "DATACO_ONLY", "SCMS_ONLY"],
                                      default=["BOTH"])
    filtered = scorecard[scorecard["SOURCE_COVERAGE"].isin(coverage_filter)] if coverage_filter else scorecard
    st.dataframe(filtered, use_container_width=True)

with tab2:
    risk = session.sql("""
        SELECT COUNTRY, RISK_TIER, ON_TIME_DELIVERY_PCT, DELAY_RATE_PCT,
            LOGISTICS_COST_RATE_PCT, FREIGHT_COST_USD, RISK_SIGNAL_COUNT
        FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT
        ORDER BY RISK_SIGNAL_COUNT DESC, COUNTRY
    """).to_pandas()

    tier_filter = st.multiselect("Risk Tier", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM"])
    filtered_risk = risk[risk["RISK_TIER"].isin(tier_filter)] if tier_filter else risk
    st.dataframe(filtered_risk, use_container_width=True)

    st.subheader("Risk Distribution")
    risk_dist = risk.groupby("RISK_TIER").size().reset_index(name="COUNT")
    st.bar_chart(risk_dist.set_index("RISK_TIER"))

with tab3:
    geo = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.CORE.GEOGRAPHY_DIM").to_pandas()
    coverage_counts = geo.groupby("SOURCE_COVERAGE").size().reset_index(name="COUNT")
    st.bar_chart(coverage_counts.set_index("SOURCE_COVERAGE"))
    st.metric("Total Countries", len(geo))
    st.metric("Countries in Both Systems", len(geo[geo["SOURCE_COVERAGE"] == "BOTH"]))
