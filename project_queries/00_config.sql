-- ============================================================================
-- CHI REPORTING — CONFIGURATION
-- ============================================================================
-- Creates the reporting schema and a single-row config table that all views
-- reference via CROSS JOIN for report year/date range parameterization.
--
-- Run this ONCE before any staging/analytical/report views.
-- To change the report year, UPDATE the single row and re-run downstream views.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS CHI_REPORTING;

CREATE TABLE IF NOT EXISTS CHI_REPORTING.chi_config (
    report_year   INTEGER,
    report_start  DATE,
    report_end    DATE
);

-- Insert default configuration (change year as needed)
-- The single-row design means all downstream views get their parameters
-- via CROSS JOIN CHI_REPORTING.chi_config
DELETE FROM CHI_REPORTING.chi_config;

INSERT INTO CHI_REPORTING.chi_config (report_year, report_start, report_end)
VALUES (
    2025,
    '2025-01-01'::DATE,
    '2026-01-01'::DATE
);

-- Verify
SELECT * FROM CHI_REPORTING.chi_config;
