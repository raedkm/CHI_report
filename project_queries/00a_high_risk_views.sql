-- ============================================================================
-- HIGH-RISK PATIENTS (GENERIC) — STAGING VIEW
-- ============================================================================
-- Creates 1 generic staging view:
--   1. stg_high_risk_patient — patient × condition, with risk_factor_count
--      and is_high_risk flags driven by chi_high_risk_factors.
--
-- The per-condition report views (rpt_{cond}_prevalence_high_risk_annual)
-- live in each condition's own folder (e.g. Prediabetes/prediab_high_risk_report.sql).
-- For v1 only Prediabetes has factors defined, so only the Prediabetes
-- report is created. When other conditions add factors via the config
-- table, a corresponding rpt_{cond}_prevalence_high_risk_annual should be
-- added to the condition's folder.
--
-- Prerequisites:
--   1. Run 00_config.sql first (creates CHI_REPORTING.chi_config + config tables,
--      including chi_high_risk_factors)
--   2. Run all per-condition staging views (so stg_*_cohort views exist for
--      the risk-factor JOINs)
--   3. Run Prediabetes/prediab_staging_views.sql so the 6 PREDIAB risk-factor
--      flag columns exist on stg_prediab_cohort
-- ============================================================================


-- ############################################################################
-- VIEW: stg_high_risk_patient
-- ############################################################################
-- Grain: one row per (patient, condition) per report year, for all conditions
--        that have ≥1 risk factor defined in chi_high_risk_factors.
--
-- For each (patient, condition, factor) row, evaluates has_factor = TRUE/FALSE
-- by reading the source_view column from the config and checking source_column.
--
-- Output columns:
--   patient_key              — patient identifier
--   condition                — 'dm', 'htn', 'dlp', 'ob', 'prediab'
--   is_prevalent_year_end    — patient is eligible AND has condition at Dec 31
--   risk_factor_count        — sum of has_factor across all factors for (patient, condition)
--   is_high_risk             — risk_factor_count >= MIN_FACTORS_FOR_HIGH_RISK (default 2)
-- ============================================================================

CREATE OR REPLACE VIEW CHI_REPORTING.stg_high_risk_patient AS

WITH total_population AS (
    SELECT
        p._ID                                   AS patient_key,
        CASE WHEN DATEDIFF(YEAR, p.DATEOFBIRTH, cfg.report_start) > 18
              AND p.NATIONALID IS NOT NULL
              AND p.NATIONALID <> ''
              AND (p.DATEOFDEATH IS NULL OR p.DATEOFDEATH >= cfg.report_start)
             THEN TRUE ELSE FALSE
        END                                     AS is_in_total_population
    FROM NMR.LEANHIS.PATIENTS p
    CROSS JOIN CHI_REPORTING.chi_config cfg
    WHERE p.DATEOFBIRTH <= DATEADD(YEAR, -18, cfg.report_start)
),

-- One row per (patient, condition) where the patient is prevalent at year-end.
-- The "is pre X at year-end" check uses the condition's first-relevant-diagnosis
-- date. For v1 we hardcode the condition -> cohort view mapping inline; the
-- generic High-Risk report only needs the (patient, condition, is_prevalent)
-- pair, so a per-condition CASE here is sufficient.
prevalent_per_condition AS (
    SELECT
        tp.patient_key,
        cfg.report_year,
        'prediab'                AS condition,
        CASE WHEN pc.first_r73_date IS NOT NULL
              AND pc.first_r73_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                      AS is_prevalent_year_end,
        pc.is_in_total_population
    FROM total_population tp
    CROSS JOIN CHI_REPORTING.chi_config cfg
    LEFT JOIN CHI_REPORTING.stg_prediab_cohort pc
            ON pc.patient_key = tp.patient_key
    UNION ALL
    SELECT
        tp.patient_key,
        cfg.report_year,
        'dm'                     AS condition,
        CASE WHEN dc.first_e11_date IS NOT NULL
              AND dc.first_e11_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                      AS is_prevalent_year_end,
        dc.is_in_total_population
    FROM total_population tp
    CROSS JOIN CHI_REPORTING.chi_config cfg
    LEFT JOIN CHI_REPORTING.stg_dm_cohort dc
            ON dc.patient_key = tp.patient_key
    UNION ALL
    SELECT
        tp.patient_key,
        cfg.report_year,
        'htn'                    AS condition,
        CASE WHEN hc.first_i10_date IS NOT NULL
              AND hc.first_i10_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                      AS is_prevalent_year_end,
        hc.is_in_total_population
    FROM total_population tp
    CROSS JOIN CHI_REPORTING.chi_config cfg
    LEFT JOIN CHI_REPORTING.stg_htn_cohort hc
            ON hc.patient_key = tp.patient_key
    UNION ALL
    SELECT
        tp.patient_key,
        cfg.report_year,
        'dlp'                    AS condition,
        CASE WHEN lc.first_e78_date IS NOT NULL
              AND lc.first_e78_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                      AS is_prevalent_year_end,
        lc.is_in_total_population
    FROM total_population tp
    CROSS JOIN CHI_REPORTING.chi_config cfg
    LEFT JOIN CHI_REPORTING.stg_dlp_cohort lc
            ON lc.patient_key = tp.patient_key
    UNION ALL
    SELECT
        tp.patient_key,
        cfg.report_year,
        'ob'                     AS condition,
        CASE WHEN oc.first_e66_date IS NOT NULL
              AND oc.first_e66_date < cfg.report_end
             THEN TRUE ELSE FALSE
        END                      AS is_prevalent_year_end,
        oc.is_in_total_population
    FROM total_population tp
    CROSS JOIN CHI_REPORTING.chi_config cfg
    LEFT JOIN CHI_REPORTING.stg_ob_cohort oc
            ON oc.patient_key = tp.patient_key
),

-- Only conditions that have at least one risk factor in the config produce
-- output. This is the "extension point" — INSERT a row into chi_high_risk_factors
-- and that condition will start showing up in the report.
conditions_with_factors AS (
    SELECT DISTINCT condition
    FROM CHI_REPORTING.chi_high_risk_factors
),

-- One row per (patient, condition, factor) for evaluation. The source_view
-- and source_column from the config are used to compute has_factor. For the
-- "always_false" sentinel (unimplemented factors), has_factor = FALSE.
factor_evaluations AS (
    SELECT
        ppc.patient_key,
        ppc.condition,
        hrf.factor_code,
        hrf.weight,
        hrf.level_order,
        -- Evaluate the factor against the patient. The CHI_REPORTING.stg_prediab_cohort
        -- case is handled specially because its columns are direct boolean flags
        -- (not nested inside a CTE). Other conditions can be wired the same way
        -- by adding a CASE branch when their cohort view is added.
        CASE
            WHEN hrf.source_column = 'always_false' THEN FALSE
            WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort'
                 AND hrf.source_column = 'has_bmi_ge_25'        THEN COALESCE((SELECT has_bmi_ge_25          FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
            WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort'
                 AND hrf.source_column = 'has_htn_dx'           THEN COALESCE((SELECT has_htn_dx             FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
            WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort'
                 AND hrf.source_column = 'has_dlp_dx'           THEN COALESCE((SELECT has_dlp_dx             FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
            WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort'
                 AND hrf.source_column = 'has_gdm_history'      THEN COALESCE((SELECT has_gdm_history        FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
            WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort'
                 AND hrf.source_column = 'has_pcos'             THEN COALESCE((SELECT has_pcos               FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
            ELSE FALSE
        END                                                         AS has_factor
    FROM prevalent_per_condition ppc
    INNER JOIN conditions_with_factors cwf
            ON cwf.condition = ppc.condition
    CROSS JOIN CHI_REPORTING.chi_high_risk_factors hrf
    WHERE hrf.condition = ppc.condition
      AND ppc.is_prevalent_year_end = TRUE
)

SELECT
    patient_key,
    condition,
    report_year,
    SUM(CASE WHEN has_factor THEN weight ELSE 0 END)             AS risk_factor_count,
    CASE WHEN SUM(CASE WHEN has_factor THEN weight ELSE 0 END) >= 2
         THEN TRUE ELSE FALSE
    END                                                            AS is_high_risk
FROM factor_evaluations
GROUP BY patient_key, condition, report_year;

-- ############################################################################
-- rpt_high_risk_patients_annual — MOVED
-- ############################################################################
-- The cross-condition aggregator that was previously defined here has been
-- moved. In v1 the report was only producing output for PREDIAB (the only
-- condition with risk factors in chi_high_risk_factors), so it now lives at
-- project_queries/Prediabetes/prediab_high_risk_report.sql as
-- rpt_prediab_prevalence_high_risk_annual (prediabetes-specific).
--
-- When other conditions (DM, HTN, DLP, OB) add risk factors via the config
-- table, the corresponding rpt_{cond}_prevalence_high_risk_annual views
-- will live in their respective condition folders. A cross-condition
-- aggregator can be reintroduced here at that point if needed.
-- ============================================================================
