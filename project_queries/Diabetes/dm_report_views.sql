-- ============================================================================
-- DIABETES MELLITUS (DM) — REPORT VIEWS
-- ============================================================================
-- Creates 3 report views from the analytical grain:
--   1. rpt_dm_screening_monthly  — Monthly screening rates by DM category
--   2. rpt_dm_prevalence_annual  — Annual E11 prevalence snapshot
--   3. rpt_dm_incidence_monthly  — Monthly new E11 case rate
--
-- All reports include per-health_cluster breakdowns, cluster subtotals, and a
-- grand total row ("── ALL CLUSTERS ──").
--
-- Prerequisites: 00_config.sql, dm_staging_views.sql, dm_analytical_view.sql
-- ============================================================================


-- ############################################################################
-- REPORT 1: SCREENING (MONTHLY)
-- ############################################################################
-- Denominator: at-risk patients at month start (no DM diagnosis before month)
-- Numerator:   at-risk patients who had FBS or A1C this month
-- Stratified:  normal / elevated (prediabetic) / abnormal (diabetic range)
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_screening_monthly AS

WITH screening_metrics AS (
    SELECT
        health_cluster,
        report_year,
        report_month,
        year_month_key,
        COUNT(DISTINCT CASE WHEN is_at_risk_start = TRUE
                        THEN patient_key END)   AS at_risk_population,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                        THEN patient_key END)   AS screened_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'normal'
                        THEN patient_key END)   AS normal_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'elevated'
                        THEN patient_key END)   AS elevated_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'abnormal'
                        THEN patient_key END)   AS abnormal_count,
        ROUND(screened_count / NULLIF(at_risk_population, 0) * 100, 4)
                                                AS screening_rate_pct,
        ROUND(abnormal_count / NULLIF(screened_count, 0) * 100, 4)
                                                AS abnormal_rate_pct
    FROM CHI_REPORTING.stg_dm_patient_month
    GROUP BY health_cluster, report_year, report_month, year_month_key
)

-- Monthly detail rows (sort_order=0)
SELECT
    report_year                              AS year,
    health_cluster,
    TO_VARCHAR(
        TO_DATE(year_month_key::VARCHAR || '01', 'YYYYMMDD'),
        'MON YYYY'
    )                                        AS period,
    at_risk_population,
    screened_count,
    normal_count,
    elevated_count,
    abnormal_count,
    screening_rate_pct,
    abnormal_rate_pct,
    year_month_key                           AS sort_key,
    0                                        AS sort_order
FROM screening_metrics

UNION ALL

-- Cluster subtotal rows (sort_order=1)
SELECT
    report_year                              AS year,
    health_cluster,
    '── ' || health_cluster || ' TOTAL ──'  AS period,
    SUM(at_risk_population)                  AS at_risk_population,
    SUM(screened_count)                      AS screened_count,
    SUM(normal_count)                        AS normal_count,
    SUM(elevated_count)                      AS elevated_count,
    SUM(abnormal_count)                      AS abnormal_count,
    ROUND(SUM(screened_count) / NULLIF(SUM(at_risk_population), 0) * 100, 4)
                                              AS screening_rate_pct,
    ROUND(SUM(abnormal_count) / NULLIF(SUM(screened_count), 0) * 100, 4)
                                              AS abnormal_rate_pct,
    99999                                    AS sort_key,
    1                                        AS sort_order
FROM screening_metrics
GROUP BY health_cluster, report_year

UNION ALL

-- Grand total row — all clusters combined (sort_order=2)
SELECT
    report_year                              AS year,
    '── ALL CLUSTERS ──'                    AS health_cluster,
    '── ' || report_year || ' ALL CLUSTERS ──' AS period,
    SUM(at_risk_population)                  AS at_risk_population,
    SUM(screened_count)                      AS screened_count,
    SUM(normal_count)                        AS normal_count,
    SUM(elevated_count)                      AS elevated_count,
    SUM(abnormal_count)                      AS abnormal_count,
    ROUND(SUM(screened_count) / NULLIF(SUM(at_risk_population), 0) * 100, 4)
                                              AS screening_rate_pct,
    ROUND(SUM(abnormal_count) / NULLIF(SUM(screened_count), 0) * 100, 4)
                                              AS abnormal_rate_pct,
    99999                                    AS sort_key,
    2                                        AS sort_order
FROM screening_metrics
GROUP BY report_year

ORDER BY health_cluster, sort_order, sort_key;


-- ############################################################################
-- REPORT 2: PREVALENCE (ANNUAL)
-- ############################################################################
-- Denominator: total eligible population at Jan 1 (age>18, National ID, alive)
-- Numerator:   all patients with ICD-10 E11 at Dec 31 of the report year
-- Sub-counts:  incident during year, pre-existing before year
-- Note:        Prevalence uses E11 specifically, not all DM types
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_prevalence_annual AS

WITH prevalence_snapshot AS (
    SELECT
        patient_key,
        first_e11_date,
        CASE WHEN first_e11_date IS NOT NULL
              AND first_e11_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                                     AS has_e11_at_year_end,
        CASE WHEN first_e11_date >= cfg.report_start
              AND first_e11_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                                     AS is_incident_this_year,
        CASE WHEN first_e11_date < cfg.report_start
             THEN TRUE ELSE FALSE
        END                                     AS is_pre_existing
    FROM CHI_REPORTING.stg_dm_cohort
    CROSS JOIN CHI_REPORTING.chi_config cfg
)

-- Per-cluster rows (sort_order=0)
SELECT
    cfg.report_year                             AS year,
    bc.health_cluster,
    COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE
                    THEN bc.patient_key END)    AS total_population,
    COUNT(DISTINCT CASE WHEN ps.has_e11_at_year_end = TRUE
                    THEN bc.patient_key END)    AS prevalent_dm_count,
    COUNT(DISTINCT CASE WHEN ps.is_incident_this_year = TRUE
                    THEN bc.patient_key END)    AS incident_during_year,
    COUNT(DISTINCT CASE WHEN ps.is_pre_existing = TRUE
                          AND ps.has_e11_at_year_end = TRUE
                    THEN bc.patient_key END)    AS pre_existing_dm_count,
    ROUND(prevalent_dm_count / NULLIF(total_population, 0) * 100, 4)
                                                AS prevalence_rate_pct,
    bc.health_cluster                           AS period_label,
    0                                           AS sort_order
FROM CHI_REPORTING.stg_dm_cohort bc
CROSS JOIN CHI_REPORTING.chi_config cfg
LEFT JOIN prevalence_snapshot ps USING (patient_key)
GROUP BY cfg.report_year, bc.health_cluster

UNION ALL

-- Grand total row — all clusters combined (sort_order=2)
SELECT
    cfg.report_year                             AS year,
    '── ALL CLUSTERS ──'                       AS health_cluster,
    COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE
                    THEN bc.patient_key END)    AS total_population,
    COUNT(DISTINCT CASE WHEN ps.has_e11_at_year_end = TRUE
                    THEN bc.patient_key END)    AS prevalent_dm_count,
    COUNT(DISTINCT CASE WHEN ps.is_incident_this_year = TRUE
                    THEN bc.patient_key END)    AS incident_during_year,
    COUNT(DISTINCT CASE WHEN ps.is_pre_existing = TRUE
                          AND ps.has_e11_at_year_end = TRUE
                    THEN bc.patient_key END)    AS pre_existing_dm_count,
    ROUND(COUNT(DISTINCT CASE WHEN ps.has_e11_at_year_end = TRUE THEN bc.patient_key END)
          / NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE THEN bc.patient_key END), 0) * 100, 4)
                                                AS prevalence_rate_pct,
    '── ' || cfg.report_year || ' ALL CLUSTERS ──' AS period_label,
    2                                           AS sort_order
FROM CHI_REPORTING.stg_dm_cohort bc
CROSS JOIN CHI_REPORTING.chi_config cfg
LEFT JOIN prevalence_snapshot ps USING (patient_key)

ORDER BY health_cluster, sort_order;


-- ############################################################################
-- REPORT 3: INCIDENCE (MONTHLY)
-- ############################################################################
-- Denominator: at-risk population at month START (no DM diagnosis before month)
-- Numerator:   patients who received first-ever E11 this month
-- Rate:        per 100,000 at-risk population
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_incidence_monthly AS

WITH incidence_metrics AS (
    SELECT
        health_cluster,
        report_year,
        report_month,
        year_month_key,
        COUNT(DISTINCT CASE WHEN is_at_risk_start = TRUE
                        THEN patient_key END)   AS at_risk_population_start,
        COUNT(DISTINCT CASE WHEN is_incident_case = TRUE
                        THEN patient_key END)   AS incident_cases,
        ROUND(incident_cases / NULLIF(at_risk_population_start, 0) * 100000, 2)
                                                AS incidence_rate_per_100k
    FROM CHI_REPORTING.stg_dm_patient_month
    GROUP BY health_cluster, report_year, report_month, year_month_key
)

-- Monthly detail rows (sort_order=0)
SELECT
    report_year                              AS year,
    health_cluster,
    TO_VARCHAR(
        TO_DATE(year_month_key::VARCHAR || '01', 'YYYYMMDD'),
        'MON YYYY'
    )                                        AS period,
    at_risk_population_start,
    incident_cases,
    incidence_rate_per_100k,
    year_month_key                           AS sort_key,
    0                                        AS sort_order
FROM incidence_metrics

UNION ALL

-- Cluster subtotal rows (sort_order=1)
-- Annual rate = total cases / January at-risk × 100,000
SELECT
    report_year                              AS year,
    health_cluster,
    '── ' || health_cluster || ' TOTAL ──'  AS period,
    NULL                                     AS at_risk_population_start,
    SUM(incident_cases)                      AS incident_cases,
    ROUND(SUM(incident_cases) / NULLIF(
        MAX(CASE WHEN report_month = 1 THEN at_risk_population_start END), 0
    ) * 100000, 2)                           AS incidence_rate_per_100k,
    99999                                    AS sort_key,
    1                                        AS sort_order
FROM incidence_metrics
GROUP BY health_cluster, report_year

UNION ALL

-- Grand total row — all clusters combined (sort_order=2)
-- Annual rate = total cases / total January at-risk × 100,000
SELECT
    report_year                              AS year,
    '── ALL CLUSTERS ──'                    AS health_cluster,
    '── ' || report_year || ' ALL CLUSTERS ──' AS period,
    NULL                                     AS at_risk_population_start,
    SUM(incident_cases)                      AS incident_cases,
    ROUND(SUM(incident_cases) / NULLIF(
        SUM(CASE WHEN report_month = 1 THEN at_risk_population_start END), 0
    ) * 100000, 2)                           AS incidence_rate_per_100k,
    99999                                    AS sort_key,
    2                                        AS sort_order
FROM incidence_metrics
GROUP BY report_year

ORDER BY health_cluster, sort_order, sort_key;


-- ============================================================================
-- FINAL OUTPUT
-- ============================================================================
-- (1) Screening Report — Monthly
-- SELECT * FROM CHI_REPORTING.rpt_dm_screening_monthly ORDER BY health_cluster, sort_order, sort_key;

-- (2) Prevalence Report — Annual
-- SELECT * FROM CHI_REPORTING.rpt_dm_prevalence_annual ORDER BY health_cluster, sort_order;

-- (3) Incidence Report — Monthly
-- SELECT * FROM CHI_REPORTING.rpt_dm_incidence_monthly ORDER BY health_cluster, sort_order, sort_key;
-- ============================================================================
