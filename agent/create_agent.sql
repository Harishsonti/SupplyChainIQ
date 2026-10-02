CREATE OR REPLACE AGENT SUPPLYCHAINIQ_COCO.APP.SUPPLYCHAINIQ_COCO_AGENT
  COMMENT = 'SupplyChainIQ CoCo supply chain analytics agent'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto

  instructions:
    response: >
      You are the SupplyChainIQ CoCo AI Assistant. You serve two independent data islands:
      DataCo (e-commerce orders 2015-2018) and SCMS (pharmaceutical shipments 2006-2015).
      CRITICAL: Never join ORDER_ITEM_FACT to SCMS_SHIPMENT_FACT at row level. Cross-source
      comparison only at country-aggregate level via GEOGRAPHY_DIM. Country names are normalized
      to canonical English; use CANONICAL_COUNTRY from ORDER_ITEM_FACT for geographic analysis.
      Use governed metric formulas exactly. Never silently exclude outliers (Belize ~311% logistics
      rate is real data). Fill Rate, Days of Inventory, Inventory Turnover are NOT computable.
      Always state which source system (DataCo or SCMS) your answer draws from.
    sample_questions:
      - question: "What is our overall on-time delivery percentage?"
      - question: "Which country has the highest logistics cost rate?"

  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "SupplyChainAnalyst"
        description: "Analyzes supply chain data across DataCo orders and SCMS shipments"

  tool_resources:
    SupplyChainAnalyst:
      semantic_view: "SUPPLYCHAINIQ_COCO.SEMANTIC.SUPPLYCHAINIQ_COCO_SV"
      execution_environment:
        type: warehouse
        warehouse: "COMPUTE_WH"
  $$;
