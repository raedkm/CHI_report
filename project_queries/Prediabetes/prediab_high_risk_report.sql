-- ============================================================================
-- PREDIABETES (PREDIAB) — HIGH-RISK PATIENTS REPORT
-- ============================================================================
-- Creates 1 Module-2 report view for prediabetes:
--   1. rpt_prediab_prevalence_high_risk_annual
--
-- Reads from the GENERIC stg_high_risk_patient view (project_queries/00a_high_risk_views.sql),
-- filtering to condition = 'prediab' rows. v1 only emits output for PREDIAB
-- because that is the only condition with risk factors defined in
-- chi_high_risk_factors (see 00_config.sql).
--
-- This file lives in project_queries/Prediabetes/ because the v1 output is
-- prediabetes-specific. When other conditions add risk factors via the
-- config table, the corresponding `rpt_{cond}_prevalence_high_risk_annual`
-- views will live in their respective condition folders; this file's
-- report can be generalized into a cross-condition aggregator at that point
-- (or remain as a thin per-condition wrapper).
--
-- Prerequisites:
--   1. Run 00_config.sql first (creates CHI_REPORTING.chi_config +
--      chi_control_thresholds + chi_care_gap_config + chi_high_risk_factors)
--   2. Run Prediabetes/prediab_staging_views.sql
--   3. Run 00a_high_risk_views.sql (creates the generic stg_high_risk_patient)
-- ============================================================================


-- ############################################################################
-- REPORT: rpt_prediab_prevalence_high_risk_annual
-- ############################################################################
-- Annual Module-2 report: among prediabetes patients (R73.03 by year-end),
-- what % carry ≥2 high-risk factors (BMI ≥25, HTN dx, DLP dx, family-history
-- placeholder, GDM history, PCOS via E28.2)?
--
-- Denominator: Prediabetes-prevalent patients at year-end (R73.03 by Dec 31)
-- Numerator:   subset of those flagged is_high_risk = TRUE by stg_high_risk_patient
-- Rate:        high-risk count / total prediab population × 100
--
-- Two-layer rows (per-cluster detail + grand total). Same shape as
-- rpt_prediab_prevalence_annual; differs in numerator definition
-- (is_high_risk instead of any-prevalent).
-- ============================================================================

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual AS

WITH snap AS (
    SELECT
        hr.patient_key,
        COALESCE(pc.health_cluster, 'Unassigned')   AS health_cluster,
        hr.is_high_risk
    FROM CHI_REPORTING.stg_high_risk_patient hr
    LEFT JOIN CHI_REPORTING.stg_prediab_cohort pc
            ON pc.patient_key = hr.patient_key
    WHERE hr.condition = 'prediab'
)

-- Detail rows (sort_order=0): per health cluster
SELECT
    2025                                                  AS year,
    health_cluster,
    COUNT(*)                                              AS total_prediab_population,
    SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)         AS high_risk_count,
    ROUND(
        SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) * 100.0
        / NULLIF(COUNT(*), 0),
        2
    )                                                     AS high_risk_pct,
    health_cluster                                        AS sort_key,
    0                                                     AS sort_order
FROM snap
GROUP BY health_cluster

UNION ALL

-- Grand total row (sort_order=2): all clusters combined
SELECT
    2025                                                  AS year,
    '── ALL CLUSTERS ──'                                AS health_cluster,
    COUNT(*)                                              AS total_prediab_population,
    SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)         AS high_risk_count,
    ROUND(
        SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) * 100.0
        / NULLIF(COUNT(*), 0),
        2
    )                                                     AS high_risk_pct,
    '── 2025 ALL CLUSTERS ──'                            AS sort_key,
    2                                                     AS sort_order
FROM snap

ORDER BY sort_order, sort_key;
