-- ============================================================================
-- DIABETES MELLITUS (DM) — COMPLIANCE & CARE GAP VIEWS
-- ============================================================================
-- Creates 5 views for disease control monitoring and care gap tracking:
--   1. stg_dm_control_patient      — Patient-level A1C control classification
--   2. stg_dm_care_gap_quarterly   — Patient × quarter follow-up completion
--   3. rpt_dm_control              — Aggregated control level report
--   4. rpt_dm_care_gap_quarterly   — Per-quarter care gap report
--   5. rpt_dm_care_gap_annual      — Annual care gap distribution
--
-- Control monitoring uses A1C only (gold standard for diabetes monitoring).
-- Care gap checks whether prevalent patients had A1C testing each quarter.
--
-- Prerequisites: 00_config.sql, dm_staging_views.sql, dm_analytical_view.sql
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_dm_control_patient
-- ############################################################################
-- Grain: one row per prevalent DM patient.
-- Gets the most recent A1C value in the report year and classifies control
-- using configurable thresholds from chi_control_thresholds.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_control_patient AS

WITH most_recent_a1c AS (
    SELECT
        pm.patient_key,
        pm.health_cluster,
        pm.gender,
        MAX_BY(
            pm.last_a1c_value,
            CASE WHEN pm.last_a1c_value IS NOT NULL
                 THEN pm.year_month_key ELSE 0 END
        )                                           AS year_end_a1c,
        BOOLOR_AGG(pm.had_a1c)                      AS had_any_a1c
    FROM CHI_REPORTING.stg_dm_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_dm_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, pm.gender
),

classified AS (
    SELECT
        mr.*,
        t.level_order,
        t.label                                     AS control_level_label
    FROM most_recent_a1c mr
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dm'
        AND t.marker = 'a1c'
        AND (t.gender = 'All' OR t.gender = mr.gender)
        AND (t.min_value IS NULL OR mr.year_end_a1c >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_a1c < t.max_value)
)

SELECT
    patient_key,
    health_cluster,
    gender,
    year_end_a1c,
    had_any_a1c,
    COALESCE(control_level_label, 'Not Monitored')  AS control_level,
    COALESCE(level_order, -1)                        AS control_level_order
FROM classified;


-- ############################################################################
-- VIEW 2: stg_dm_care_gap_quarterly
-- ############################################################################
-- Grain: one row per prevalent DM patient per quarter.
-- A quarter is "completed" if the patient had ≥1 A1C test in that quarter.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_care_gap_quarterly AS

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
        BOOLOR_AGG(pm.had_a1c)                      AS quarter_completed
    FROM CHI_REPORTING.stg_dm_patient_month pm
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE pm.report_year = cfg.report_year
      AND pm.is_dm_prevalent = TRUE
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
-- Aggregated count of prevalent patients by control level, per health cluster.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_control AS

WITH control_metrics AS (
    SELECT
        health_cluster,
        control_level,
        control_level_order,
        COUNT(*)                                    AS patient_count
    FROM CHI_REPORTING.stg_dm_control_patient
    GROUP BY health_cluster, control_level, control_level_order
),

-- Prevalent count per cluster (for percentage denominator)
prevalent_counts AS (
    SELECT
        health_cluster,
        COUNT(*)                                    AS prevalent_total
    FROM CHI_REPORTING.stg_dm_control_patient
    GROUP BY health_cluster
)

-- Detail rows (sort_order=0)
SELECT
    cfg.report_year                                 AS year,
    cm.health_cluster,
    cm.control_level,
    cm.control_level_order,
    cm.patient_count,
    ROUND(cm.patient_count * 100.0 / NULLIF(pc.prevalent_total, 0), 2)
                                                    AS pct_of_prevalent,
    0                                               AS sort_order
FROM control_metrics cm
JOIN prevalent_counts pc USING (health_cluster)
CROSS JOIN CHI_REPORTING.chi_config cfg

UNION ALL

-- Cluster subtotals (sort_order=1)
SELECT
    cfg.report_year                                 AS year,
    cm.health_cluster,
    '── ' || cm.health_cluster || ' TOTAL ──'       AS control_level,
    99                                              AS control_level_order,
    SUM(cm.patient_count)                           AS patient_count,
    100.0                                           AS pct_of_prevalent,
    1                                               AS sort_order
FROM control_metrics cm
CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, cm.health_cluster

UNION ALL

-- Grand total (sort_order=2)
SELECT
    cfg.report_year                                 AS year,
    '── ALL CLUSTERS ──'                            AS health_cluster,
    '── ALL CLUSTERS ──'                            AS control_level,
    99                                              AS control_level_order,
    SUM(cm.patient_count)                           AS patient_count,
    100.0                                           AS pct_of_prevalent,
    2                                               AS sort_order
FROM control_metrics cm
CROSS JOIN CHI_REPORTING.chi_config cfg

ORDER BY health_cluster, sort_order, control_level_order;


-- ############################################################################
-- REPORT 5: CARE GAP (QUARTERLY)
-- ############################################################################
-- Per-quarter: how many prevalent patients completed follow-up vs. had a gap.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_care_gap_quarterly AS

WITH quarterly_metrics AS (
    SELECT
        cg.health_cluster,
        1 AS quarter,
        COUNT(*)                                    AS prevalent_count,
        SUM(cg.q1_completed)                        AS completed_count,
        prevalent_count - completed_count           AS gap_count,
        ROUND(completed_count * 100.0 / NULLIF(prevalent_count, 0), 2)
                                                    AS completion_rate_pct
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
    GROUP BY cg.health_cluster

    UNION ALL
    SELECT
        cg.health_cluster,
        2 AS quarter,
        COUNT(*),
        SUM(cg.q2_completed),
        COUNT(*) - SUM(cg.q2_completed),
        ROUND(SUM(cg.q2_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
    GROUP BY cg.health_cluster

    UNION ALL
    SELECT
        cg.health_cluster,
        3 AS quarter,
        COUNT(*),
        SUM(cg.q3_completed),
        COUNT(*) - SUM(cg.q3_completed),
        ROUND(SUM(cg.q3_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
    GROUP BY cg.health_cluster

    UNION ALL
    SELECT
        cg.health_cluster,
        4 AS quarter,
        COUNT(*),
        SUM(cg.q4_completed),
        COUNT(*) - SUM(cg.q4_completed),
        ROUND(SUM(cg.q4_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
    GROUP BY cg.health_cluster
)

-- Detail rows (sort_order=0)
SELECT
    cfg.report_year                                 AS year,
    qm.health_cluster,
    qm.quarter,
    qm.prevalent_count,
    qm.completed_count,
    qm.gap_count,
    qm.completion_rate_pct,
    qm.quarter                                      AS sort_key,
    0                                               AS sort_order
FROM quarterly_metrics qm
CROSS JOIN CHI_REPORTING.chi_config cfg

UNION ALL

-- Cluster subtotals (sort_order=1)
SELECT
    cfg.report_year                                 AS year,
    qm.health_cluster,
    NULL                                            AS quarter,
    MAX(qm.prevalent_count)                         AS prevalent_count,
    SUM(qm.completed_count)                         AS completed_count,
    SUM(qm.gap_count)                               AS gap_count,
    ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2)
                                                    AS completion_rate_pct,
    99                                              AS sort_key,
    1                                               AS sort_order
FROM quarterly_metrics qm
CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, qm.health_cluster

UNION ALL

-- Grand total (sort_order=2)
SELECT
    cfg.report_year                                 AS year,
    '── ALL CLUSTERS ──'                            AS health_cluster,
    NULL                                            AS quarter,
    MAX(qm.prevalent_count)                         AS prevalent_count,
    SUM(qm.completed_count)                         AS completed_count,
    SUM(qm.gap_count)                               AS gap_count,
    ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2)
                                                    AS completion_rate_pct,
    99                                              AS sort_key,
    2                                               AS sort_order
FROM quarterly_metrics qm
CROSS JOIN CHI_REPORTING.chi_config cfg

ORDER BY health_cluster, sort_order, sort_key;


-- ############################################################################
-- REPORT 6: CARE GAP (ANNUAL)
-- ############################################################################
-- Annual distribution: count of patients by number of quarters completed (0-4).
-- Includes percentage meeting the target from chi_care_gap_config.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_care_gap_annual AS

WITH patient_summary AS (
    SELECT
        cg.health_cluster,
        cg.patient_key,
        cg.quarters_completed,
        cg.quarters_completed >= gg.target_quarters_completed
                                                    AS meets_target
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
    CROSS JOIN CHI_REPORTING.chi_care_gap_config gg
    WHERE cg.report_year = gg.report_year
),

annual_metrics AS (
    SELECT
        health_cluster,
        quarters_completed,
        COUNT(*)                                    AS patient_count,
        ROUND(COUNT(*) * 100.0 / NULLIF(
            SUM(COUNT(*)) OVER (PARTITION BY health_cluster), 0), 2)
                                                    AS pct_of_prevalent
    FROM patient_summary
    GROUP BY health_cluster, quarters_completed
)

-- Detail rows (sort_order=0)
SELECT
    cfg.report_year                                 AS year,
    am.health_cluster,
    am.quarters_completed,
    am.patient_count,
    am.pct_of_prevalent,
    am.quarters_completed                           AS sort_key,
    0                                               AS sort_order
FROM annual_metrics am
CROSS JOIN CHI_REPORTING.chi_config cfg

UNION ALL

-- Cluster subtotals + meeting target (sort_order=1)
SELECT
    cfg.report_year                                 AS year,
    ps.health_cluster,
    '≥ Target'                                      AS quarters_completed,
    SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END) AS patient_count,
    ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END) * 100.0
          / NULLIF(COUNT(*), 0), 2)                  AS pct_of_prevalent,
    99                                              AS sort_key,
    1                                               AS sort_order
FROM patient_summary ps
CROSS JOIN CHI_REPORTING.chi_config cfg
GROUP BY cfg.report_year, ps.health_cluster

UNION ALL

-- Grand total (sort_order=2)
SELECT
    cfg.report_year                                 AS year,
    '── ALL CLUSTERS ──'                            AS health_cluster,
    '── ALL CLUSTERS ──'                            AS quarters_completed,
    SUM(am.patient_count)                           AS patient_count,
    100.0                                           AS pct_of_prevalent,
    100                                             AS sort_key,
    2                                               AS sort_order
FROM annual_metrics am
CROSS JOIN CHI_REPORTING.chi_config cfg

ORDER BY health_cluster, sort_order, sort_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_dm_control_patient ORDER BY health_cluster, control_level_order;
-- SELECT * FROM CHI_REPORTING.stg_dm_care_gap_quarterly ORDER BY health_cluster, quarters_completed DESC;
-- SELECT * FROM CHI_REPORTING.rpt_dm_control ORDER BY health_cluster, sort_order, control_level_order;
-- SELECT * FROM CHI_REPORTING.rpt_dm_care_gap_quarterly ORDER BY health_cluster, sort_order, quarter;
-- SELECT * FROM CHI_REPORTING.rpt_dm_care_gap_annual ORDER BY health_cluster, sort_order, sort_key;
-- ============================================================================
