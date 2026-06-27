-- ============================================================================
-- OBESITY (OB) — ANALYTICAL VIEW
-- ============================================================================
-- Creates the core analytical grain: stg_ob_patient_month
--   Grain: one row per patient per month.
--   Combines: cohort membership, BMI screening results, diagnosis events.
--   Assigns:  screening_category (WHO BMI thresholds), is_incident_case flag.
--
-- Prerequisites: 00_config.sql, ob_staging_views.sql
--
-- BMI Classification (WHO thresholds mapped to standard categories):
--   underweight < 18.5
--   normal       18.5–24.9
--   elevated     25.0–29.9  (overweight)
--   abnormal     ≥ 30.0      (obese)
-- ============================================================================


-- ############################################################################
-- VIEW: stg_ob_patient_month
-- ############################################################################
-- The central analytical table for Obesity.
-- Every downstream report reads from this single view.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_patient_month AS

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

patient_month_bmi AS (
    SELECT
        patient_key,
        year_month_key,
        MAX_BY(result_value, visit_date)        AS last_bmi_value,
        BOOLOR_AGG(TRUE)                        AS had_bmi
    FROM CHI_REPORTING.stg_ob_labs
    GROUP BY patient_key, year_month_key
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
        bc.is_ob_prevalent,
        bc.first_any_ob_date,
        bc.first_e66_date,

        -- Pre-existing Obesity diagnosis: was E66 diagnosed BEFORE this month?
        CASE WHEN bc.first_any_ob_date IS NOT NULL
              AND bc.first_any_ob_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_ob_before_month,

        -- At-risk at month start
        CASE WHEN NOT has_ob_before_month THEN TRUE ELSE FALSE
        END                                     AS is_at_risk_start

    FROM CHI_REPORTING.stg_ob_cohort bc
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

    -- Visit flag (any healthcare encounter this month)
    CASE WHEN pv.patient_key IS NOT NULL THEN TRUE ELSE FALSE
    END                                         AS had_visit,

    -- BMI data
    COALESCE(bmi.had_bmi, FALSE)                AS had_bmi,
    bmi.last_bmi_value,

    -- Screened = had BMI this month while in at-risk pool
    CASE WHEN pms.is_at_risk_start
          AND COALESCE(bmi.had_bmi, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_screened,

    -- BMI Classification (WHO thresholds → standard categories)
    CASE
        WHEN bmi.last_bmi_value IS NULL THEN NULL
        WHEN bmi.last_bmi_value < 18.5 THEN 'underweight'
        WHEN bmi.last_bmi_value <= 24.9 THEN 'normal'
        WHEN bmi.last_bmi_value <= 29.9 THEN 'elevated'    -- overweight → elevated
        ELSE 'abnormal'                                     -- obese → abnormal
    END                                         AS screening_category,

    -- INCIDENCE: first-ever E66 this month while at-risk
    CASE WHEN pms.first_e66_date IS NOT NULL
          AND pms.first_e66_date >= TO_DATE(
                  pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
              )
          AND pms.first_e66_date < ADD_MONTHS(
                  TO_DATE(
                      pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  ), 1
              )
          AND pms.is_at_risk_start = TRUE
         THEN TRUE ELSE FALSE
    END                                         AS is_incident_case

FROM patient_months_spine pms
LEFT JOIN patient_visits pv
    ON  pms.patient_key   = pv.patient_key
    AND pms.year_month_key = pv.year_month_key
LEFT JOIN patient_month_bmi bmi
    ON  pms.patient_key    = bmi.patient_key
    AND pms.year_month_key = bmi.year_month_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_ob_patient_month
-- WHERE patient_key = 'P01'
-- ORDER BY year_month_key;
-- ============================================================================
