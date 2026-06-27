-- ============================================================================
-- DIABETES MELLITUS (DM) — STAGING VIEWS
-- ============================================================================
-- Creates 3 staging views that extract and prepare source data:
--   1. stg_dm_cohort       — patient × year grain (demographics + diagnosis flags)
--   2. stg_dm_diagnosis    — patient × diagnosis grain (ICD-10 E10-E14,O24 records)
--   3. stg_dm_labs         — patient × visit grain (FBS/A1C, LABS+OBS)
--
-- Prerequisites: Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--
-- Data sources (LABRESULTS + OBSERVATIONS):
--   NMR.LEANHIS.PATIENTS
--   NMR.LEANHIS.PATIENTVISITS
--   NMR.LEANHIS.LABRESULTS / LABRESULTS_RESULTVALUES
--   NMR.LEANHIS.OBSERVATIONS / OBSERVATIONS_OBSERVATIONVALUES
--   NMR.LEANHIS.DIAGNOSIS_CODES  [PLACEHOLDER]
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_dm_cohort
-- ############################################################################
-- Grain: one row per patient per report year.
-- Identifies every eligible patient and joins DM diagnosis history to assign
-- cohort membership: is_in_total_population, is_in_at_risk, is_dm_prevalent.
-- Also provides first-ever E11 date (for incidence) and other DM type flags.
-- NOTE: Prediabetes patients ARE included in at-risk (they can be screened
--       and can become incident E11 cases).
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_cohort AS

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

dm_diagnosis_summary AS (
    SELECT
        PATIENTUID                              AS patient_key,
        MIN(DIAGNOSIS_DATE)                     AS first_any_dm_date,
        MIN(CASE WHEN TRIM(UPPER(ICD10_CODE)) = 'E11'
                 THEN DIAGNOSIS_DATE END)       AS first_e11_date,
        MIN(CASE WHEN TRIM(UPPER(ICD10_CODE)) = 'E10'
                 THEN DIAGNOSIS_DATE END)       AS first_e10_date,
        MIN(CASE WHEN TRIM(UPPER(ICD10_CODE)) = 'O24'
                 THEN DIAGNOSIS_DATE END)       AS first_gdm_date,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'E10')
                                                AS has_type1,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'E11')
                                                AS has_e11,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) IN ('E13','E14'))
                                                AS has_other_dm,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'O24')
                                                AS has_gdm
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) IN (                               -- [PLACEHOLDER]
              'E10',   -- Type 1 DM
              'E11',   -- Type 2 DM (target condition)
              'E13',   -- Other specified DM
              'E14',   -- Unspecified DM
              'O24'    -- Gestational DM
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
    dx.first_any_dm_date,
    dx.first_e11_date,
    dx.first_e10_date,
    dx.first_gdm_date,
    COALESCE(dx.has_type1,   FALSE)             AS has_dm_type1,
    COALESCE(dx.has_e11,     FALSE)             AS has_dm_type2,
    COALESCE(dx.has_other_dm,FALSE)             AS has_dm_other,
    COALESCE(dx.has_gdm,     FALSE)             AS has_gdm,
    (COALESCE(dx.has_type1,   FALSE)
  OR COALESCE(dx.has_e11,     FALSE)
  OR COALESCE(dx.has_other_dm,FALSE)
  OR COALESCE(dx.has_gdm,     FALSE))           AS has_any_dm_diagnosis,
    -- At-risk = eligible + no DM diagnosis (prediabetes IS included)
    CASE WHEN tp.is_in_total_population
          AND NOT has_any_dm_diagnosis
         THEN TRUE ELSE FALSE
    END                                         AS is_in_at_risk,
    -- Prevalent = eligible + has any DM diagnosis
    CASE WHEN tp.is_in_total_population
          AND has_any_dm_diagnosis
         THEN TRUE ELSE FALSE
    END                                         AS is_dm_prevalent
FROM total_population tp
LEFT JOIN phc_assignment phc USING (patient_key)
LEFT JOIN dm_diagnosis_summary dx USING (patient_key);


-- ############################################################################
-- VIEW 2: stg_dm_diagnosis
-- ############################################################################
-- Grain: one row per diagnosis record.
-- Extracts all DM-related ICD-10 codes with first-occurrence rank.
-- Useful for debugging: see exactly when each patient was diagnosed.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_diagnosis AS

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
              'E10', 'E11', 'E13', 'E14', 'O24'
          )
) raw;


-- ############################################################################
-- VIEW 3: stg_dm_labs
-- ############################################################################
-- Grain: one row per lab/observation result per patient per visit.
-- Extracts FBS and A1C from both LABRESULTS and OBSERVATIONS (UNION ALL).
-- Standardizes result names: 'FBS' and 'A1C'.
-- NOTE: FBS can be in mg/dL or mmol/L — dual-unit classification happens
--       downstream in stg_dm_patient_month.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_labs AS

-- Step 1 — FBS and A1C from LABRESULTS
SELECT
    lr.PATIENTUID                               AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    CASE
        WHEN lrv.NAME IN (
            'Fasting glucose',
            'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
            'GLUCOSE FASTING'
        ) THEN 'FBS'
        WHEN lrv.NAME = 'Hemoglobin A1c.' THEN 'A1C'
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
          'Fasting glucose',
          'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
          'GLUCOSE FASTING',
          'Hemoglobin A1c.'
      )

UNION ALL

-- Step 2 — FBS and A1C from OBSERVATIONS
SELECT
    o.PATIENTUID                                AS patient_key,
    TO_DATE(pv.STARTDATE)                       AS visit_date,
    YEAR(pv.STARTDATE) * 100 + MONTH(pv.STARTDATE) AS year_month_key,
    CASE
        WHEN ov.NAME IN (
            'Fasting glucose',
            'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
            'GLUCOSE FASTING'
        ) THEN 'FBS'
        WHEN ov.NAME = 'Hemoglobin A1c.' THEN 'A1C'
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
          'Fasting glucose',
          'Hemoglobin A1c.'
      );


-- ============================================================================
-- VERIFY
-- ============================================================================
-- SELECT COUNT(*) AS cohort_rows FROM CHI_REPORTING.stg_dm_cohort;
-- SELECT COUNT(*) AS diagnosis_rows FROM CHI_REPORTING.stg_dm_diagnosis;
-- SELECT result_name, COUNT(*) FROM CHI_REPORTING.stg_dm_labs GROUP BY 1;
-- ============================================================================
