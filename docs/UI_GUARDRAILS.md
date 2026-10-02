# UI Guardrails

- Do NOT change RAW, CORE, ONTOLOGY, SEMANTIC, METRIC_REGISTRY, Cortex Agent instructions, governed formulas, or any EVALUATION/red-team/provenance/readiness records. No new backend objects.
- No new features, RAG, vector search, multi-agent, new metrics, or Phase 4.
- Never run migration commands. Never create/recreate/reset the database or schemas. Ignore any leftover "create the database and schemas" prompt.
- No external JS, CSS, fonts, icon libraries, or custom components. Native Streamlit + embedded CSS/HTML only.
- Governed values must stay identical: OTD 42.710040%, Delay 57.289960%, Avg Delay 1.618184 days, Sales $36,784,735.01, Profit $3,966,902.97, Logistics Rate 4.228220%.
- Every visible table must answer a business question. Apply LIMIT in SQL, default Top 10, long lists in collapsed expanders. Governance/readiness/variant/red-team/provenance tables are exempt from limits.
- Query live counts; never hardcode numbers that come from tables. Verify real column names before querying; do not assume columns exist.
- Deploy to @SUPPLYCHAINIQ_COCO.APP.STREAMLIT_STAGE and update the EXISTING app SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_APP only. Run the 50-test smoke suite (must be 50/50), then commit only that stage's changes with the given message.
- Work autonomously; stop only for genuine blockers. Report actual observed values only. Do only the stage requested, then STOP.
