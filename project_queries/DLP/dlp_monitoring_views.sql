-- ============================================================================
-- DYSLIPIDEMIA (DLP) — COMPLIANCE & CARE GAP VIEWS
-- ============================================================================
-- Creates 5 views for disease control monitoring and care gap tracking:
--   1. stg_dlp_control_patient      — Patient-level lipid control classification
--   2. stg_dlp_care_gap_quarterly   — Patient × quarter follow-up completion
--   3. rpt_dlp_control              — Aggregated control level report
--   4. rpt_dlp_care_gap_quarterly   — Per-quarter care gap report
--   5. rpt_dlp_care_gap_annual      — Annual care gap distribution
--
-- Control monitoring uses all 4 lipid markers (HDL, LDL, CHOL, TRIG).
-- GREATEST of all 4 marker levels determines overall control.
-- HDL has gender-specific thresholds (Male: 40, Female: 50).
-- Care gap checks whether prevalent patients had any lipid panel each quarter.
--
-- Prerequisites: 00_config.sql, dlp_staging_views.sql, dlp_analytical_view.sql
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_dlp_control_patient
-- ############################################################################
-- Grain: one row per prevalent DLP patient.
-- Gets the most recent value for each of the 4 lipid markers independently
-- (each marker's most recent non-null month may differ).
-- Classifies each marker via config thresholds, GREATEST determines overall.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_control_patient AS

WITH most_recent_lipids AS (
    SELECT
        pm.patient_key,
        pm.health_cluster,
        pm.gender,
        MAX_BY(pm.last_hdl_value,
            CASE WHEN pm.last_hdl_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END)  AS year_end_hdl,
        MAX_BY(pm.last_ldl_value,
            CASE WHEN pm.last_ldl_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END)  AS year_end_ldl,
        MAX_BY(pm.last_chol_value,
            CASE WHEN pm.last_chol_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END)  AS year_end_chol,
        MAX_BY(pm.last_trig_value,
            CASE WHEN pm.last_trig_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END)  AS year_end_trig,
        BOOLOR_AGG(pm.had_hdl)                      AS had_any_hdl,
        BOOLOR_AGG(pm.had_ldl)                      AS had_any_ldl,
        BOOLOR_AGG(pm.had_chol)                     AS had_any_chol,
        BOOLOR_AGG(pm.had_trig)                     AS had_any_trig
    FROM CHI_REPORTING.stg_dlp_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_dlp_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, pm.gender
),

-- Classify each marker independently
c_hdl AS (
    SELECT mr.*, t.level_order AS hdl_level_order, t.label AS hdl_control_label
    FROM most_recent_lipids mr
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dlp' AND t.marker = 'hdl'
        AND (t.gender = mr.gender OR t.gender = 'All')
        AND (t.min_value IS NULL OR mr.year_end_hdl >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_hdl < t.max_value)
),
c_ldl AS (
    SELECT ch.*, t.level_order AS ldl_level_order, t.label AS ldl_control_label
    FROM c_hdl ch
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dlp' AND t.marker = 'ldl' AND t.gender = 'All'
        AND (t.min_value IS NULL OR ch.year_end_ldl >= t.min_value)
        AND (t.max_value IS NULL OR ch.year_end_ldl < t.max_value)
),
c_chol AS (
    SELECT cl.*, t.level_order AS chol_level_order, t.label AS chol_control_label
    FROM c_ldl cl
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dlp' AND t.marker = 'chol' AND t.gender = 'All'
        AND (t.min_value IS NULL OR cl.year_end_chol >= t.min_value)
        AND (t.max_value IS NULL OR cl.year_end_chol < t.max_value)
),
c_trig AS (
    SELECT cc.*, t.level_order AS trig_level_order, t.label AS trig_control_label
    FROM c_chol cc
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dlp' AND t.marker = 'trig' AND t.gender = 'All'
        AND (t.min_value IS NULL OR cc.year_end_trig >= t.min_value)
        AND (t.max_value IS NULL OR cc.year_end_trig < t.max_value)
)

SELECT
    patient_key,
    health_cluster,
    gender,
    year_end_hdl, year_end_ldl, year_end_chol, year_end_trig,
    had_any_hdl OR had_any_ldl OR had_any_chol OR had_any_trig
                                                    AS had_any_lipid,
    hdl_control_label,
    COALESCE(hdl_level_order, -1)                   AS hdl_level_order,
    ldl_control_label,
    COALESCE(ldl_level_order, -1)                   AS ldl_level_order,
    chol_control_label,
    COALESCE(chol_level_order, -1)                  AS chol_level_order,
    trig_control_label,
    COALESCE(trig_level_order, -1)                  AS trig_level_order,
    GREATEST(
        COALESCE(hdl_level_order, -1),
        COALESCE(ldl_level_order, -1),
        COALESCE(chol_level_order, -1),
        COALESCE(trig_level_order, -1)
    )                                               AS overall_level_order,
    CASE GREATEST(
        COALESCE(hdl_level_order, -1),
        COALESCE(ldl_level_order, -1),
        COALESCE(chol_level_order, -1),
        COALESCE(trig_level_order, -1)
    )
        WHEN -1 THEN 'Not Monitored'
        ELSE
            -- Find which marker has the worst level and use its label
            CASE
                WHEN COALESCE(ldl_level_order, -1) >= COALESCE(hdl_level_order, -1)
                 AND COALESCE(ldl_level_order, -1) >= COALESCE(chol_level_order, -1)
                 AND COALESCE(ldl_level_order, -1) >= COALESCE(trig_level_order, -1)
                THEN ldl_control_label
                WHEN COALESCE(chol_level_order, -1) >= COALESCE(hdl_level_order, -1)
                 AND COALESCE(chol_level_order, -1) >= COALESCE(ldl_level_order, -1)
                 AND COALESCE(chol_level_order, -1) >= COALESCE(trig_level_order, -1)
                THEN chol_control_label
                WHEN COALESCE(trig_level_order, -1) >= COALESCE(hdl_level_order, -1)
                 AND COALESCE(trig_level_order, -1) >= COALESCE(ldl_level_order, -1)
                 AND COALESCE(trig_level_order, -1) >= COALESCE(chol_level_order, -1)
                THEN trig_control_label
                ELSE hdl_control_label
            END
    END                                             AS control_level
FROM c_trig;


-- ############################################################################
-- VIEW 2: stg_dlp_care_gap_quarterly
-- ############################################################################
-- A quarter is "completed" if the patient had any lipid panel component that quarter.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_care_gap_quarterly AS

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
        BOOLOR_AGG(pm.had_hdl OR pm.had_ldl OR pm.had_chol OR pm.had_trig)
                                                    AS quarter_completed
    FROM CHI_REPORTING.stg_dlp_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_dlp_prevalent = TRUE
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

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_control AS

WITH control_metrics AS (
    SELECT health_cluster, control_level, overall_level_order,
           COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_dlp_control_patient
    GROUP BY health_cluster, control_level, overall_level_order
),
prevalent_counts AS (
    SELECT health_cluster, COUNT(*) AS prevalent_total
    FROM CHI_REPORTING.stg_dlp_control_patient GROUP BY health_cluster
)
SELECT cfg.report_year AS year, cm.health_cluster, cm.control_level,
       cm.overall_level_order AS control_level_order, cm.patient_count,
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

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_care_gap_quarterly AS

WITH quarterly_metrics AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prevalent_count,
           SUM(cg.q1_completed) AS completed_count,
           COUNT(*) - SUM(cg.q1_completed) AS gap_count,
           ROUND(SUM(cg.q1_completed) * 100.0 / NULLIF(COUNT(*), 0), 2) AS completion_rate_pct
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed),
           COUNT(*) - SUM(cg.q2_completed),
           ROUND(SUM(cg.q2_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed),
           COUNT(*) - SUM(cg.q3_completed),
           ROUND(SUM(cg.q3_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed),
           COUNT(*) - SUM(cg.q4_completed),
           ROUND(SUM(cg.q4_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
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

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_care_gap_annual AS

WITH patient_summary AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= gg.target_quarters_completed AS meets_target
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg
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
-- SELECT * FROM CHI_REPORTING.stg_dlp_control_patient ORDER BY health_cluster, overall_level_order;
-- SELECT * FROM CHI_REPORTING.rpt_dlp_control ORDER BY health_cluster, sort_order, control_level_order;
-- SELECT * FROM CHI_REPORTING.rpt_dlp_care_gap_quarterly ORDER BY health_cluster, sort_order, quarter;
-- SELECT * FROM CHI_REPORTING.rpt_dlp_care_gap_annual ORDER BY health_cluster, sort_order, sort_key;
-- ============================================================================
