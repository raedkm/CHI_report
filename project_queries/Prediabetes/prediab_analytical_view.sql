-- ============================================================================
-- PREDIABETES (PREDIAB) — ANALYTICAL VIEW
-- ============================================================================
-- Creates 1 view: stg_prediab_patient_month — patient × month grain.
--
-- This is the central grain for the Prediabetes Incidence (Monthly) report.
-- The High-Risk Prevalence (Annual) report reads from stg_prediab_cohort
-- directly (no monthly granularity needed).
--
-- Carries forward from stg_prediab_cohort:
--   • All 6 risk-factor flags + risk_factor_count + is_high_risk_prediab
--   • first_r73_date, has_prediabetes, is_prediab_prevalent, is_in_at_risk_prediab
--
-- Time-varying columns computed here:
--   • is_prediab_at_risk_start    — at-risk at month start (no prior R73.03)
--   • has_r73_before_month        — R73.03 already diagnosed before this month
--   • is_prediab_incident_case    — first-ever R73.03 this month while at-risk
--   • had_visit                   — any visit this month
--
-- Prerequisites:
--   1. Run 00_config.sql                  (chi_config)
--   2. Run Diabetes/dm_staging_views.sql  (stg_dm_cohort for has_gdm)
--   3. Run HTN/htn_staging_views.sql      (stg_htn_cohort for has_htn)
--   4. Run DLP/dlp_staging_views.sql      (stg_dlp_cohort for has_dlp)
--   5. Run Prediabetes/prediab_staging_views.sql (stg_prediab_cohort)
-- ============================================================================


CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_patient_month AS

WITH patient_visits AS (
    SELECT
        PATIENTUID                              AS patient_key,
        YEAR(STARTDATE) * 100 + MONTH(STARTDATE) AS year_month_key
    FROM NMR.LEANHIS.PATIENTVISITS
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE STARTDATE >= cfg.report_start
      AND STARTDATE <  cfg.report_end
    GROUP BY PATIENTUID, year_month_key
),

patient_months_spine AS (
    SELECT
        bc.patient_key,
        m.year_month_key,
        m.report_year,
        m.report_month,
        bc.gender,
        bc.age_at_jan1,
        bc.is_in_total_population,
        bc.health_cluster,
        bc.is_prediab_prevalent,
        bc.is_in_at_risk_prediab,
        bc.is_high_risk_prediab,
        bc.risk_factor_count,
        bc.first_r73_date,
        bc.has_prediabetes,

        -- Risk-factor flags carried forward (constants per patient)
        bc.has_bmi_ge_25,
        bc.has_htn_dx,
        bc.has_dlp_dx,
        bc.has_family_history_diabetes,
        bc.has_gdm_history,
        bc.has_pcos,

        -- Was R73.03 already diagnosed BEFORE this month?
        CASE WHEN bc.first_r73_date IS NOT NULL
              AND bc.first_r73_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_r73_before_month,

        -- At-risk at month start = no R73.03 prior to this month
        CASE WHEN NOT (bc.first_r73_date IS NOT NULL
                       AND bc.first_r73_date < TO_DATE(
                               m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                           ))
             THEN TRUE ELSE FALSE
        END                                     AS is_prediab_at_risk_start

    FROM CHI_REPORTING.stg_prediab_cohort bc
    CROSS JOIN (
        SELECT
            seq                                 AS report_month,
            cfg.report_year * 100 + seq         AS year_month_key,
            cfg.report_year                     AS report_year
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
        CROSS JOIN CHI_REPORTING.chi_config cfg
    ) m
    WHERE bc.is_in_total_population = TRUE
)

SELECT
    pms.*,

    -- Visit flag
    CASE WHEN pv.patient_key IS NOT NULL THEN TRUE ELSE FALSE
    END                                         AS had_visit,

    -- INCIDENCE: first-ever R73.03 in this month while at-risk
    CASE WHEN pms.first_r73_date IS NOT NULL
          AND pms.first_r73_date >= TO_DATE(
                  pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
              )
          AND pms.first_r73_date < ADD_MONTHS(
                  TO_DATE(
                      pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  ), 1
              )
          AND pms.is_prediab_at_risk_start = TRUE
         THEN TRUE ELSE FALSE
    END                                         AS is_prediab_incident_case

FROM patient_months_spine pms
LEFT JOIN patient_visits pv
    ON  pms.patient_key   = pv.patient_key
    AND pms.year_month_key = pv.year_month_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_prediab_patient_month
-- WHERE patient_key = 'P23'
-- ORDER BY year_month_key;
-- ============================================================================