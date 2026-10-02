import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

st.header("Logistics & Cost (SCMS)")

trend = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_LOGISTICS_TREND").to_pandas()
if not trend.empty:
    st.subheader("Monthly Freight Cost Trend")
    st.line_chart(trend.set_index("MONTH_START")[["FREIGHT_COST_USD", "LOGISTICS_COST_RATE_PCT"]])

st.subheader("Supplier Scorecard (Top 20 by Shipment Value)")
suppliers = session.sql("""
    SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLIER_SCORECARD
    ORDER BY SHIPMENT_VALUE_USD DESC LIMIT 20
""").to_pandas()
st.dataframe(suppliers, use_container_width=True)

st.subheader("Manufacturing Site Scorecard (Top 20 by Shipment Value)")
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
