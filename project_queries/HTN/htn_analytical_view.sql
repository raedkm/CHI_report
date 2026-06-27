-- ============================================================================
-- HYPERTENSION (HTN) — ANALYTICAL VIEW
-- ============================================================================
-- Creates the core analytical grain: stg_htn_patient_month
--   Grain: one row per patient per month.
--   Combines: cohort membership, BP screening results, diagnosis events.
--   Assigns:  screening_category (ACC/AHA 2017 BP thresholds), is_incident_case.
--
-- Prerequisites: 00_config.sql, htn_staging_views.sql
--
-- Key design: SYS and DIA must be paired from the SAME VISIT to classify.
--   Step 1: Pair SYS+DIA per visit (HAVING both present)
--   Step 2: Take the LATEST visit's paired values per month (MAX_BY)
--   Step 3: Classify using combined thresholds
--
-- BP Classification (ACC/AHA 2017):
--   normal:    SYS < 120 AND DIA < 80
--   elevated:  SYS 120–129 OR DIA 80–89
--   abnormal:  SYS ≥ 130 OR DIA ≥ 90
-- ============================================================================


-- ############################################################################
-- VIEW: stg_htn_patient_month
-- ############################################################################
-- The central analytical table for Hypertension.
-- Every downstream report reads from this single view.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_patient_month AS

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

-- Pair SYS and DIA from the same visit (must have BOTH to classify)
bp_per_visit AS (
    SELECT
        patient_key,
        visit_date,
        year_month_key,
        MAX(CASE WHEN result_name = 'SYS' THEN result_value END) AS sys_value,
        MAX(CASE WHEN result_name = 'DIA' THEN result_value END) AS dia_value
    FROM CHI_REPORTING.stg_htn_labs
    WHERE result_value IS NOT NULL
    GROUP BY patient_key, visit_date, year_month_key
    HAVING sys_value IS NOT NULL AND dia_value IS NOT NULL
),

-- Aggregate to patient-month: take LATEST visit's paired BP values
patient_month_bp AS (
    SELECT
        patient_key,
        year_month_key,
        MAX_BY(sys_value, visit_date)            AS last_sys_value,
        MAX_BY(dia_value, visit_date)            AS last_dia_value,
        BOOLOR_AGG(TRUE)                         AS had_bp
    FROM bp_per_visit
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
        bc.is_htn_prevalent,
        bc.first_any_htn_date,
        bc.first_i10_date,

        -- Pre-existing HTN diagnosis: was ANY HTN diagnosed BEFORE this month?
        CASE WHEN bc.first_any_htn_date IS NOT NULL
              AND bc.first_any_htn_date < TO_DATE(
                      m.year_month_key::VARCHAR || '01', 'YYYYMMDD'
                  )
             THEN TRUE ELSE FALSE
        END                                     AS has_any_htn_before_month,

        -- At-risk at month start
        CASE WHEN NOT has_any_htn_before_month THEN TRUE ELSE FALSE
        END                                     AS is_at_risk_start

    FROM CHI_REPORTING.stg_htn_cohort bc
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

    -- BP data
    COALESCE(bp.had_bp, FALSE)                  AS had_bp,
    bp.last_sys_value,
    bp.last_dia_value,

    -- Screened = had BOTH SYS AND DIA this month while at-risk
    -- Both must be present (a single reading is not enough to classify)
    CASE WHEN pms.is_at_risk_start
          AND COALESCE(bp.had_bp, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_screened,

    -- BP Classification (ACC/AHA 2017): combined SYS/DIA, worst category wins
    CASE
        WHEN bp.last_sys_value IS NULL OR bp.last_dia_value IS NULL THEN NULL
        -- Abnormal: SYS >= 130 or DIA >= 90
        WHEN bp.last_sys_value >= 130 OR bp.last_dia_value >= 90 THEN 'abnormal'
        -- Elevated: SYS 120-129 or DIA 80-89 (but not already abnormal)
        WHEN (bp.last_sys_value BETWEEN 120 AND 129)
          OR (bp.last_dia_value BETWEEN 80 AND 89) THEN 'elevated'
        -- Normal: SYS < 120 AND DIA < 80
        ELSE 'normal'
    END                                         AS screening_category,

    -- INCIDENCE: first-ever I10 this month while at-risk
    CASE WHEN pms.first_i10_date IS NOT NULL
          AND pms.first_i10_date >= TO_DATE(
                  pms.year_month_key::VARCHAR || '01', 'YYYYMMDD'
              )
          AND pms.first_i10_date < ADD_MONTHS(
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
LEFT JOIN patient_month_bp bp
    ON  pms.patient_key    = bp.patient_key
    AND pms.year_month_key = bp.year_month_key;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT * FROM CHI_REPORTING.stg_htn_patient_month
-- WHERE patient_key = 'P01'
-- ORDER BY year_month_key;
-- ============================================================================
