-- ============================================================================
-- DIABETES MELLITUS (DM) — ANALYTICAL VIEW
-- ============================================================================
-- Creates the core analytical grain: stg_dm_patient_month
--   Grain: one row per patient per month.
--   Combines: cohort membership, FBS/A1C screening results, diagnosis events.
--   Assigns:  screening_category (worst of FBS and A1C), is_incident_case.
--
-- Prerequisites: 00_config.sql, dm_staging_views.sql
--
-- FBS Classification (handles both mg/dL and mmol/L — auto-detected by value range):
--   mmol/L range (values < 30):  normal ≤ 5.5  | elevated 5.6–6.9  | abnormal > 6.9
--   mg/dL range (values ≥ 30):   normal ≤ 99   | elevated 100–125  | abnormal > 125
--
-- A1C Classification:
--   normal < 5.7  | elevated 5.7–6.4  | abnormal > 6.4
--
-- Overall category = GREATEST(FBS_category, A1C_category)
-- ============================================================================


-- ############################################################################
-- VIEW: stg_dm_patient_month
-- ############################################################################
-- The central analytical table for Diabetes Mellitus.
-- Every downstream report reads from this single view.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_patient_month AS

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

-- Aggregate to patient-month: take the LATEST result of each marker
patient_month_labs AS (
    SELECT
        patient_key,
        year_month_key,
        MAX_BY(result_value,
            CASE WHEN result_name = 'FBS' THEN visit_date END
        )                                       AS last_fbs_value,
        MAX_BY(result_value,
            CASE WHEN result_name = 'A1C' THEN visit_date END
        )                                       AS last_a1c_value,
        BOOLOR_AGG(result_name = 'FBS')         AS had_fbs,
        BOOLOR_AGG(result_name = 'A1C')         AS had_a1c
    FROM CHI_REPORTING.stg_dm_labs
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
        bc.is_dm_prevalent,
        bc.first_any_dm_date,
        bc.first_e11_date,

        -- Pre-existing DM diagnosis: was ANY DM diagnosed BEFORE this month?
        CASE WHEN bc.first_any_dm_date IS NOT NULL
              AND bc.first_any_dm_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_any_dm_before_month,

        -- E11 specifically before this month
        CASE WHEN bc.first_e11_date IS NOT NULL
              AND bc.first_e11_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_e11_before_month,

        -- At-risk at month start
        CASE WHEN NOT has_any_dm_before_month THEN TRUE ELSE FALSE
        END                                     AS is_at_risk_start

    FROM CHI_REPORTING.stg_dm_cohort bc
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

    -- Lab data
    COALESCE(pml.had_fbs, FALSE)                AS had_fbs,
    COALESCE(pml.had_a1c, FALSE)                AS had_a1c,
    pml.last_fbs_value,
    pml.last_a1c_value,

    -- Screened = had FBS OR A1C this month while at-risk
    CASE WHEN pms.is_at_risk_start
          AND (COALESCE(pml.had_fbs, FALSE) OR COALESCE(pml.had_a1c, FALSE))
         THEN TRUE ELSE FALSE
    END                                         AS is_screened,

    -- FBS category (handles both mg/dL and mmol/L — auto-detected by value range)
    CASE
        WHEN pml.last_fbs_value IS NULL THEN NULL
        -- mmol/L range: values < 30 are in mmol/L
        WHEN pml.last_fbs_value < 30 THEN
            CASE
                WHEN pml.last_fbs_value <= 5.5 THEN 'normal'
                WHEN pml.last_fbs_value <= 6.9 THEN 'elevated'
                ELSE                                  'abnormal'
            END
        -- mg/dL range: values ≥ 30
        ELSE
            CASE
                WHEN pml.last_fbs_value <= 99  THEN 'normal'
                WHEN pml.last_fbs_value <= 125 THEN 'elevated'
                ELSE                                'abnormal'
            END
    END                                         AS fbs_category,

    -- A1C category
    CASE
        WHEN pml.last_a1c_value IS NULL THEN NULL
        WHEN pml.last_a1c_value < 5.7  THEN 'normal'
        WHEN pml.last_a1c_value <= 6.4 THEN 'elevated'
        ELSE                                 'abnormal'
    END                                         AS a1c_category,

    -- Overall screening category: GREATEST (worst) of FBS and A1C
    -- Uses numeric encoding: normal=1, elevated=2, abnormal=3
    CASE GREATEST(
        COALESCE(CASE
            WHEN a1c_category IS NULL THEN 0
            WHEN a1c_category = 'normal' THEN 1
            WHEN a1c_category = 'elevated' THEN 2
            ELSE 3
        END, 0),
        COALESCE(CASE
            WHEN fbs_category IS NULL THEN 0
            WHEN fbs_category = 'normal' THEN 1
            WHEN fbs_category = 'elevated' THEN 2
            ELSE 3
        END, 0)
    )
    WHEN 3 THEN 'abnormal'
    WHEN 2 THEN 'elevated'
    WHEN 1 THEN 'normal'
    END                                         AS screening_category,

    -- INCIDENCE: first-ever E11 this month while at-risk
    CASE WHEN pms.first_e11_date IS NOT NULL
          AND pms.first_e11_date >= TO_DATE(
                  pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
              )
          AND pms.first_e11_date < ADD_MONTHS(
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
LEFT JOIN patient_month_labs pml
    ON  pms.patient_key    = pml.patient_key
    AND pms.year_month_key = pml.year_month_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_dm_patient_month
-- WHERE patient_key = 'P01'
-- ORDER BY year_month_key;
-- ============================================================================
