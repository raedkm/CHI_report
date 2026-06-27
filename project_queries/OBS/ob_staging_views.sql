-- ============================================================================
-- OBESITY (OB) — STAGING VIEWS
-- ============================================================================
-- Creates 3 staging views that extract and prepare source data:
--   1. stg_ob_cohort       — patient × year grain (demographics + diagnosis flags)
--   2. stg_ob_diagnosis    — patient × diagnosis grain (ICD-10 E66 records)
--   3. stg_ob_labs         — patient × visit grain (BMI readings, OBSERVATIONS only)
--
-- Prerequisites: Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--
-- Data sources (OBSERVATIONS only — no LABRESULTS for Obesity):
--   NMR.LEANHIS.PATIENTS
--   NMR.LEANHIS.PATIENTVISITS
--   NMR.LEANHIS.OBSERVATIONS / OBSERVATIONS_OBSERVATIONVALUES
--   NMR.LEANHIS.DIAGNOSIS_CODES  [PLACEHOLDER]
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_ob_cohort
-- ############################################################################
-- Grain: one row per patient per report year.
-- Identifies every eligible patient (age>18, alive, valid National ID) and
-- joins their Obesity diagnosis history to assign cohort membership flags:
--   is_in_total_population, is_in_at_risk, is_ob_prevalent
-- Also provides the first-ever E66 diagnosis date (for incidence detection).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_cohort AS

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

ob_diagnosis_summary AS (
    SELECT
        PATIENTUID                              AS patient_key,
        MIN(DIAGNOSIS_DATE)                     AS first_e66_date,
        MIN(DIAGNOSIS_DATE)                     AS first_any_ob_date,
        TRUE                                    AS has_e66
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E66'                           -- [PLACEHOLDER]
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
    dx.first_any_ob_date,
    dx.first_e66_date,
    COALESCE(dx.has_e66, FALSE)                 AS has_e66,
    COALESCE(dx.has_e66, FALSE)                 AS has_any_ob_diagnosis,
    CASE WHEN tp.is_in_total_population
          AND NOT COALESCE(dx.has_e66, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_in_at_risk,
    CASE WHEN tp.is_in_total_population
          AND COALESCE(dx.has_e66, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_ob_prevalent
FROM total_population tp
LEFT JOIN phc_assignment phc USING (patient_key)
LEFT JOIN ob_diagnosis_summary dx USING (patient_key);


-- ############################################################################
-- VIEW 2: stg_ob_diagnosis
-- ############################################################################
-- Grain: one row per diagnosis record.
-- Extracts all E66 (Obesity) ICD-10 codes with their first-occurrence rank.
-- Useful for debugging: see exactly when each patient was diagnosed.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_diagnosis AS

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
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E66'                              -- [PLACEHOLDER]
) raw;


-- ############################################################################
-- VIEW 3: stg_ob_labs
-- ############################################################################
-- Grain: one row per BMI reading per patient per visit.
-- Extracts BMI from OBSERVATIONS only (Obesity does not use LABRESULTS).
-- Filters out clinically implausible values (BMI < 10 or > 80).
-- Standardizes result name to 'BMI'.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_labs AS

SELECT
    o.PATIENTUID                                AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    'BMI'                                       AS result_name,
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
  AND ov.NAME = 'BMI'
  AND ov.RESULTVALUE IS NOT NULL
  -- Filter clinically implausible values
  AND TRY_TO_DECIMAL(
        REGEXP_SUBSTR(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?'),
        10, 2
      ) BETWEEN 10 AND 80;


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT COUNT(*) AS cohort_rows FROM CHI_REPORTING.stg_ob_cohort;
-- SELECT COUNT(*) AS diagnosis_rows FROM CHI_REPORTING.stg_ob_diagnosis;
-- SELECT COUNT(*) AS lab_rows FROM CHI_REPORTING.stg_ob_labs;
-- ============================================================================
