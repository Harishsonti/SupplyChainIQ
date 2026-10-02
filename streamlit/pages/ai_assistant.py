import streamlit as st
import json
from snowflake.snowpark.context import get_active_session
from provenance import parse_agent_response, build_provenance, render_provenance_card

session = get_active_session()

st.header("AI Assistant")
st.caption("Powered by SupplyChainIQ CoCo Cortex Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("provenance"):
            render_provenance_card(msg["provenance"])

if prompt := st.chat_input("Ask about supply chain performance..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                req_body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]})
                result_raw = session.sql(
                    f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN("
                    f"'SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_AGENT', $${req_body}$$)"
                ).collect()[0][0]

                prov_parsed = parse_agent_response(result_raw)
                response_text = prov_parsed.get("text", "")
                if not response_text:
                    response_text = "No response generated."

                prov_obj = build_provenance(prov_parsed, session)

                st.markdown(response_text)
                render_provenance_card(prov_obj)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "provenance": prov_obj,
                })
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

st.sidebar.markdown("### Sample Questions")
samples = [
    "What is our overall on-time delivery percentage?",
    "Which country has the highest logistics cost rate?",
    "What are our total sales and profit?",
    "Show delivery performance by shipping mode",
]
for s in samples:
    if st.sidebar.button(s, key=s):
        st.session_state.messages.append({"role": "user", "content": s})
        st.rerun()
