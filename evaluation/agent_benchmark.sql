-- Agent Benchmark: 50 test questions across 5 categories
-- Categories: ENTERPRISE (10), COUNTRY (10), GOVERNANCE (10), PERSONA (7), BOUNDARY (6)
-- See SUPPLYCHAINIQ_COCO.EVALUATION.AGENT_BENCHMARK table for full definitions
-- This file documents the test IDs and intent; the INSERT is in schema_setup.sql

-- ENTERPRISE: Verify the agent returns governed metric values
-- ENT-001 through ENT-010

-- COUNTRY: Verify country-level queries work correctly, including Belize outlier
-- CTY-001 through CTY-010

-- GOVERNANCE: Verify the agent refuses unsupported cross-source joins and non-computable metrics
-- GOV-001 through GOV-010

-- PERSONA CONSISTENCY: Same metric, different phrasings, must yield identical answers
-- PER-001 through PER-007

-- BOUNDARY: Questions the agent must decline (fill rate, inventory, returns, forecasts)
-- BND-001 through BND-006
