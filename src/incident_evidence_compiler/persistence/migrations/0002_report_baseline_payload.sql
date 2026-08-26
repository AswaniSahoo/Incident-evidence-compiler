-- 0002_report_baseline_payload.sql, expose the baseline ranking (ADR 0019).
-- Additive and nullable: existing reports read back NULL, and the verification payload column
-- is unchanged, so every consumer of that payload is unaffected.

ALTER TABLE reports ADD COLUMN baseline_payload text;
