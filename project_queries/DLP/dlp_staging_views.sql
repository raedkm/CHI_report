-- ============================================================================
-- DYSLIPIDEMIA (DLP) — STAGING VIEWS
-- ============================================================================
-- Creates 3 staging views that extract and prepare source data:
--   1. stg_dlp_cohort       — patient × year grain (demographics + diagnosis flags)
--   2. stg_dlp_diagnosis    — patient × diagnosis grain (ICD-10 E78 records)
--   3. stg_dlp_labs         — patient × visit grain (HDL/LDL/CHOL/TRIG, LABS+OBS)
--
-- Prerequisites: Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--
-- Data sources (LABRESULTS + OBSERVATIONS — same pattern as DM):
--   NMR.LEANHIS.PATIENTS
--   NMR.LEANHIS.PATIENTVISITS
--   NMR.LEANHIS.LABRESULTS / LABRESULTS_RESULTVALUES
--   NMR.LEANHIS.OBSERVATIONS / OBSERVATIONS_OBSERVATIONVALUES
--   NMR.LEANHIS.DIAGNOSIS_CODES  [PLACEHOLDER]
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_dlp_cohort
-- ############################################################################
-- Grain: one row per patient per report year.
-- Identifies every eligible patient and joins DLP diagnosis history to assign
-- cohort membership: is_in_total_population, is_in_at_risk, is_dlp_prevalent.
-- Also provides the first-ever E78 diagnosis date (for incidence detection).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_cohort AS

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

dlp_diagnosis_summary AS (
    SELECT
        PATIENTUID                              AS patient_key,
        MIN(DIAGNOSIS_DATE)                     AS first_e78_date,
        MIN(DIAGNOSIS_DATE)                     AS first_any_dlp_date,
        TRUE                                    AS has_e78
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E78'                           -- [PLACEHOLDER]
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
    dx.first_any_dlp_date,
    dx.first_e78_date,
    COALESCE(dx.has_e78, FALSE)                 AS has_e78,
    COALESCE(dx.has_e78, FALSE)                 AS has_any_dlp_diagnosis,
    CASE WHEN tp.is_in_total_population
          AND NOT COALESCE(dx.has_e78, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_in_at_risk,
    CASE WHEN tp.is_in_total_population
          AND COALESCE(dx.has_e78, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_dlp_prevalent
FROM total_population tp
LEFT JOIN phc_assignment phc USING (patient_key)
LEFT JOIN dlp_diagnosis_summary dx USING (patient_key);


-- ############################################################################
-- VIEW 2: stg_dlp_diagnosis
-- ############################################################################
-- Grain: one row per diagnosis record.
-- Extracts all E78 (Dyslipidemia) ICD-10 codes with first-occurrence rank.
-- Useful for debugging: see exactly when each patient was diagnosed.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_diagnosis AS

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
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E78'                              -- [PLACEHOLDER]
) raw;


-- ############################################################################
-- VIEW 3: stg_dlp_labs
-- ############################################################################
-- Grain: one row per lipid result per patient per visit.
-- Extracts 4 lipid markers from both LABRESULTS and OBSERVATIONS (UNION ALL).
-- Standardizes result names: HDL, LDL, CHOL, TRIG.
-- NOTE: Gender-specific HDL classification happens downstream in stg_dlp_patient_month.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_labs AS

-- Step 1 — Lipid panel from LABRESULTS
SELECT
    lr.PATIENTUID                               AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    CASE
        WHEN lrv.NAME IN (
            'Cholesterol.in HDL',
            'Cholesterol in HDL'
        ) THEN 'HDL'
        WHEN lrv.NAME IN (
            'Cholesterol.in LDL',
            'Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay'
        ) THEN 'LDL'
        WHEN lrv.NAME = 'Cholesterol in Serum or Plasma' THEN 'CHOL'
        WHEN lrv.NAME = 'Triglyceride' THEN 'TRIG'
    END                                         AS result_name,
    NULLIF(
        TRY_TO_DECIMAL(
            REGEXP_SUBSTR(lrv.RESULTVALUE, '[0-9]+(\\.[0-9]+)?'),
            10, 2
        ), 0
    )                                           AS result_value,
    'LABRESULTS'                                AS source_table
FROM NMR.LEANHIS.LABRESULTS lr
JOIN NMR.LEANHIS.LABRESULTS_RESULTVALUES lrv
    ON lr._ID = lrv.LABRESULTS_ID
JOIN NMR.LEANHIS.PATIENTVISITS pv
    ON lr.PATIENTVISITUID = pv._ID
CROSS JOIN CHI_REPORTING.chi_config cfg
WHERE pv.STARTDATE >= cfg.report_start
  AND pv.STARTDATE <  cfg.report_end
  AND lrv.NAME IN (
          'Cholesterol.in HDL',
          'Cholesterol in HDL',
          'Cholesterol.in LDL',
          'Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay',
          'Cholesterol in Serum or Plasma',
          'Triglyceride'
      )

UNION ALL

-- Step 2 — HDL and Triglyceride from OBSERVATIONS
SELECT
    o.PATIENTUID                                AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    CASE
        WHEN ov.NAME IN (
            'Cholesterol.in HDL',
            'Cholesterol in HDL'
        ) THEN 'HDL'
        WHEN ov.NAME = 'Triglyceride' THEN 'TRIG'
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
  AND ov.NAME IN (
          'Cholesterol.in HDL',
          'Cholesterol in HDL',
          'Triglyceride'
      );


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT COUNT(*) AS cohort_rows FROM CHI_REPORTING.stg_dlp_cohort;
-- SELECT COUNT(*) AS diagnosis_rows FROM CHI_REPORTING.stg_dlp_diagnosis;
-- SELECT result_name, COUNT(*) FROM CHI_REPORTING.stg_dlp_labs GROUP BY 1;
-- ============================================================================
