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

-- ============================================================================
-- CONTROL THRESHOLDS — Configurable disease control classification
-- ============================================================================
-- Each row defines one range for one marker at one control level.
-- Classification: patient's most recent value is matched against ranges.
-- For conditions with multiple markers (HTN, DLP), GREATEST(level_order)
-- across all markers determines the overall control level.
-- To change thresholds, UPDATE or INSERT rows — no SQL code changes needed.
-- ============================================================================

CREATE TABLE IF NOT EXISTS CHI_REPORTING.chi_control_thresholds (
    condition       VARCHAR,          -- 'dm', 'htn', 'dlp', 'ob'
    marker          VARCHAR,          -- 'a1c', 'sys', 'dia', 'hdl', 'ldl', 'chol', 'trig', 'bmi'
    gender          VARCHAR,          -- 'Male', 'Female', 'All'
    control_level   VARCHAR,          -- 'controlled', 'uncontrolled'
    min_value       DECIMAL(10,2),    -- inclusive lower bound (NULL = unbounded)
    max_value       DECIMAL(10,2),    -- exclusive upper bound (NULL = unbounded)
    level_order     INTEGER,          -- 0=best, 3=worst
    label           VARCHAR           -- DISPLAY label with threshold range
);

DELETE FROM CHI_REPORTING.chi_control_thresholds;

-- DM — A1C only (ADA Standards of Care)
INSERT INTO CHI_REPORTING.chi_control_thresholds VALUES
('dm', 'a1c', 'All', 'controlled',     0.0,  7.0,  0, 'Controlled (A1C < 7.0%)'),
('dm', 'a1c', 'All', 'uncontrolled',   7.0,  8.0,  1, 'Uncontrolled (A1C 7.0–7.9%)'),
('dm', 'a1c', 'All', 'uncontrolled',   8.0,  9.0,  2, 'Uncontrolled (A1C 8.0–8.9%)'),
('dm', 'a1c', 'All', 'uncontrolled',   9.0,  NULL, 3, 'Uncontrolled (A1C ≥ 9.0%)');

-- HTN — SYS + DIA combined (ACC/AHA 2017, adapted for treated patients)
INSERT INTO CHI_REPORTING.chi_control_thresholds VALUES
('htn', 'sys', 'All', 'controlled',     0.0, 130.0, 0, 'Controlled (SYS < 130)'),
('htn', 'sys', 'All', 'uncontrolled', 130.0, 140.0, 1, 'Uncontrolled (SYS 130–139)'),
('htn', 'sys', 'All', 'uncontrolled', 140.0, 160.0, 2, 'Uncontrolled (SYS 140–159)'),
('htn', 'sys', 'All', 'uncontrolled', 160.0,  NULL, 3, 'Uncontrolled (SYS ≥ 160)'),
('htn', 'dia', 'All', 'controlled',     0.0,  80.0, 0, 'Controlled (DIA < 80)'),
('htn', 'dia', 'All', 'uncontrolled',  80.0,  90.0, 1, 'Uncontrolled (DIA 80–89)'),
('htn', 'dia', 'All', 'uncontrolled',  90.0, 100.0, 2, 'Uncontrolled (DIA 90–99)'),
('htn', 'dia', 'All', 'uncontrolled', 100.0,  NULL, 3, 'Uncontrolled (DIA ≥ 100)');

-- DLP — 4 markers, GREATEST of all (gender-specific HDL)
INSERT INTO CHI_REPORTING.chi_control_thresholds VALUES
('dlp', 'ldl', 'All', 'controlled',     0.0, 100.0, 0, 'Controlled (LDL < 100)'),
('dlp', 'ldl', 'All', 'uncontrolled', 100.0, 130.0, 1, 'Uncontrolled (LDL 100–129)'),
('dlp', 'ldl', 'All', 'uncontrolled', 130.0, 160.0, 2, 'Uncontrolled (LDL 130–159)'),
('dlp', 'ldl', 'All', 'uncontrolled', 160.0,  NULL, 3, 'Uncontrolled (LDL ≥ 160)'),
('dlp', 'chol', 'All', 'controlled',     0.0, 200.0, 0, 'Controlled (Chol < 200)'),
('dlp', 'chol', 'All', 'uncontrolled', 200.0, 240.0, 1, 'Uncontrolled (Chol 200–239)'),
('dlp', 'chol', 'All', 'uncontrolled', 240.0, 280.0, 2, 'Uncontrolled (Chol 240–279)'),
('dlp', 'chol', 'All', 'uncontrolled', 280.0,  NULL, 3, 'Uncontrolled (Chol ≥ 280)'),
('dlp', 'trig', 'All', 'controlled',     0.0, 150.0, 0, 'Controlled (Trig < 150)'),
('dlp', 'trig', 'All', 'uncontrolled', 150.0, 200.0, 1, 'Uncontrolled (Trig 150–199)'),
('dlp', 'trig', 'All', 'uncontrolled', 200.0, 500.0, 2, 'Uncontrolled (Trig 200–499)'),
('dlp', 'trig', 'All', 'uncontrolled', 500.0,  NULL, 3, 'Uncontrolled (Trig ≥ 500)'),
('dlp', 'hdl', 'Male',   'controlled',   40.0,  NULL, 0, 'Controlled (HDL ≥ 40)'),
('dlp', 'hdl', 'Male',   'uncontrolled',  0.0,  40.0, 1, 'Uncontrolled (HDL < 40)'),
('dlp', 'hdl', 'Female', 'controlled',   50.0,  NULL, 0, 'Controlled (HDL ≥ 50)'),
('dlp', 'hdl', 'Female', 'uncontrolled',  0.0,  50.0, 1, 'Uncontrolled (HDL < 50)');

-- OB — BMI only (WHO classification)
INSERT INTO CHI_REPORTING.chi_control_thresholds VALUES
('ob', 'bmi', 'All', 'controlled',   18.5,  25.0, 0, 'Controlled (BMI 18.5–24.9)'),
('ob', 'bmi', 'All', 'uncontrolled', 25.0,  30.0, 1, 'Uncontrolled (BMI 25.0–29.9)'),
('ob', 'bmi', 'All', 'uncontrolled', 30.0,  35.0, 2, 'Uncontrolled (BMI 30.0–34.9)'),
('ob', 'bmi', 'All', 'uncontrolled', 35.0,  NULL, 3, 'Uncontrolled (BMI ≥ 35.0)');

-- ============================================================================
-- CARE GAP CONFIG — Follow-up compliance targets
-- ============================================================================

CREATE TABLE IF NOT EXISTS CHI_REPORTING.chi_care_gap_config (
    target_quarters_completed  INTEGER,   -- minimum quarters with follow-up to be "compliant"
    report_year                INTEGER
);

DELETE FROM CHI_REPORTING.chi_care_gap_config;

INSERT INTO CHI_REPORTING.chi_care_gap_config VALUES (3, 2025);

-- Verify config tables
SELECT 'chi_control_thresholds' AS config_table, COUNT(*) AS rows
FROM CHI_REPORTING.chi_control_thresholds
UNION ALL
SELECT 'chi_care_gap_config', COUNT(*) FROM CHI_REPORTING.chi_care_gap_config;
