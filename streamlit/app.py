import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

st.set_page_config(page_title="SupplyChainIQ CoCo", layout="wide")
st.title("SupplyChainIQ CoCo")
st.caption("Supply Chain Intelligence — Governed Analytics across DataCo & SCMS")

tab_exec, tab_delivery, tab_logistics, tab_country, tab_agent = st.tabs([
    "Executive Summary", "Delivery Performance", "Logistics & Cost", "Country Risk", "AI Assistant"
])

# ── Executive Summary ──────────────────────────────────────────────────────────
with tab_exec:
    delivery = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_DELIVERY_SCORECARD").collect()
    logistics = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.ENTERPRISE_LOGISTICS_SCORECARD").collect()

    if delivery and logistics:
        d = delivery[0]
        l = logistics[0]

        st.subheader("Delivery Performance (DataCo)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("On-Time Delivery", f"{d['ON_TIME_DELIVERY_PCT']:.2f}%")
        c2.metric("Delay Rate", f"{d['DELAY_RATE_PCT']:.2f}%")
        c3.metric("Avg Delay", f"{d['AVG_DELIVERY_DELAY_DAYS']:.2f} days")
        c4.metric("Orders", f"{d['ORDER_COUNT']:,}")

        st.subheader("Commercial Performance (DataCo)")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Total Sales", f"${d['TOTAL_SALES']:,.0f}")
        c6.metric("Total Profit", f"${d['TOTAL_PROFIT']:,.0f}")
        c7.metric("Profit Margin", f"{d['PROFIT_MARGIN_PCT']:.2f}%")
        c8.metric("Order Items", f"{d['ORDER_ITEM_COUNT']:,}")

        st.subheader("Logistics Performance (SCMS)")
        c9, c10, c11, c12 = st.columns(4)
        c9.metric("Shipments", f"{l['SHIPMENT_COUNT']:,}")
        c10.metric("Freight Cost", f"${l['TOTAL_FREIGHT_COST']:,.0f}")
        c11.metric("Logistics Rate", f"{l['LOGISTICS_COST_RATE_PCT']:.2f}%")
        c12.metric("Null Freight %", f"{l['NULL_FREIGHT_PCT']:.1f}%")

        st.subheader("Data Quality")
        dq = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.DATA_QUALITY_SCORECARD").to_pandas()
        st.dataframe(dq, use_container_width=True)

# ── Delivery Performance ───────────────────────────────────────────────────────
with tab_delivery:
    st.subheader("Monthly On-Time Delivery Trend")
    trend = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_DELIVERY_TREND").to_pandas()
    if not trend.empty:
        st.line_chart(trend.set_index("MONTH_START")[["ON_TIME_DELIVERY_PCT", "DELAY_RATE_PCT"]])

        st.subheader("Monthly Sales Trend")
        st.bar_chart(trend.set_index("MONTH_START")["TOTAL_SALES"])

    st.subheader("Delivery by Shipping Mode")
    mode_data = session.sql("""
        SELECT SHIPPING_MODE,
            COUNT(*) AS ITEMS,
            ROUND(100.0 * COUNT_IF(DELIVERY_STATUS IN ('Advance shipping','Shipping on time'))
                / NULLIF(COUNT_IF(DELIVERY_STATUS != 'Shipping canceled'), 0), 2) AS OTD_PCT,
            ROUND(SUM(SALES), 0) AS SALES
        FROM SUPPLYCHAINIQ_COCO.CORE.ORDER_ITEM_FACT
        GROUP BY SHIPPING_MODE ORDER BY SALES DESC
    """).to_pandas()
    st.dataframe(mode_data, use_container_width=True)

    st.subheader("Delivery Status Breakdown")
    status = session.sql("""
        SELECT DELIVERY_STATUS, COUNT(*) AS ITEM_COUNT,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS PCT
        FROM SUPPLYCHAINIQ_COCO.CORE.ORDER_ITEM_FACT
        GROUP BY DELIVERY_STATUS ORDER BY ITEM_COUNT DESC
    """).to_pandas()
    st.dataframe(status, use_container_width=True)

    st.subheader("Country Delivery Scorecard (Top 20)")
    country_del = session.sql("""
        SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD
        ORDER BY ORDER_ITEM_COUNT DESC LIMIT 20
    """).to_pandas()
    st.dataframe(country_del, use_container_width=True)

# ── Logistics & Cost ───────────────────────────────────────────────────────────
with tab_logistics:
    st.subheader("Monthly Freight Cost Trend")
    ltend = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_LOGISTICS_TREND").to_pandas()
    if not ltend.empty:
        st.line_chart(ltend.set_index("MONTH_START")[["FREIGHT_COST_USD", "LOGISTICS_COST_RATE_PCT"]])

    st.subheader("Supplier Scorecard (Top 20 by Shipment Value)")
    suppliers = session.sql("""
        SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD
        ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 20
    """).to_pandas()
    st.dataframe(suppliers, use_container_width=True)

    st.subheader("Manufacturing Site Scorecard (Top 20)")
    sites = session.sql("""
        SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MANUFACTURING_SITE_SCORECARD
        ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 20
    """).to_pandas()
    st.dataframe(sites, use_container_width=True)

    st.subheader("Shipment Mode Analysis (SCMS)")
    modes = session.sql("""
        SELECT SHIPMENT_MODE, COUNT(*) AS SHIPMENT_COUNT,
            ROUND(SUM(LINE_ITEM_VALUE), 0) AS TOTAL_VALUE,
            ROUND(SUM(FREIGHT_COST_USD), 0) AS FREIGHT_COST,
            ROUND(100.0 * SUM(FREIGHT_COST_USD) / NULLIF(SUM(LINE_ITEM_VALUE), 0), 2) AS LOGISTICS_RATE_PCT
        FROM SUPPLYCHAINIQ_COCO.CORE.SCMS_SHIPMENT_FACT
        GROUP BY SHIPMENT_MODE ORDER BY TOTAL_VALUE DESC
    """).to_pandas()
    st.dataframe(modes, use_container_width=True)

# ── Country Risk ───────────────────────────────────────────────────────────────
with tab_country:
    st.caption("Cross-source comparison at country-aggregate level (the only valid cross-source join)")

    subtab1, subtab2, subtab3 = st.tabs(["Cross-Source Scorecard", "Risk Assessment", "Coverage Map"])

    with subtab1:
        scorecard = session.sql("""
            SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_CROSS_SOURCE_SCORECARD
            ORDER BY SOURCE_COVERAGE DESC, COUNTRY
        """).to_pandas()
        coverage_filter = st.multiselect("Source Coverage", ["BOTH", "DATACO_ONLY", "SCMS_ONLY"],
                                          default=["BOTH"], key="cov_filter")
        filtered = scorecard[scorecard["SOURCE_COVERAGE"].isin(coverage_filter)] if coverage_filter else scorecard
        st.dataframe(filtered, use_container_width=True)

    with subtab2:
        risk = session.sql("""
            SELECT COUNTRY, RISK_TIER, ON_TIME_DELIVERY_PCT, DELAY_RATE_PCT,
                LOGISTICS_COST_RATE_PCT, FREIGHT_COST_USD, RISK_SIGNAL_COUNT
            FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_RISK_ASSESSMENT
            ORDER BY RISK_SIGNAL_COUNT DESC, COUNTRY
        """).to_pandas()
        tier_filter = st.multiselect("Risk Tier", ["HIGH", "MEDIUM", "LOW"],
                                      default=["HIGH", "MEDIUM"], key="risk_filter")
        filtered_risk = risk[risk["RISK_TIER"].isin(tier_filter)] if tier_filter else risk
        st.dataframe(filtered_risk, use_container_width=True)

        st.subheader("Risk Distribution")
        risk_dist = risk.groupby("RISK_TIER").size().reset_index(name="COUNT")
        st.bar_chart(risk_dist.set_index("RISK_TIER"))

    with subtab3:
        geo = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.CORE.GEOGRAPHY_DIM").to_pandas()
        coverage_counts = geo.groupby("SOURCE_COVERAGE").size().reset_index(name="COUNT")
        st.bar_chart(coverage_counts.set_index("SOURCE_COVERAGE"))
        gc1, gc2 = st.columns(2)
        gc1.metric("Total Countries", len(geo))
        gc2.metric("Countries in Both Systems", len(geo[geo["SOURCE_COVERAGE"] == "BOTH"]))

# ── AI Assistant ───────────────────────────────────────────────────────────────
with tab_agent:
    st.subheader("AI Assistant")
    st.caption("Powered by SupplyChainIQ CoCo Cortex Agent")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about supply chain performance..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                import json
                try:
                    req_body = json.dumps({
                        "messages": [{
                            "role": "user",
                            "content": [{"type": "text", "text": prompt}]
                        }]
                    })
                    result_raw = session.sql(
                        f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_AGENT', $${req_body}$$)"
                    ).collect()[0][0]
                    result = json.loads(result_raw)
                    response_text = ""
                    if isinstance(result, dict) and "content" in result:
                        for block in result["content"]:
                            if block.get("type") == "text":
                                response_text += block.get("text", "")
                    if not response_text:
                        response_text = "No response generated."
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

    with st.expander("Sample Questions"):
        samples = [
            "What is our overall on-time delivery percentage?",
            "Which country has the highest logistics cost rate?",
            "What are our total sales and profit?",
            "Show delivery performance by shipping mode",
            "Compare top 5 suppliers by freight cost",
        ]
        for s in samples:
            st.code(s, language=None)

st.sidebar.markdown("**Data Sources**")
st.sidebar.markdown("- DataCo: E-commerce orders (2015-2018)")
st.sidebar.markdown("- SCMS: Pharma shipments (2006-2015)")
st.sidebar.markdown("---")
st.sidebar.caption("Two-island model: DataCo and SCMS cannot be joined at row level.")
