import streamlit as st
from snowflake.snowpark.context import get_active_session
from snowflake.cortex import data_agent_run
import json

session = get_active_session()

st.header("AI Assistant")
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
            try:
                result = data_agent_run(
                    agent_name="SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_AGENT",
                    user_message=prompt,
                    session=session
                )
                response_text = ""
                if isinstance(result, dict):
                    messages = result.get("messages", [])
                    for m in messages:
                        if m.get("role") == "assistant":
                            response_text += m.get("content", "")
                elif isinstance(result, str):
                    response_text = result
                else:
                    response_text = str(result)

                if not response_text:
                    response_text = "No response generated."

                st.markdown(response_text)
                st.session_state.messages.append({"role": "assistant", "content": response_text})
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
