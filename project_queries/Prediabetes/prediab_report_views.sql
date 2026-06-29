-- ============================================================================
-- PREDIABETES (PREDIAB) — REPORT VIEWS
-- ============================================================================
-- Creates 2 Module-1 report views:
--   1. rpt_prediab_incidence_monthly          — Report 7
--   2. rpt_prediab_prevalence_high_risk_annual — Report 8
--
-- (No Module-2 monitoring views for prediabetes in this iteration.)
--
-- Each report emits rows with a `sort_order` column:
--   • sort_order=0 — detail rows (per cluster / per cluster × month)
--   • sort_order=1 — cluster subtotals (only for monthly reports)
--   • sort_order=2 — grand total ('-- ALL CLUSTERS --')
--
-- Prerequisites:
--   1. Run all Prediabetes staging + analytical views first
-- ============================================================================


-- ############################################################################
-- REPORT 7: rpt_prediab_incidence_monthly
-- ############################################################################
-- Reports the rate of NEW prediabetes (R73.03) diagnoses per 100,000
-- at-risk population per month, by health cluster.
--
-- Denominator: patients at-risk at start of month = no prior R73.03 diagnosis
-- Numerator:   patients who received first-ever R73.03 this month
-- Rate:        per 100,000 at-risk population
--
-- Direct mirror of rpt_dm_incidence_monthly (3-layer UNION ALL).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_incidence_monthly AS

WITH incidence_metrics AS (
    SELECT
        health_cluster,
        report_year,
        report_month,
        year_month_key,
        COUNT(DISTINCT CASE WHEN is_prediab_at_risk_start = TRUE
                        THEN patient_key END)   AS at_risk_population_start,
        COUNT(DISTINCT CASE WHEN is_prediab_incident_case = TRUE
                        THEN patient_key END)   AS incident_cases,
        ROUND(incident_cases / NULLIF(at_risk_population_start, 0) * 100000, 2)
                                                AS incidence_rate_per_100k
    FROM CHI_REPORTING.stg_prediab_patient_month
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


-- ############################################################################
-- REPORT 8: rpt_prediab_prevalence_high_risk_annual
-- ############################################################################
-- Annual report: what % of prediabetes patients (R73.03 by year-end) carry
-- ≥2 high-risk factors (BMI ≥25, HTN dx, DLP dx, family history, GDM, PCOS).
--
-- Denominator: all R73-prevalent patients at Dec 31 of report year
-- Numerator:   subset of those with is_high_risk_prediab = TRUE
-- Rate:        high-risk count / total prediab population × 100
--
-- Two-layer rows (per-cluster detail + grand total).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual AS

WITH year_end_snap AS (
    SELECT
        bc.patient_key,
        bc.health_cluster,
        cfg.report_year                         AS report_year,
        (bc.first_r73_date IS NOT NULL
         AND bc.first_r73_date < cfg.report_end)
                                                AS is_prediab_prevalent_year_end,
        bc.is_high_risk_prediab,
        bc.risk_factor_count
    FROM CHI_REPORTING.stg_prediab_cohort bc
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE bc.is_in_total_population = TRUE
)

-- Detail rows (sort_order=0): per health cluster
SELECT
    report_year                              AS year,
    health_cluster,
    COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                    THEN patient_key END)     AS total_prediab_population,
    COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                          AND is_high_risk_prediab
                    THEN patient_key END)     AS high_risk_count,
    ROUND(
        COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                              AND is_high_risk_prediab
                        THEN patient_key END)
        * 100.0
        / NULLIF(
            COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                          THEN patient_key END), 0
          ), 2
    )                                         AS high_risk_pct,
    health_cluster                            AS sort_key,
    0                                         AS sort_order
FROM year_end_snap
GROUP BY health_cluster, report_year

UNION ALL

-- Grand total (sort_order=2): all clusters combined
SELECT
    report_year                              AS year,
    '── ALL CLUSTERS ──'                    AS health_cluster,
    COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                    THEN patient_key END)     AS total_prediab_population,
    COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                          AND is_high_risk_prediab
                    THEN patient_key END)     AS high_risk_count,
    ROUND(
        COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                              AND is_high_risk_prediab
                        THEN patient_key END)
        * 100.0
        / NULLIF(
            COUNT(DISTINCT CASE WHEN is_prediab_prevalent_year_end
                          THEN patient_key END), 0
          ), 2
    )                                         AS high_risk_pct,
    '── ' || report_year || ' ALL CLUSTERS ──' AS sort_key,
    2                                         AS sort_order
FROM year_end_snap
GROUP BY report_year

ORDER BY sort_order, sort_key;