-- ============================================================================
-- HIGH-RISK PATIENTS (GENERIC) — STAGING + REPORT VIEWS
-- ============================================================================
-- Creates 2 views that implement the generic High-Risk Patients report
-- (Module 2, Report 7). The report is parameterized by condition via the
-- chi_high_risk_factors config table (see 00_config.sql).
--
-- For v1, only PREDIAB has factors defined. Other conditions return
-- zero-filled rows in the report. To extend: INSERT new rows into
-- chi_high_risk_factors — no SQL change required.
--
-- Prerequisites:
--   1. Run 00_config.sql first (creates CHI_REPORTING.chi_config + config tables)
--   2. Run all per-condition staging views (so stg_*_cohort views exist for
--      the risk-factor JOINs)
--   3. Run Prediabetes/prediab_staging_views.sql so the 6 PREDIAB risk-factor
--      flag columns exist on stg_prediab_cohort
-- ============================================================================


-- ############################################################################
-- VIEW 1: stg_high_risk_patient
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
-- VIEW 2: rpt_high_risk_patients_annual
-- ############################################################################
-- Generic annual report: per condition, per cluster, count prevalent patients
-- who are flagged is_high_risk = TRUE. Denominator = condition-prevalent at
-- year-end. Numerator = subset with risk_factor_count >= 2.
--
-- Output rows: one detail row (sort_order=0) per (condition, cluster) + one
-- grand total row (sort_order=2) per condition. For v1 only PREDIAB has
-- non-zero counts.
-- ============================================================================

CREATE OR REPLACE VIEW CHI_REPORTING.rpt_high_risk_patients_annual AS

WITH base AS (
    SELECT
        hr.condition,
        COALESCE(pc.health_cluster, 'Unassigned')   AS health_cluster,
        hr.is_high_risk
    FROM CHI_REPORTING.stg_high_risk_patient hr
    LEFT JOIN CHI_REPORTING.stg_prediab_cohort pc
            ON pc.patient_key = hr.patient_key AND hr.condition = 'prediab'
    LEFT JOIN CHI_REPORTING.stg_dm_cohort dc
            ON dc.patient_key = hr.patient_key AND hr.condition = 'dm'
    LEFT JOIN CHI_REPORTING.stg_htn_cohort hc
            ON hc.patient_key = hr.patient_key AND hr.condition = 'htn'
    LEFT JOIN CHI_REPORTING.stg_dlp_cohort lc
            ON lc.patient_key = hr.patient_key AND hr.condition = 'dlp'
    LEFT JOIN CHI_REPORTING.stg_ob_cohort oc
            ON oc.patient_key = hr.patient_key AND hr.condition = 'ob'
)

-- Detail rows (sort_order=0): per condition × cluster
SELECT
    condition,
    health_cluster,
    COUNT(*)                                          AS total_prevalent,
    SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)     AS high_risk_count,
    ROUND(
        SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) * 100.0
        / NULLIF(COUNT(*), 0), 2
    )                                                 AS high_risk_pct,
    health_cluster                                    AS sort_key,
    0                                                 AS sort_order
FROM base
GROUP BY condition, health_cluster

UNION ALL

-- Grand total (sort_order=2): per condition
SELECT
    condition,
    '── ALL CLUSTERS ──'                            AS health_cluster,
    COUNT(*)                                          AS total_prevalent,
    SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)     AS high_risk_count,
    ROUND(
        SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) * 100.0
        / NULLIF(COUNT(*), 0), 2
    )                                                 AS high_risk_pct,
    '── ALL CLUSTERS ──'                            AS sort_key,
    2                                                 AS sort_order
FROM base
GROUP BY condition

ORDER BY condition, sort_order, sort_key;