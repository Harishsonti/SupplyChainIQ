import streamlit as st
from snowflake.snowpark.context import get_active_session

session = get_active_session()

st.header("Executive Summary")

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
