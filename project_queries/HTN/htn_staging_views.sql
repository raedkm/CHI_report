-- ============================================================================
-- HYPERTENSION (HTN) — STAGING VIEWS
-- ============================================================================
-- Creates 3 staging views that extract and prepare source data:
--   1. stg_htn_cohort       — patient × year grain (demographics + diagnosis flags)
--   2. stg_htn_diagnosis    — patient × diagnosis grain (ICD-10 I10-I15 records)
--   3. stg_htn_labs         — patient × visit grain (SYS/DIA BP, OBSERVATIONS only)
--
-- Prerequisites: Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--
-- Data sources (OBSERVATIONS only — no LABRESULTS for Hypertension):
--   NMR.LEANHIS.PATIENTS
--   NMR.LEANHIS.PATIENTVISITS
--   NMR.LEANHIS.OBSERVATIONS / OBSERVATIONS_OBSERVATIONVALUES
--   NMR.LEANHIS.DIAGNOSIS_CODES  [PLACEHOLDER]
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_htn_cohort
-- ############################################################################
-- Grain: one row per patient per report year.
-- Identifies every eligible patient and joins HTN diagnosis history to assign
-- cohort membership: is_in_total_population, is_in_at_risk, is_htn_prevalent.
-- Also provides the first-ever I10 diagnosis date (for incidence detection).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_cohort AS

WITH total_population AS (
    SELECT
        p._ID                                   AS patient_key,
        p.GENDERUID                             AS gender,
        p.DATEOFBIRTH                           AS date_of_birth,
        DATEDIFF(YEAR, p.DATEOFBIRTH, cfg.report_start) AS age_at_jan1,
        CASE WHEN age_at_jan1 > 18
              AND p.NATIONALID IS NOT NULL
              AND p.NATIONALID <> ''
              AND (p.DATEOFDEATH IS NULL OR p.DATEOFDEATH >= cfg.report_start)
             THEN TRUE ELSE FALSE
        END                                     AS is_in_total_population
    FROM NMR.LEANHIS.PATIENTS p
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE p.DATEOFBIRTH <= DATEADD(YEAR, -18, cfg.report_start)
),

htn_diagnosis_summary AS (
    SELECT
        PATIENTUID                              AS patient_key,
        MIN(DIAGNOSIS_DATE)                     AS first_any_htn_date,
        MIN(CASE WHEN TRIM(UPPER(ICD10_CODE)) = 'I10'
                 THEN DIAGNOSIS_DATE END)       AS first_i10_date,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'I10')
                                                AS has_i10,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) IN ('I11','I12','I13','I15'))
                                                AS has_other_htn
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) IN (                               -- [PLACEHOLDER]
              'I10',   -- Essential hypertension
              'I11',   -- Hypertensive heart disease
              'I12',   -- Hypertensive renal disease
              'I13',   -- Hypertensive heart and renal disease
              'I15'    -- Secondary hypertension
          )
    GROUP BY PATIENTUID
),

phc_assignment AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS.PHC_ASSIGNMENT
)

SELECT
    tp.patient_key,
    tp.gender,
    tp.age_at_jan1,
    tp.is_in_total_population,
    COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
    dx.first_any_htn_date,
    dx.first_i10_date,
    COALESCE(dx.has_i10,       FALSE)           AS has_i10,
    COALESCE(dx.has_other_htn, FALSE)           AS has_other_htn,
    (COALESCE(dx.has_i10, FALSE)
  OR COALESCE(dx.has_other_htn, FALSE))         AS has_any_htn_diagnosis,
    CASE WHEN tp.is_in_total_population
          AND NOT (COALESCE(dx.has_i10, FALSE)
                OR COALESCE(dx.has_other_htn, FALSE))
         THEN TRUE ELSE FALSE
    END                                         AS is_in_at_risk,
    CASE WHEN tp.is_in_total_population
          AND (COALESCE(dx.has_i10, FALSE)
            OR COALESCE(dx.has_other_htn, FALSE))
         THEN TRUE ELSE FALSE
    END                                         AS is_htn_prevalent
FROM total_population tp
LEFT JOIN phc_assignment phc USING (patient_key)
LEFT JOIN htn_diagnosis_summary dx USING (patient_key);


-- ############################################################################
-- VIEW 2: stg_htn_diagnosis
-- ############################################################################
-- Grain: one row per diagnosis record.
-- Extracts all HTN-related ICD-10 codes (I10-I15) with first-occurrence rank.
-- Useful for debugging: see exactly when each patient was diagnosed.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_diagnosis AS

SELECT
    patient_key,
    diagnosis_date,
    icd10_code,
    icd10_description,
    ROW_NUMBER() OVER (
        PARTITION BY patient_key, icd10_code
        ORDER BY diagnosis_date
    )                                           AS diagnosis_rank
FROM (
    SELECT
        PATIENTUID                              AS patient_key,        -- [PLACEHOLDER]
        TO_DATE(DIAGNOSIS_DATE)                 AS diagnosis_date,     -- [PLACEHOLDER]
        TRIM(UPPER(ICD10_CODE))                 AS icd10_code,         -- [PLACEHOLDER]
        DIAGNOSIS_DESCRIPTION                   AS icd10_description   -- [PLACEHOLDER]
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                   -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) IN (                                  -- [PLACEHOLDER]
              'I10', 'I11', 'I12', 'I13', 'I15'
          )
) raw;


-- ############################################################################
-- VIEW 3: stg_htn_labs
-- ############################################################################
-- Grain: one row per BP reading per patient per visit.
-- Extracts Systolic BP and Diastolic BP from OBSERVATIONS only.
-- HTN does NOT use LABRESULTS.
-- Standardizes result names to 'SYS' and 'DIA'.
-- NOTE: SYS/DIA pairing per visit happens downstream in stg_htn_patient_month.
--       This view returns individual readings for maximum debugging flexibility.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_labs AS

SELECT
    o.PATIENTUID                                AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    CASE
        WHEN ov.NAME = 'Systolic BP'  THEN 'SYS'
        WHEN ov.NAME = 'Diastolic BP' THEN 'DIA'
    END                                         AS result_name,
    NULLIF(
        TRY_TO_DECIMAL(
            REGEXP_SUBSTR(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?'),
            10, 2
        ), 0
    )                                           AS result_value,
    'OBSERVATIONS'                              AS source_table
FROM NMR.LEANHIS.OBSERVATIONS o
JOIN NMR.LEANHIS.OBSERVATIONS_OBSERVATIONVALUES ov
    ON o._ID = ov.OBSERVATIONS_ID
JOIN NMR.LEANHIS.PATIENTVISITS pv
    ON o.PATIENTVISITUID = pv._ID
CROSS JOIN CHI_REPORTING.chi_config cfg
WHERE pv.STARTDATE >= cfg.report_start
  AND pv.STARTDATE <  cfg.report_end
  AND ov.NAME IN ('Systolic BP', 'Diastolic BP')
  AND ov.RESULTVALUE IS NOT NULL;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT COUNT(*) AS cohort_rows FROM CHI_REPORTING.stg_htn_cohort;
-- SELECT COUNT(*) AS diagnosis_rows FROM CHI_REPORTING.stg_htn_diagnosis;
-- SELECT result_name, COUNT(*) FROM CHI_REPORTING.stg_htn_labs GROUP BY 1;
-- ============================================================================
