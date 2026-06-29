-- ============================================================================
-- PREDIABETES (PREDIAB) — STAGING VIEWS
-- ============================================================================
-- Creates 2 staging views that extract and prepare source data:
--   1. stg_prediab_cohort       — patient × year grain (demographics + 6 risk-factor flags)
--   2. stg_prediab_diagnosis    — patient × diagnosis grain (ICD-10 R73.03 records only)
--
-- NO stg_prediab_labs — prediabetes has no lab of its own. The BMI ≥ 25 risk
-- factor is computed inline in stg_prediab_cohort from OBSERVATIONS.
--
-- Prerequisites:
--   1. Run 00_config.sql first (creates CHI_REPORTING.chi_config)
--   2. Run Diabetes/dm_staging_views.sql (for has_gdm)
--   3. Run HTN/htn_staging_views.sql   (for has_any_htn_diagnosis)
--   4. Run DLP/dlp_staging_views.sql   (for has_any_dlp_diagnosis)
--
-- Data sources:
--   NMR.LEANHIS.PATIENTS
--   NMR.LEANHIS.PATIENTVISITS
--   NMR.LEANHIS.OBSERVATIONS / OBSERVATIONS_OBSERVATIONVALUES
--   NMR.LEANHIS.DIAGNOSIS_CODES  [PLACEHOLDER]
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_prediab_cohort
-- ############################################################################
-- Grain: one row per patient per report year.
-- Identifies every eligible patient and joins R73.03 diagnosis history plus
-- 6 risk-factor flags (BMI ≥ 25, HTN dx, DLP dx, family-history PLACEHOLDER,
-- GDM history, PCOS via E28.2).
--
-- IMPORTANT — at-risk vs prevalent semantics INVERTED vs DM cohort:
--   • is_in_at_risk (DM cohort)        = eligible AND no DM dx  (INCLUDES R73)
--   • is_in_at_risk_prediab (THIS view) = eligible AND no R73 dx (EXCLUDES R73)
--   • is_prediab_prevalent (THIS view)  = eligible AND has R73 dx
--
-- Module-1 reports derived from this view (see prediab_report_views.sql):
--   • Report 7: Prediabetes Incidence (Monthly)        — uses is_in_at_risk_prediab
--   • Report 8: High-Risk Prediabetes Prevalence (Ann.)— uses is_prediab_prevalent
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_cohort AS

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

-- Prediabetes diagnosis summary — R73.03 ONLY (the user's locked decision)
prediab_diagnosis_summary AS (
    SELECT
        PATIENTUID                              AS patient_key,
        MIN(DIAGNOSIS_DATE)                     AS first_r73_date,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'R73.03')
                                                AS has_r73
    FROM NMR.LEANHIS.DIAGNOSIS_CODES                                -- [PLACEHOLDER]
    WHERE TRIM(UPPER(ICD10_CODE)) = 'R73.03'                        -- [PLACEHOLDER]
    GROUP BY PATIENTUID
),

-- Risk factor 1: latest BMI in 2025 ≥ 25
-- arg_max(value, visit_date) picks the most recent reading of the report year
bmi_latest AS (
    SELECT
        o.PATIENTUID                            AS patient_key,
        MAX_BY(
            TRY_TO_DECIMAL(
                REGEXP_SUBSTR(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?'),
                10, 2
            ),
            pv.STARTDATE
        )                                       AS latest_bmi_value
    FROM NMR.LEANHIS.OBSERVATIONS o
    JOIN NMR.LEANHIS.OBSERVATIONS_OBSERVATIONVALUES ov
            ON o._ID = ov.OBSERVATIONS_ID
    JOIN NMR.LEANHIS.PATIENTVISITS pv
            ON o.PATIENTVISITUID = pv._ID
    WHERE pv.STARTDATE >= (SELECT report_start  FROM CHI_REPORTING.chi_config)
      AND pv.STARTDATE <  (SELECT report_end    FROM CHI_REPORTING.chi_config)
      AND ov.NAME = 'BMI'
      AND TRY_TO_DECIMAL(REGEXP_SUBSTR(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?'), 10, 2)
            BETWEEN 10 AND 80                   -- exclude implausible outliers
    GROUP BY o.PATIENTUID
),

-- Risk factor 2: HTN diagnosis (re-uses existing HTN cohort view)
htn_flag AS (
    SELECT patient_key, has_any_htn_diagnosis
    FROM CHI_REPORTING.stg_htn_cohort
),

-- Risk factor 3: DLP diagnosis (re-uses existing DLP cohort view)
dlp_flag AS (
    SELECT patient_key, has_any_dlp_diagnosis
    FROM CHI_REPORTING.stg_dlp_cohort
),

-- Risk factor 4: First-degree family history of diabetes — PLACEHOLDER
-- TODO: When a structured family-history source becomes available (e.g.
--       FAMILY_HISTORY table with code Z83.3), replace this CTE with a
--       real LEFT JOIN. For now, hardcoded FALSE so the SQL is structured
--       and the flag can be flipped on once data exists.
family_history_flag AS (
    SELECT DISTINCT patient_key, FALSE AS has_family_history_diabetes
    FROM CHI_REPORTING.stg_htn_cohort        -- reuses the same patient universe
),

-- Risk factor 5: gestational diabetes history (re-uses DM cohort view)
gdm_flag AS (
    SELECT patient_key, has_gdm
    FROM CHI_REPORTING.stg_dm_cohort
),

-- Risk factor 6: PCOS / PMOS proxy via E28.2
pcos_dx AS (
    SELECT
        PATIENTUID                              AS patient_key,
        BOOLOR_AGG(TRIM(UPPER(ICD10_CODE)) = 'E28.2')
                                                AS has_pcos
    FROM NMR.LEANHIS.DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E28.2'
    GROUP BY PATIENTUID
),

phc_assignment AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS.PHC_ASSIGNMENT
)

SELECT
    patient_key,
    gender,
    age_at_jan1,
    is_in_total_population,
    health_cluster,

    -- Prediabetes diagnosis history
    first_r73_date,
    has_prediabetes,

    -- 6 risk-factor flags (each boolean)
    has_bmi_ge_25,
    has_htn_dx,
    has_dlp_dx,
    has_family_history_diabetes,
    has_gdm_history,
    has_pcos,

    -- Aggregated risk-factor count (0..6) and high-risk flag
    risk_factor_count,
    CASE WHEN risk_factor_count >= 2 THEN TRUE ELSE FALSE END
                                                AS is_high_risk_prediab,

    -- Cohort membership flags
    CASE WHEN is_in_total_population
          AND COALESCE(has_prediabetes, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_prediab_prevalent,
    CASE WHEN is_in_total_population
          AND NOT COALESCE(has_prediabetes, FALSE)
         THEN TRUE ELSE FALSE
    END                                         AS is_in_at_risk_prediab
FROM (
    SELECT
        tp.patient_key,
        tp.gender,
        tp.age_at_jan1,
        tp.is_in_total_population,
        COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
        pdx.first_r73_date,
        COALESCE(pdx.has_r73, FALSE)                AS has_prediabetes,
        COALESCE(bmi.latest_bmi_value >= 25.0, FALSE)
                                                    AS has_bmi_ge_25,
        COALESCE(htn.has_any_htn_diagnosis, FALSE)  AS has_htn_dx,
        COALESCE(dlp.has_any_dlp_diagnosis, FALSE)  AS has_dlp_dx,
        COALESCE(fh.has_family_history_diabetes, FALSE)
                                                    AS has_family_history_diabetes,
        COALESCE(gdm.has_gdm, FALSE)                AS has_gdm_history,
        COALESCE(pcos.has_pcos, FALSE)              AS has_pcos,
        (CASE WHEN bmi.latest_bmi_value >= 25.0            THEN 1 ELSE 0 END
       + CASE WHEN COALESCE(htn.has_any_htn_diagnosis, FALSE)  THEN 1 ELSE 0 END
       + CASE WHEN COALESCE(dlp.has_any_dlp_diagnosis, FALSE)  THEN 1 ELSE 0 END
       + CASE WHEN COALESCE(fh.has_family_history_diabetes, FALSE) THEN 1 ELSE 0 END
       + CASE WHEN COALESCE(gdm.has_gdm, FALSE)              THEN 1 ELSE 0 END
       + CASE WHEN COALESCE(pcos.has_pcos, FALSE)            THEN 1 ELSE 0 END
        )                                           AS risk_factor_count
    FROM total_population tp
    LEFT JOIN phc_assignment        phc  USING (patient_key)
    LEFT JOIN prediab_diagnosis_summary pdx USING (patient_key)
    LEFT JOIN bmi_latest            bmi  USING (patient_key)
    LEFT JOIN htn_flag              htn  USING (patient_key)
    LEFT JOIN dlp_flag              dlp  USING (patient_key)
    LEFT JOIN family_history_flag   fh   USING (patient_key)
    LEFT JOIN gdm_flag              gdm  USING (patient_key)
    LEFT JOIN pcos_dx               pcos USING (patient_key)
) base;


-- ############################################################################
-- VIEW 2: stg_prediab_diagnosis
-- ############################################################################
-- Grain: one row per R73.03 diagnosis record.
-- Extracts all prediabetes ICD-10 codes (R73.03 only) with first-occurrence rank.
-- Useful for debugging: see exactly when each patient was diagnosed.
-- ############################################################################

CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_diagnosis AS

SELECT
    PATIENTUID                              AS patient_key,
    DIAGNOSIS_DATE                          AS diagnosis_date,
    ICD10_CODE                              AS icd10_code,
    DIAGNOSIS_DESCRIPTION                   AS icd10_description,
    ROW_NUMBER() OVER (
        PARTITION BY PATIENTUID, ICD10_CODE
        ORDER BY DIAGNOSIS_DATE
    )                                       AS diagnosis_rank
FROM NMR.LEANHIS.DIAGNOSIS_CODES                -- [PLACEHOLDER]
WHERE TRIM(UPPER(ICD10_CODE)) = 'R73.03';       -- [PLACEHOLDER]