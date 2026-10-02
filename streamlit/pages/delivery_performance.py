import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

st.header("Delivery Performance (DataCo)")

trend = session.sql("SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.MONTHLY_DELIVERY_TREND").to_pandas()
if not trend.empty:
    st.subheader("Monthly On-Time Delivery Trend")
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

st.subheader("Country Delivery Scorecard (Top 20 by Order Items)")
country = session.sql("""
    SELECT * FROM SUPPLYCHAINIQ_COCO.SEMANTIC.COUNTRY_DELIVERY_SCORECARD
    ORDER BY ORDER_ITEM_COUNT DESC LIMIT 20
""").to_pandas()
st.dataframe(country, use_container_width=True)
