-- ============================================================================
-- DYSLIPIDEMIA (DLP) — ANALYTICAL VIEW
-- ============================================================================
-- Creates the core analytical grain: stg_dlp_patient_month
--   Grain: one row per patient per month.
--   Combines: cohort membership, lipid screening results, diagnosis events.
--   Assigns:  screening_category (worst of 4 lipid markers), is_incident_case.
--
-- Prerequisites: 00_config.sql, dlp_staging_views.sql
--
-- Lipid Classification (GREATEST of HDL, Triglyceride, Cholesterol, LDL):
--   HDL (Male):   normal >= 40  | abnormal < 40   (no elevated category)
--   HDL (Female): normal >= 50  | abnormal < 50
--   Triglyceride: normal < 150  | elevated 150–199 | abnormal >= 200
--   Cholesterol:  normal < 200  | elevated 200–239 | abnormal >= 240
--   LDL:          normal < 130  | elevated 130–159 | abnormal >= 160
--
--   Each marker is scored: 1=normal, 2=elevated, 3=abnormal
--   Overall category = GREATEST score across all 4 markers
-- ============================================================================


-- ############################################################################
-- VIEW: stg_dlp_patient_month
-- ############################################################################
-- The central analytical table for Dyslipidemia.
-- Every downstream report reads from this single view.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_patient_month AS

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

-- Aggregate to patient-month: take the LATEST result of each lipid marker
patient_month_lipids AS (
    SELECT
        patient_key,
        year_month_key,
        MAX_BY(result_value,
            CASE WHEN result_name = 'HDL'  THEN visit_date END
        )                                       AS last_hdl_value,
        MAX_BY(result_value,
            CASE WHEN result_name = 'LDL'  THEN visit_date END
        )                                       AS last_ldl_value,
        MAX_BY(result_value,
            CASE WHEN result_name = 'CHOL' THEN visit_date END
        )                                       AS last_chol_value,
        MAX_BY(result_value,
            CASE WHEN result_name = 'TRIG' THEN visit_date END
        )                                       AS last_trig_value,
        BOOLOR_AGG(result_name = 'HDL')         AS had_hdl,
        BOOLOR_AGG(result_name = 'LDL')         AS had_ldl,
        BOOLOR_AGG(result_name = 'CHOL')        AS had_chol,
        BOOLOR_AGG(result_name = 'TRIG')        AS had_trig
    FROM CHI_REPORTING.stg_dlp_labs
    WHERE result_value IS NOT NULL
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
        bc.is_dlp_prevalent,
        bc.first_any_dlp_date,
        bc.first_e78_date,

        -- Pre-existing DLP diagnosis: was E78 diagnosed BEFORE this month?
        CASE WHEN bc.first_any_dlp_date IS NOT NULL
              AND bc.first_any_dlp_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_dlp_before_month,

        -- At-risk at month start
        CASE WHEN NOT has_dlp_before_month THEN TRUE ELSE FALSE
        END                                     AS is_at_risk_start

    FROM CHI_REPORTING.stg_dlp_cohort bc
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

    -- Lipid data
    COALESCE(pml.had_hdl,  FALSE)               AS had_hdl,
    COALESCE(pml.had_ldl,  FALSE)               AS had_ldl,
    COALESCE(pml.had_chol, FALSE)               AS had_chol,
    COALESCE(pml.had_trig, FALSE)               AS had_trig,
    pml.last_hdl_value,
    pml.last_ldl_value,
    pml.last_chol_value,
    pml.last_trig_value,

    -- Screened = had HDL OR LDL this month while at-risk
    -- (any lipid panel component counts as screening)
    CASE WHEN pms.is_at_risk_start
          AND (COALESCE(pml.had_hdl, FALSE) OR COALESCE(pml.had_ldl, FALSE))
         THEN TRUE ELSE FALSE
    END                                         AS is_screened,

    -- Overall lipid classification: GREATEST (worst) of 4 markers
    -- Each scored: normal=1, elevated=2, abnormal=3
    -- HDL has no 'elevated' category — only normal(1) or abnormal(3)
    CASE GREATEST(
        -- HDL (gender-specific: no elevated category)
        COALESCE(CASE
            WHEN pml.last_hdl_value IS NULL THEN 0
            WHEN pms.gender = 'Male'   AND pml.last_hdl_value >= 40 THEN 1
            WHEN pms.gender = 'Female' AND pml.last_hdl_value >= 50 THEN 1
            ELSE 3
        END, 0),
        -- Triglyceride
        COALESCE(CASE
            WHEN pml.last_trig_value IS NULL THEN 0
            WHEN pml.last_trig_value < 150 THEN 1
            WHEN pml.last_trig_value <= 199 THEN 2
            ELSE 3
        END, 0),
        -- Total Cholesterol
        COALESCE(CASE
            WHEN pml.last_chol_value IS NULL THEN 0
            WHEN pml.last_chol_value < 200 THEN 1
            WHEN pml.last_chol_value <= 239 THEN 2
            ELSE 3
        END, 0),
        -- LDL
        COALESCE(CASE
            WHEN pml.last_ldl_value IS NULL THEN 0
            WHEN pml.last_ldl_value < 130 THEN 1
            WHEN pml.last_ldl_value <= 159 THEN 2
            ELSE 3
        END, 0)
    )
    WHEN 3 THEN 'abnormal'
    WHEN 2 THEN 'elevated'
    WHEN 1 THEN 'normal'
    END                                         AS screening_category,

    -- INCIDENCE: first-ever E78 this month while at-risk
    CASE WHEN pms.first_e78_date IS NOT NULL
          AND pms.first_e78_date >= TO_DATE(
                  pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
              )
          AND pms.first_e78_date < ADD_MONTHS(
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
LEFT JOIN patient_month_lipids pml
    ON  pms.patient_key    = pml.patient_key
    AND pms.year_month_key = pml.year_month_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_dlp_patient_month
-- WHERE patient_key = 'P01'
-- ORDER BY year_month_key;
-- ============================================================================
