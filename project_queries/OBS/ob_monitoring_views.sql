-- ============================================================================
-- OBESITY (OB) — COMPLIANCE & CARE GAP VIEWS
-- ============================================================================
-- Creates 5 views for disease control monitoring and care gap tracking:
--   1. stg_ob_control_patient       — Patient-level BMI control classification
--   2. stg_ob_care_gap_quarterly    — Patient × quarter follow-up completion
--   3. rpt_ob_control               — Aggregated control level report
--   4. rpt_ob_care_gap_quarterly    — Per-quarter care gap report
--   5. rpt_ob_care_gap_annual       — Annual care gap distribution
--
-- Control monitoring uses BMI only (WHO classification).
-- Care gap checks whether prevalent patients had BMI measurement each quarter.
--
-- Prerequisites: 00_config.sql, ob_staging_views.sql, ob_analytical_view.sql
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_ob_control_patient
-- ############################################################################
-- Grain: one row per prevalent OB patient.
-- Gets the most recent BMI value and classifies control using config thresholds.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_control_patient AS

WITH most_recent_bmi AS (
    SELECT
        pm.patient_key,
        pm.health_cluster,
        MAX_BY(
            pm.last_bmi_value,
            CASE WHEN pm.last_bmi_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END
        )                                           AS year_end_bmi,
        BOOLOR_AGG(pm.had_bmi)                      AS had_any_bmi
    FROM CHI_REPORTING.stg_ob_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_ob_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster
),

classified AS (
    SELECT
        mr.*,
        t.level_order,
        t.label                                     AS control_level_label
    FROM most_recent_bmi mr
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'ob'
        AND t.marker = 'bmi'
        AND (t.min_value IS NULL OR mr.year_end_bmi >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_bmi < t.max_value)
)

SELECT
    patient_key,
    health_cluster,
    year_end_bmi,
    had_any_bmi,
    COALESCE(control_level_label, 'Not Monitored')  AS control_level,
    COALESCE(level_order, -1)                        AS control_level_order
FROM classified;


-- ############################################################################
-- VIEW 2: stg_ob_care_gap_quarterly
-- ############################################################################
-- A quarter is "completed" if the patient had ≥1 BMI measurement in that quarter.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_care_gap_quarterly AS

WITH quarterly_followup AS (
    SELECT
        pm.patient_key,
        pm.health_cluster,
        cfg.report_year,
        CASE
            WHEN pm.report_month BETWEEN 1 AND 3  THEN 1
            WHEN pm.report_month BETWEEN 4 AND 6  THEN 2
            WHEN pm.report_month BETWEEN 7 AND 9  THEN 3
            WHEN pm.report_month BETWEEN 10 AND 12 THEN 4
        END                                         AS quarter,
        BOOLOR_AGG(pm.had_bmi)                      AS quarter_completed
    FROM CHI_REPORTING.stg_ob_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_ob_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, cfg.report_year, quarter
)

SELECT
    patient_key,
    health_cluster,
    report_year,
    SUM(CASE WHEN quarter_completed THEN 1 ELSE 0 END) AS quarters_completed,
    MAX(CASE WHEN quarter = 1 AND quarter_completed THEN 1 ELSE 0 END) AS q1_completed,
    MAX(CASE WHEN quarter = 2 AND quarter_completed THEN 1 ELSE 0 END) AS q2_completed,
    MAX(CASE WHEN quarter = 3 AND quarter_completed THEN 1 ELSE 0 END) AS q3_completed,
    MAX(CASE WHEN quarter = 4 AND quarter_completed THEN 1 ELSE 0 END) AS q4_completed
FROM quarterly_followup
GROUP BY patient_key, health_cluster, report_year;


-- ############################################################################
-- REPORT 4: CONTROL LEVELS (ANNUAL)
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_control AS

WITH control_metrics AS (
    SELECT health_cluster, control_level, control_level_order,
           COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_ob_control_patient
    GROUP BY health_cluster, control_level, control_level_order
),
prevalent_counts AS (
    SELECT health_cluster, COUNT(*) AS prevalent_total
    FROM CHI_REPORTING.stg_ob_control_patient GROUP BY health_cluster
)
SELECT cfg.report_year AS year, cm.health_cluster, cm.control_level,
       cm.control_level_order, cm.patient_count,
       ROUND(cm.patient_count * 100.0 / NULLIF(pc.prevalent_total, 0), 2) AS pct_of_prevalent,
       0 AS sort_order
FROM control_metrics cm JOIN prevalent_counts pc USING (health_cluster)
CROSS JOIN CHI_REPORTING.chi_config cfg
UNION ALL
SELECT cfg.report_year, cm.health_cluster,
       '── ' || cm.health_cluster || ' TOTAL ──', 99,
       SUM(cm.patient_count), 100.0, 1
FROM control_metrics cm CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, cm.health_cluster
UNION ALL
SELECT cfg.report_year, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', 99,
       SUM(cm.patient_count), 100.0, 2
FROM control_metrics cm CROSS JOIN CHI_REPORTING.chi_config cfg
ORDER BY health_cluster, sort_order, control_level_order;


-- ############################################################################
-- REPORT 5: CARE GAP (QUARTERLY)
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_care_gap_quarterly AS

WITH quarterly_metrics AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prevalent_count,
           SUM(cg.q1_completed) AS completed_count,
           COUNT(*) - SUM(cg.q1_completed) AS gap_count,
           ROUND(SUM(cg.q1_completed) * 100.0 / NULLIF(COUNT(*), 0), 2) AS completion_rate_pct
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed),
           COUNT(*) - SUM(cg.q2_completed),
           ROUND(SUM(cg.q2_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed),
           COUNT(*) - SUM(cg.q3_completed),
           ROUND(SUM(cg.q3_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed),
           COUNT(*) - SUM(cg.q4_completed),
           ROUND(SUM(cg.q4_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
)
SELECT cfg.report_year AS year, qm.health_cluster, qm.quarter,
       qm.prevalent_count, qm.completed_count, qm.gap_count,
       qm.completion_rate_pct, qm.quarter AS sort_key, 0 AS sort_order
FROM quarterly_metrics qm CROSS JOIN CHI_REPORTING.chi_config cfg
UNION ALL
SELECT cfg.report_year, qm.health_cluster, NULL,
       MAX(qm.prevalent_count), SUM(qm.completed_count), SUM(qm.gap_count),
       ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2),
       99, 1
FROM quarterly_metrics qm CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, qm.health_cluster
UNION ALL
SELECT cfg.report_year, '── ALL CLUSTERS ──', NULL,
       MAX(qm.prevalent_count), SUM(qm.completed_count), SUM(qm.gap_count),
       ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2),
       99, 2
FROM quarterly_metrics qm CROSS JOIN CHI_REPORTING.chi_config cfg
ORDER BY health_cluster, sort_order, sort_key;


-- ############################################################################
-- REPORT 6: CARE GAP (ANNUAL)
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_care_gap_annual AS

WITH patient_summary AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= gg.target_quarters_completed AS meets_target
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg
    CROSS JOIN CHI_REPORTING.chi_care_gap_config gg
    WHERE cg.report_year = gg.report_year
),
annual_metrics AS (
    SELECT health_cluster, quarters_completed, COUNT(*) AS patient_count,
           ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY health_cluster), 0), 2) AS pct_of_prevalent
    FROM patient_summary GROUP BY health_cluster, quarters_completed
)
SELECT cfg.report_year AS year, am.health_cluster, am.quarters_completed,
       am.patient_count, am.pct_of_prevalent, am.quarters_completed AS sort_key, 0 AS sort_order
FROM annual_metrics am CROSS JOIN CHI_REPORTING.chi_config cfg
UNION ALL
SELECT cfg.report_year, ps.health_cluster, '≥ Target',
       SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2),
       99, 1
FROM patient_summary ps CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, ps.health_cluster
UNION ALL
SELECT cfg.report_year, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──',
       SUM(am.patient_count), 100.0, 100, 2
FROM annual_metrics am CROSS JOIN CHI_REPORTING.chi_config cfg
ORDER BY health_cluster, sort_order, sort_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_ob_control_patient ORDER BY health_cluster, control_level_order;
-- SELECT * FROM CHI_REPORTING.rpt_ob_control ORDER BY health_cluster, sort_order, control_level_order;
-- SELECT * FROM CHI_REPORTING.rpt_ob_care_gap_quarterly ORDER BY health_cluster, sort_order, quarter;
-- SELECT * FROM CHI_REPORTING.rpt_ob_care_gap_annual ORDER BY health_cluster, sort_order, sort_key;
-- ============================================================================
