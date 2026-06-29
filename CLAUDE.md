# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Community Health Indicators (CHI) reporting project. Generates **9 report types** across **5 chronic conditions** from an EMR database (Snowflake, `NMR.LEANHIS` schema):

| Report | Frequency | What It Measures | Module |
|--------|-----------|-----------------|--------|
| **Screening Report** | Monthly | % of at-risk population tested for the condition (DM/HTN/DLP/OB only) | M1 |
| **Prevalence Report** | Annual | % of total population with the condition at year-end (all 5 conditions) | M1 |
| **Incidence Report** | Monthly | Rate of new cases developing among at-risk population (all 5 conditions) | M1 |
| **Control Level Report** | Annual | Disease control classification for diagnosed patients (per condition) | M2 |
| **Care Gap (Quarterly)** | Quarterly | % of diagnosed patients completing follow-up visits/labs each quarter (per condition) | M2 |
| **Care Gap (Annual)** | Annual | Distribution of patients by number of quarters with follow-up (per condition) | M2 |
| **High-Risk Prediabetes Prevalence** | Annual | % of Prediabetes-prevalent patients with ≥2 risk factors (BMI ≥25, HTN, DLP, family history, GDM, PCOS); v1 instantiation of the configurable High-Risk pattern in `chi_high_risk_factors` | M2 |

### Chronic Conditions & Their Data Sources

| Condition | Source Tables | Key Markers |
|-----------|--------------|-------------|
| **Diabetes Mellitus (DM)** | LABRESULTS + OBSERVATIONS (UNION ALL) | FBS, HbA1c |
| **Hypertension (HTN)** | OBSERVATIONS only | Systolic BP, Diastolic BP |
| **Dyslipidemia (DLP)** | LABRESULTS + OBSERVATIONS (UNION ALL) | HDL, LDL, Cholesterol, Triglyceride |
| **Obesity (OB)** | OBSERVATIONS only | BMI |
| **Prediabetes (PREDIAB)** | DIAGNOSIS_CODES only (R73.03); BMI joined inline for risk-factor classification | ICD-10 R73.03 |

Key distinction: **HTN and Obesity use OBSERVATIONS only** (vitals/clinic measurements). **DM and DLP use both** LABRESULTS and OBSERVATIONS since these tests can be recorded in either table. **Prediabetes** uses DIAGNOSIS_CODES (R73.03) for cohort membership and inline joins to BMI, HTN, DLP, GDM, and PCOS observations/diagnoses for the 6-factor risk profile.

## Project Queries — Modular Views (Primary)

The production Snowflake queries are organized as **modular views** in `project_queries/views/`. Each pipeline stage is a standalone `CREATE OR REPLACE VIEW` — independently queryable for debugging.

### File Structure (17 files, 38-377 lines each)

```
project_queries/
├── 00_config.sql                  -- CHI_REPORTING.chi_config + chi_control_thresholds + chi_care_gap_config + chi_high_risk_factors
├── 00a_high_risk_views.sql        -- stg_high_risk_patient (GENERIC per-(patient, condition) staging; reads chi_high_risk_factors)
│
├── dm_staging_views.sql       -- stg_dm_cohort, stg_dm_diagnosis, stg_dm_labs
├── dm_analytical_view.sql     -- stg_dm_patient_month (dual-unit FBS + A1C classification)
├── dm_report_views.sql        -- rpt_dm_screening/prevalence/incidence
├── dm_monitoring_views.sql    -- stg_dm_control_patient, stg_dm_care_gap_quarterly, rpt_dm_control, rpt_dm_care_gap_quarterly, rpt_dm_care_gap_annual
│
├── htn_staging_views.sql      -- stg_htn_cohort, stg_htn_diagnosis, stg_htn_labs (SYS/DIA)
├── htn_analytical_view.sql    -- stg_htn_patient_month (paired SYS+DIA per visit, combined thresholds)
├── htn_report_views.sql       -- rpt_htn_screening/prevalence/incidence
├── htn_monitoring_views.sql   -- stg_htn_control_patient, stg_htn_care_gap_quarterly, rpt_htn_control, rpt_htn_care_gap_quarterly, rpt_htn_care_gap_annual
│
├── dlp_staging_views.sql      -- stg_dlp_cohort, stg_dlp_diagnosis, stg_dlp_labs (4 lipid markers)
├── dlp_analytical_view.sql    -- stg_dlp_patient_month (gender-specific HDL, GREATEST of 4)
├── dlp_report_views.sql       -- rpt_dlp_screening/prevalence/incidence
├── dlp_monitoring_views.sql   -- stg_dlp_control_patient, stg_dlp_care_gap_quarterly, rpt_dlp_control, rpt_dlp_care_gap_quarterly, rpt_dlp_care_gap_annual
│
├── ob_staging_views.sql       -- stg_ob_cohort, stg_ob_diagnosis, stg_ob_labs (BMI + outlier filter)
├── ob_analytical_view.sql     -- stg_ob_patient_month (WHO BMI classification)
├── ob_report_views.sql        -- rpt_ob_screening/prevalence/incidence
└── ob_monitoring_views.sql    -- stg_ob_control_patient, stg_ob_care_gap_quarterly, rpt_ob_control, rpt_ob_care_gap_quarterly, rpt_ob_care_gap_annual

-- Prediabetes: Module-1 standard reports + Module-2 high-risk report
-- (the high-risk report is currently prediabetes-specific because only PREDIAB
--  has risk factors defined in chi_high_risk_factors; other conditions will
--  get their own rpt_{cond}_prevalence_high_risk_annual when their factors
--  are added)
project_queries/Prediabetes/
├── prediab_staging_views.sql       -- stg_prediab_cohort (with 6 risk-factor flags), stg_prediab_diagnosis (R73.03 only)
├── prediab_analytical_view.sql     -- stg_prediab_patient_month
├── prediab_report_views.sql        -- rpt_prediab_prevalence_annual, rpt_prediab_incidence_monthly
└── prediab_high_risk_report.sql   -- rpt_prediab_prevalence_high_risk_annual (Module-2 High-Risk, v1 specific to PREDIAB)


### View Dependency Chain (per condition)

```
chi_config + chi_control_thresholds + chi_care_gap_config + chi_high_risk_factors (shared)
    ├──► stg_{cond}_cohort      (patient × year — demographics + diagnosis flags)
    ├──► stg_{cond}_diagnosis   (patient × diagnosis — ICD-10 records, ranked)
    └──► stg_{cond}_labs        (patient × visit — standardized lab/obs results)
                └──► stg_{cond}_patient_month  (patient × month — analytical grain)
                            ├──► rpt_{cond}_screening_monthly
                            ├──► rpt_{cond}_prevalence_annual  (reads from stg_*_cohort)
                            ├──► rpt_{cond}_incidence_monthly
                            │
                            ├──► stg_{cond}_control_patient   (prevalent patient × year-end values)
                            │       └──► rpt_{cond}_control   (control level distribution)
                            │
                            └──► stg_{cond}_care_gap_quarterly (prevalent patient × quarter)
                                    ├──► rpt_{cond}_care_gap_quarterly
                                    └──► rpt_{cond}_care_gap_annual

chi_high_risk_factors (config-driven, no condition-specific source view)
    └──► stg_high_risk_patient (per-condition prevalent patient × factor flags, risk_factor_count, is_high_risk)
            └──► rpt_prediab_prevalence_high_risk_annual (prediabetes-specific Module-2 report; lives in Prediabetes/ folder; v1 produces output only for PREDIAB)
```

### Usage

1. Run `00_config.sql` once to create the schema + config table
2. Run `00a_high_risk_views.sql` → creates the generic `stg_high_risk_patient` (per-condition staging)
3. Run `{cond}_staging_views.sql` → creates 3 staging views
4. Run `{cond}_analytical_view.sql` → creates patient_month view
5. Run `{cond}_report_views.sql` → creates 3 report views
6. For the Module-2 High-Risk report, also run `Prediabetes/prediab_high_risk_report.sql` (v1 specific to PREDIAB)
7. Debug any stage: `SELECT * FROM CHI_REPORTING.stg_htn_patient_month WHERE patient_key = 'P03'`
8. Change year: `UPDATE CHI_REPORTING.chi_config SET report_year = 2026, ...` then re-run step 3-5

### Parameterization

All views reference `CHI_REPORTING.chi_config` (a single-row table) via `CROSS JOIN` for report year/date range. Change the year by updating one row — no hardcoded dates in any view.

## Key Reference Documents

| File | Purpose |
|------|---------|
| `Diabetes Indicators.docx` | Logic flow diagrams (source of truth for all conditions) |
| [docs/epidemiological_methodology.md](docs/epidemiological_methodology.md) | Cohort definitions, 6-report methodology (Screening, Prevalence, Incidence, Control, Care Gap Q, Care Gap Annual), screening & control thresholds, assumptions/limitations for all 4 conditions |

### Monolithic SQL files (legacy reference)

The original monolithic CTE-based queries are kept in `project_queries/` for reference. The views above are the modular replacement:

| File | Status |
|------|--------|
| [dm_reports.sql](project_queries/dm_reports.sql) | Replaced by views/dm_*.sql |
| [htn_reports.sql](project_queries/htn_reports.sql) | Replaced by views/htn_*.sql |
| [dlp_reports.sql](project_queries/dlp_reports.sql) | Replaced by views/dlp_*.sql |
| [ob_reports.sql](project_queries/ob_reports.sql) | Replaced by views/ob_*.sql |

## Target Architecture

All reports for a condition share a common **staging pipeline** before splitting into 6 outputs:

```
NMR.LEANHIS (Source EMR)
    │
    ├──► stg_{cond}_cohort          (patient × year — demographic flags, cohort membership)
    ├──► stg_{cond}_diagnosis       (patient × diagnosis — ICD-10/problem-list records)
    └──► stg_{cond}_labs            (patient × lab/obs — screening results, standardized names)
                │
                └──► stg_{cond}_patient_month  (patient × month — core analytical grain)
                            │
                            ├──► rpt_{cond}_screening_monthly
                            ├──► rpt_{cond}_prevalence_annual
                            ├──► rpt_{cond}_incidence_monthly
                            │
                            ├──► stg_{cond}_control_patient (patient-level control classification)
                            │       └──► rpt_{cond}_control
                            │
                            └──► stg_{cond}_care_gap_quarterly (patient × quarter)
                                    ├──► rpt_{cond}_care_gap_quarterly
                                    └──► rpt_{cond}_care_gap_annual
```

## Compliance & Care Gap Module

### Config Tables

**`chi_control_thresholds`** — Configurable disease control classification (30 rows across 4 conditions):
- Per-condition, per-marker ranges with min/max bounds
- Gender-specific thresholds (HDL for DLP: Male ≥40, Female ≥50)
- Descriptive labels include threshold ranges (e.g. "Controlled (A1C < 7.0%)")
- `level_order` (0-3) determines severity; GREATEST across markers = overall level

**`chi_care_gap_config`** — Single-row config: `target_quarters_completed` (default: 3)

**`chi_high_risk_factors`** — Configurable risk-factor definitions for the generic Module-2 High-Risk Patients report. Schema: `(condition, factor_code, factor_label, source_view, source_column, value_min, weight, requires_value, level_order)`. For v1 only Prediabetes has 6 factor rows (BMI ≥ 25, HTN dx, DLP dx, family-history placeholder, GDM history, PCOS via E28.2). To extend to a new condition: `INSERT` new rows into `chi_high_risk_factors`, extend the `CASE` chain in `stg_high_risk_patient.factor_evaluations`, and create a per-condition `rpt_{cond}_prevalence_high_risk_annual` view in the condition's folder.

### Control Monitoring Markers

| Condition | Marker(s) | Classification Method |
|-----------|-----------|----------------------|
| DM | A1C only | Most recent A1C value → threshold lookup |
| HTN | SYS + DIA (paired) | Most recent visit with both → classify each → GREATEST |
| DLP | HDL, LDL, CHOL, TRIG | Each marker from most recent non-null month → GREATEST of 4 |
| OB | BMI only | Most recent BMI value → threshold lookup |

### Care Gap Logic

- Year divided into 4 quarters (Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec)
- Quarter "completed" = ≥1 visit with the condition-specific lab that quarter
- Condition-specific lab checks: DM=A1C, HTN=had_bp (SYS+DIA paired), DLP=any lipid, OB=BMI
- Annual report counts patients by quarters_completed (0-4), includes "≥ Target" row

### Monitoring View Inventory (5 per condition × 4 = 20 views)

| View | Grain | Purpose |
|------|-------|---------|
| `stg_{cond}_control_patient` | 1 row / prevalent patient | Year-end lab value + control classification |
| `stg_{cond}_care_gap_quarterly` | 1 row / prevalent patient | Quarters completed + Q1-Q4 flags |
| `rpt_{cond}_control` | health_cluster × control_level | Aggregated control distribution |
| `rpt_{cond}_care_gap_quarterly` | health_cluster × quarter | Per-quarter completion rates |
| `rpt_{cond}_care_gap_annual` | health_cluster × quarters_completed | Annual distribution + target % |

### Naming Convention

| Prefix | Purpose | Example |
|--------|---------|---------|
| `stg_` | Staging table (patient-level, derived from EMR) | `stg_dm_cohort` |
| `rpt_` | Report output table (aggregated metrics) | `rpt_dm_screening_monthly` |

Condition codes: `dm`, `htn`, `dlp`, `ob`

### Standard Column Naming (used across all conditions)

| Pattern | Example | Meaning |
|---------|---------|---------|
| `patient_key` | — | Unique patient identifier |
| `year_month_key` | `202501` | YYYYMM integer for monthly grain |
| `is_*` | `is_screened`, `is_in_at_risk` | Boolean flag |
| `has_*` | `has_any_dm_diagnosis` | Ever/currently has a condition |
| `first_*_date` | `first_e11_date` | Date of first occurrence |
| `had_*` | `had_fbs`, `had_visit` | Event occurred in period |
| `last_*_value` | `last_fbs_value` | Most recent value in period |
| `*_count` | `screened_count` | Aggregated count |
| `*_pct` | `screening_rate_pct` | Percentage |
| `*_per_100k` | `incidence_rate_per_100k` | Rate per 100,000 |

### Report Output Columns (standardized across conditions)

All report tables include:
- `report_year`, `report_month` / `period_label`
- Denominator, numerator, breakdown counts
- Rate metrics (pct or per 100k)
- `sort_key` for ordering (month detail rows first, yearly total row last)

## Database Schema (Source EMR — NMR.LEANHIS)

- **`PATIENTS`** — Demographics: `_ID`, `NATIONALID`, `GENDERUID`, `DATEOFBIRTH`, `DATEOFDEATH`
- **`PATIENTVISITS`** — Visits: `_ID`, `PATIENTUID`, `STARTDATE`
- **`LABRESULTS`** / **`LABRESULTS_RESULTVALUES`** — Lab results: joined on `LABRESULTS._ID = LABRESULTS_RESULTVALUES.LABRESULTS_ID`
- **`OBSERVATIONS`** / **`OBSERVATIONS_OBSERVATIONVALUES`** — Clinical observations: joined on `OBSERVATIONS._ID = OBSERVATIONS_OBSERVATIONVALUES.OBSERVATIONS_ID`
- **`DIAGNOSIS_CODES`** — **[PLACEHOLDER]** ICD-10 diagnosis/problem-list. Exact table name TBD.

## Screening Classification Thresholds

**Diabetes** — `GREATEST(FBS_category, A1C_category)`:
- FBS (mg/dL): normal ≤ 99 | elevated 100–125 | abnormal > 125
- FBS (mmol/L): normal ≤ 5.5 | elevated 5.6–6.9 | abnormal > 6.9
- A1C: normal < 5.7 | elevated 5.7–6.4 | abnormal > 6.4

**Hypertension** — Combined SYS/DIA:
- normal: SYS < 120 AND DIA < 80
- elevated: SYS 120–129 OR DIA 80–89
- abnormal: SYS ≥ 130 OR DIA ≥ 90

**Obesity** — BMI:
- underweight < 18.5 | normal 18.5–24.9 | overweight 25–29.9 | obese ≥ 30
- Outliers: excludes BMI < 10 or > 80

**Dyslipidemia** — `GREATEST(HDL, Triglyceride, Cholesterol, LDL)` with gender-specific HDL:
- HDL (male): abnormal < 40 | HDL (female): abnormal < 50
- Triglyceride: normal < 150 | elevated 150–199 | abnormal ≥ 200
- Cholesterol: normal < 200 | elevated 200–239 | abnormal ≥ 240
- LDL: normal < 130 | elevated 130–159 | abnormal ≥ 160

## Snowflake-Specific Functions

- `MAX_BY(expr, order_expr)` — Value of `expr` at max `order_expr`
- `TRY_TO_DECIMAL(str, p, s)` — Safe string-to-number
- `REGEXP_SUBSTR(str, pattern)` — Regex extraction
- `TO_VARCHAR(date, fmt)` / `TO_DATE(str, fmt)` — Date formatting
- `NULLIF(expr, 0)` — Zero → NULL
- `IFF(condition, then, else)` — Ternary
- `BOOLOR_AGG(condition)` — True if any row matches
- `GREATEST(a, b, ...)` — Max across columns (used for worst-category classification)
- `ADD_MONTHS(date, n)` — Date arithmetic

## DuckDB Simulation

Local development/testing uses DuckDB. The simulation database is in `data/`; Python scripts are in `scripts/`:

| File | Purpose |
|------|---------|
| `data/chi_sim.db` | DuckDB database (20 synthetic patients, 2025 data) |
| `scripts/generate_synthetic_data.py` | Creates base DM data |
| `scripts/extend_data_htn_dlp_ob.py` | Adds HTN/DLP/OB data to the simulation |
| `scripts/create_views_in_duckdb.py` | Creates all 44 CHI_REPORTING views incl. compliance & care gap (DuckDB dialect) |
| `scripts/run_all_reports.py` | Config-driven runner for all 4 conditions — 6 reports each |

Usage: `uv run python scripts/run_all_reports.py [dm|htn|dlp|ob|prediab|high_risk|all]`

### DuckDB → Snowflake Dialect Mapping

When porting from the DuckDB simulation to Snowflake SQL:

| DuckDB | Snowflake |
|--------|-----------|
| `strptime(x, '%Y%m')` | `TO_DATE(x::VARCHAR \|\| '01', 'YYYYMMDD')` |
| `strptime(x, '%Y%m') + INTERVAL 1 MONTH` | `ADD_MONTHS(TO_DATE(...), 1)` |
| `bool_or()` | `BOOLOR_AGG()` |
| `TRY_CAST(x AS DECIMAL(10,2))` | `TRY_TO_DECIMAL(x, 10, 2)` |
| `regexp_extract()` | `REGEXP_SUBSTR()` |
| `strftime(date, '%b %Y')` | `TO_VARCHAR(date, 'MON YYYY')` |
| `arg_max(val, order)` | `MAX_BY(val, order)` |
| `bool_or()` | `BOOLOR_AGG()` |
| `QUARTER(date)` / custom CASE | Quarter computed from report_month ranges |

## Legacy Files

| File | Status |
|------|--------|
| `Diabitic report 14-6-26.sql` | Legacy — replaced by views/dm_*.sql |
| `HYPERTENSION report 14-6-26.sql` | Legacy — replaced by views/htn_*.sql |
| `Obesity report 14-6-26.sql` | Legacy — replaced by views/ob_*.sql |
| `dlp report 14-6-26.sql` | Legacy — replaced by views/dlp_*.sql |
| `project_queries/dm_reports.sql` | Legacy — replaced by views/dm_*.sql (monolithic CTE version, kept for reference) |
| `project_queries/htn_reports.sql` | Legacy — replaced by views/htn_*.sql |
| `project_queries/dlp_reports.sql` | Legacy — replaced by views/dlp_*.sql |
| `project_queries/ob_reports.sql` | Legacy — replaced by views/ob_*.sql |
| `DM.xlsx`, `HTN.xlsx`, `Obesity.xlsx`, `DLP.xlsx` | Outputs from legacy queries |
