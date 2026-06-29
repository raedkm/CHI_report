-- ============================================================================
-- PREDIABETES (PREDIAB) — REPORT VIEWS
-- ============================================================================
-- Creates 2 Module-1 report views (standard Prediabetes reports, mirror of the
-- DM/HTN/DLP/OB pattern):
--   1. rpt_prediab_prevalence_annual     — Report 2 (standard annual prevalence)
--   2. rpt_prediab_incidence_monthly     — Report 3 (standard monthly incidence)
--
-- The Prediabetes-specific HIGH-RISK PATIENTS report (formerly Report 8) has
-- been moved to the GENERIC module-2 file: 00a_high_risk_views.sql as
-- rpt_high_risk_patients_annual. It is no longer prediabetes-specific — for v1
-- only PREDIAB has risk factors defined in chi_high_risk_factors, but the
-- report is parameterized by condition and extendable to others without
-- schema changes.
--
-- Each report emits rows with a `sort_order` column:
--   • sort_order=0 — detail rows (per cluster / per cluster × month)
--   • sort_order=1 — cluster subtotals (only for monthly reports)
--   • sort_order=2 — grand total ('-- ALL CLUSTERS --')
--
-- Prerequisites:
--   1. Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--   2. Run Prediabetes/prediab_staging_views.sql
--   3. Run Prediabetes/prediab_analytical_view.sql
-- ============================================================================


-- ############################################################################
-- REPORT 3: rpt_prediab_incidence_monthly
-- ############################################################################
-- Standard Module-1 incidence report for prediabetes (R73.03).
-- Reports the rate of NEW prediabetes diagnoses per 100,000
-- at-risk population per month, by health cluster.
--
-- Denominator: patients at-risk at start of month = no prior R73.03 diagnosis
-- Numerator:   patients who received first-ever R73.03 this month
-- Rate:        per 100,000 at-risk population
--
-- Direct mirror of rpt_dm_incidence_monthly (3-layer UNION ALL).
-- See §6.3 of epidemiological_methodology.md for the methodological context
-- shared with the DM/HTN/DLP/OB incidence reports.
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
-- REPORT 2: rpt_prediab_prevalence_annual
-- ############################################################################
-- Standard Module-1 prevalence report for prediabetes (R73.03).
-- Reports the % of the eligible population diagnosed with prediabetes by year-end.
--
-- Denominator: total eligible population (is_in_total_population = TRUE) at year-end
-- Numerator:   patients with first R73.03 diagnosis before report_end
-- Rate:        prevalent / total × 100
--
-- Direct mirror of rpt_dm_prevalence_annual. Two-layer rows (per-cluster
-- detail + grand total). For prediabetes the target code is R73.03 only
-- (no broader code set like DM's E10/E11/E13/E14/O24), so the "incident during
-- year" sub-count simplifies.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_prevalence_annual AS

WITH prevalence_snapshot AS (
    SELECT
        patient_key,
        first_r73_date,
        CASE WHEN first_r73_date IS NOT NULL
              AND first_r73_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                                     AS has_r73_at_year_end,
        CASE WHEN first_r73_date >= cfg.report_start
              AND first_r73_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                                     AS is_incident_this_year,
        CASE WHEN first_r73_date < cfg.report_start
             THEN TRUE ELSE FALSE
        END                                     AS is_pre_existing
    FROM CHI_REPORTING.stg_prediab_cohort
    CROSS JOIN CHI_REPORTING.chi_config cfg
)

-- Per-cluster rows (sort_order=0)
SELECT
    cfg.report_year                             AS year,
    bc.health_cluster,
    COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE
                    THEN bc.patient_key END)    AS total_population,
    COUNT(DISTINCT CASE WHEN ps.has_r73_at_year_end = TRUE
                    THEN bc.patient_key END)    AS prevalent_prediab_count,
    COUNT(DISTINCT CASE WHEN ps.is_incident_this_year = TRUE
                    THEN bc.patient_key END)    AS incident_during_year,
    COUNT(DISTINCT CASE WHEN ps.is_pre_existing = TRUE
                          AND ps.has_r73_at_year_end = TRUE
                    THEN bc.patient_key END)    AS pre_existing_prediab_count,
    ROUND(prevalent_prediab_count / NULLIF(total_population, 0) * 100, 4)
                                                AS prevalence_rate_pct,
    bc.health_cluster                           AS period_label,
    0                                           AS sort_order
FROM CHI_REPORTING.stg_prediab_cohort bc
CROSS JOIN CHI_REPORTING.chi_config cfg
LEFT JOIN prevalence_snapshot ps USING (patient_key)
GROUP BY cfg.report_year, bc.health_cluster

UNION ALL

-- Grand total row (sort_order=2)
SELECT
    cfg.report_year                             AS year,
    '── ALL CLUSTERS ──'                       AS health_cluster,
    COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE
                    THEN bc.patient_key END)    AS total_population,
    COUNT(DISTINCT CASE WHEN ps.has_r73_at_year_end = TRUE
                    THEN bc.patient_key END)    AS prevalent_prediab_count,
    COUNT(DISTINCT CASE WHEN ps.is_incident_this_year = TRUE
                    THEN bc.patient_key END)    AS incident_during_year,
    COUNT(DISTINCT CASE WHEN ps.is_pre_existing = TRUE
                          AND ps.has_r73_at_year_end = TRUE
                    THEN bc.patient_key END)    AS pre_existing_prediab_count,
    ROUND(COUNT(DISTINCT CASE WHEN ps.has_r73_at_year_end = TRUE THEN bc.patient_key END)
          / NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population = TRUE THEN bc.patient_key END), 0) * 100, 4)
                                                AS prevalence_rate_pct,
    '── ' || cfg.report_year || ' ALL CLUSTERS ──' AS period_label,
    2                                           AS sort_order
FROM CHI_REPORTING.stg_prediab_cohort bc
CROSS JOIN CHI_REPORTING.chi_config cfg
LEFT JOIN prevalence_snapshot ps USING (patient_key)

ORDER BY health_cluster, sort_order;