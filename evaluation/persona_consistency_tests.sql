-- Persona Consistency Tests
-- Each governed metric is asked in multiple phrasings
-- All phrasings for the same metric must yield the same numerical answer

-- OTD: PER-001, PER-002, PER-003 -> ~42.71%
-- Sales: PER-004, PER-005 -> ~$36.78M
-- Logistics Rate: PER-006, PER-007 -> ~4.23%

-- Evaluation procedure:
-- 1. For each PER group, run all questions against the agent
-- 2. Extract the numerical answer from each response
-- 3. All answers in the group must match within rounding tolerance
