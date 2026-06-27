# Community Health Indicators (CHI) — Methodology & Reporting Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture: The Staging Pipeline](#architecture-the-staging-pipeline)
3. [Report Definitions](#report-definitions)
4. [Population Cohorts & Indicators](#population-cohorts--indicators)
5. [Monthly vs. Annual Rates](#monthly-vs-annual-rates)
6. [Health Cluster Dimension](#health-cluster-dimension)
7. [Clinical Classification Thresholds](#clinical-classification-thresholds)
8. [Deployment Guide](#deployment-guide)
9. [Local Simulation (DuckDB)](#local-simulation-duckdb)

---

## Overview

The CHI reporting system generates **3 report types** across **4 chronic conditions** from an EMR database (Snowflake, `NMR.LEANHIS` schema). Each report type targets a distinct epidemiological question:

| Report | Frequency | Question It Answers |
|--------|-----------|---------------------|
| **Screening Report** | Monthly | What % of the at-risk population is being tested each month? |
| **Prevalence Report** | Annual | What % of the total population has the condition at year-end? |
| **Incidence Report** | Monthly | How many new cases are developing per 100,000 at-risk per month? |

### Conditions Covered

| Condition | ICD-10 Codes | Diagnostic Markers | Source Tables |
|-----------|-------------|--------------------|----------------|
| **Diabetes Mellitus (DM)** | E10, E11, E13, E14, O24 | Fasting Blood Sugar (FBS), HbA1c | LABRESULTS + OBSERVATIONS |
| **Hypertension (HTN)** | I10–I15 | Systolic BP, Diastolic BP | OBSERVATIONS only |
| **Dyslipidemia (DLP)** | E78 | HDL, LDL, Cholesterol, Triglyceride | LABRESULTS + OBSERVATIONS |
| **Obesity (OB)** | E66 | BMI | OBSERVATIONS only |

> **Key distinction**: HTN and Obesity use OBSERVATIONS only (vitals/clinic measurements recorded at point of care). DM and DLP use both LABRESULTS and OBSERVATIONS (tests may be recorded in either table), combined via `UNION ALL`.

---

## Architecture: The Staging Pipeline

### Why a Staging Pipeline?

Producing three fundamentally different reports (monthly screening, annual prevalence, monthly incidence) from the same raw EMR data requires reconciling conflicting temporal grains:

- **Screening** needs month-level aggregates: who was at-risk in January vs. who got tested in January
- **Prevalence** needs a year-end snapshot: who had the condition at any point before December 31
- **Incidence** needs month-level event detection: who received their **first-ever** diagnosis in a specific month

A monolithic query that handles all three simultaneously would be:
1. **Error-prone**: mixing annual and monthly logic in one CTE chain creates subtle bugs
2. **Unmaintainable**: changing one indicator risks breaking the others
3. **Untestable**: no way to debug intermediate results

The staging approach **decomposes the problem into independently queryable layers**, each producing a single, well-defined grain.

### The 3-Layer Architecture

```
NMR.LEANHIS (Source EMR)
    │
    ├──► stg_{cond}_cohort          (patient × year — one row per patient per report year)
    ├──► stg_{cond}_diagnosis       (patient × diagnosis — one row per ICD-10 record)
    └──► stg_{cond}_labs            (patient × visit — one row per screening result)
                │
                └──► stg_{cond}_patient_month  (patient × month — the core analytical grain)
                            │
                            ├──► rpt_{cond}_screening_monthly   (month × cluster)
                            ├──► rpt_{cond}_prevalence_annual   (year × cluster)
                            └──► rpt_{cond}_incidence_monthly   (month × cluster)
```

### Layer 1: Staging Views (`stg_*`)

Three views per condition, each extracts and standardizes one domain of source data:

| View | Grain | Purpose |
|------|-------|---------|
| `stg_{cond}_cohort` | patient × year | Demographics, eligibility, diagnosis flags, **health cluster** |
| `stg_{cond}_diagnosis` | patient × diagnosis | ICD-10 records with first-occurrence ranking (debugging) |
| `stg_{cond}_labs` | patient × visit | Screening results (FBS, BP, BMI, lipids) with standardized names |

**Why separate them?** Each staging view has a different join path:
- `cohort` joins PATIENTS → DIAGNOSIS_CODES → PHC_ASSIGNMENT (3 different sources)
- `labs` joins LABRESULTS/result values → PATIENTVISITS (with UNION ALL across LABS and OBS)
- `diagnosis` is a simple extract for auditability

Putting all three in one view would create a Cartesian explosion and make debugging impossible.

### Layer 2: Analytical View (`stg_{cond}_patient_month`)

The **single source of truth** for all downstream reports. Grain: **one row per patient per month**.

This view:

1. **Explodes** the cohort from year-grain to month-grain via `CROSS JOIN` with a 12-month spine
2. **Classifies** each patient-month: were they at-risk at month start? were they screened? what was the result?
3. **Detects** incident cases: did the first-ever diagnosis occur in this specific month?
4. **Handles dual-unit classification** (DM: mmol/L vs mg/dL auto-detected by value range)
5. **Handles visit-paired measurements** (HTN: SYS and DIA must come from the same visit)
6. **Applies gender-specific thresholds** (DLP: HDL cutoffs differ by gender)

Every report reads from this single view. Change the classification logic here, and all three reports update consistently.

### Layer 3: Report Views (`rpt_*`)

Three views per condition, each aggregating `stg_{cond}_patient_month` into the final output format:

| View | Grain | Columns |
|------|-------|---------|
| `rpt_{cond}_screening_monthly` | month × cluster | at-risk, screened, normal/elevated/abnormal, screening rate, abnormal rate |
| `rpt_{cond}_prevalence_annual` | year × cluster | total pop, prevalent, incident, pre-existing, prevalence rate |
| `rpt_{cond}_incidence_monthly` | month × cluster | at-risk start, incident cases, monthly rate per 100k |

### Why Not a Single Monolithic Query?

The original codebase (preserved in [`archive/NMR_queries/`](archive/NMR_queries/)) used monolithic CTE-based queries — one giant SQL file per condition that produced all 3 reports in a single execution. These files (~127–183 lines each) chained 12+ CTEs together with no intermediate checkpoints.

**What made the monoliths problematic:**

| Problem | Real-World Impact | Staging Solution |
|---------|-------------------|-----------------|
| Eligibility criteria duplicated in every CTE | Changing "age > 18" to "age ≥ 18" required finding and updating it in 4+ CTEs per file | `stg_{cond}_cohort` defines eligibility once |
| Classification logic copy-pasted across screening, prevalence, and incidence queries | Fixing a lab threshold meant updating it in 3 different CTE chains — one was always missed | `stg_{cond}_patient_month` classifies once, all 3 reports consume it |
| No way to inspect intermediate results | Debugging meant adding `SELECT * FROM cte_7` blocks mid-query, running truncated SQL, and hoping | Each `stg_*` view is independently queryable — `SELECT * FROM stg_htn_patient_month WHERE patient_key = 'P03'` |
| One syntax error broke all 3 reports | A missing comma in the screening CTE prevented prevalence and incidence from running too | Reports are independent — a bug in `rpt_dm_screening` doesn't affect `rpt_dm_prevalence` |
| Adding a dimension (e.g., health cluster) required touching every CTE | The health cluster addition touched 5+ CTEs per condition in the monolith; in staging it enters at the cohort and flows through | New dimensions enter at the staging layer and propagate automatically |

**Concrete example:** The legacy `archive/NMR_queries/Diabitic report 14-6-26.sql` computes at-risk population, screening results, prevalence, and incidence all in one 175-line CTE chain. To change the report year, you find-and-replace `'2025-01-01'` across the entire file. In the staging system, you update one row in `CHI_REPORTING.chi_config` and re-run.

---

## Report Definitions

### Report 1: Screening (Monthly)

Measures **testing coverage** among the at-risk population.

| Component | Definition |
|-----------|-----------|
| **Period** | Calendar month (e.g., Jan 2025) |
| **Denominator** | At-risk patients at month start: eligible patients with **no prior diagnosis** of the condition before the month began |
| **Numerator** | Patients from the denominator who had the relevant screening test(s) during the month |
| **Output Metric** | `screening_rate_pct = screened / at_risk × 100` |
| **Stratification** | By result category (normal / elevated / abnormal) among those screened |
| **Annual Rate** (subtotal rows) | Cumulative: `SUM(screened) / SUM(at_risk)` across all 12 months |

**What counts as "screened"?**

| Condition | Requirement |
|-----------|------------|
| DM | FBS **or** A1C recorded in the month |
| HTN | **Both** Systolic AND Diastolic BP recorded in the same visit |
| DLP | HDL **or** LDL recorded in the month |
| OB | BMI recorded in the month |

### Report 2: Prevalence (Annual)

Measures **disease burden** at a point in time. A **snapshot** as of December 31.

| Component | Definition |
|-----------|-----------|
| **Period** | Calendar year (snapshot at Dec 31) |
| **Denominator** | Total eligible population at Jan 1: age > 18, has National ID, alive |
| **Numerator** | Patients with the target ICD-10 code diagnosed **on or before** Dec 31 |
| **Output Metric** | `prevalence_rate_pct = prevalent / total_population × 100` |
| **Sub-counts** | Incident during the year, pre-existing before the year |

> **Important**: Prevalence uses the target ICD-10 code specifically (E11 for DM, I10 for HTN, E78 for DLP, E66 for OB), not all condition-related codes. The denominator is fixed at Jan 1 — patients who die or leave during the year remain in the denominator for that year.

### Report 3: Incidence (Monthly)

Measures **new disease occurrence** — the rate at which the at-risk population develops the condition.

| Component | Definition |
|-----------|-----------|
| **Period** | Calendar month |
| **Denominator** | At-risk patients at month start: same definition as Screening denominator |
| **Numerator** | Patients from the denominator who received their **first-ever** target ICD-10 diagnosis during the month |
| **Output (Monthly)** | `incidence_rate_per_100k = incident_cases / at_risk_start × 100,000` |
| **Output (Annual, subtotal rows)** | `annual_rate_per_100k = SUM(all incident cases) / at_risk_at_January × 100,000` |

> **Key**: The at-risk population **shrinks** over the year as patients become incident cases and leave the at-risk pool. The monthly rate uses that month's specific at-risk count. The annual rate uses the January at-risk as a fixed baseline.

---

## Population Cohorts & Indicators

### Cohort Definitions

```
TOTAL POPULATION
├── Inclusion criteria:  Age > 18 at Jan 1 of report year
│                        Has National ID (not null, not empty)
│                        Alive at Jan 1 (no death record before report start)
│
├── PREVALENT (excluded from at-risk pool)
│   └── Has ANY diagnosis in the condition's ICD-10 code set
│       before the report period
│
└── AT-RISK (denominator for screening and incidence)
    └── TOTAL POPULATION minus PREVALENT
        (includes patients with prediabetes or abnormal screening results
         who don't yet have a formal diagnosis)
```

### The "At-Risk" Indicator: Monthly vs. Annual Usage

The at-risk indicator (`is_at_risk_start`) is evaluated at each month boundary:

| Report | How At-Risk Is Used |
|--------|--------------------|
| **Screening (monthly)** | Denominator = patients at-risk at month **start**. At-risk pool shrinks over the year as patients are diagnosed and leave the pool. |
| **Incidence (monthly)** | Same denominator as screening — a patient must be at-risk at month start to be counted as a new case that month. |
| **Incidence (annual subtotal)** | Annual rate uses **January at-risk only** as a fixed baseline to avoid the denominator fluctuating across months. This answers: "Of the population at risk at the start of the year, how many developed the condition?" |
| **Prevalence (annual)** | Prevalence does not use the at-risk indicator. It uses the total eligible population. |

### Cumulative Sum vs. Monthly Rate

A critical methodological distinction:

**Monthly Rate** (detail rows):
```
screening_rate = screened_this_month / at_risk_this_month × 100
incidence_rate = new_cases_this_month / at_risk_this_month × 100,000
```
Each month is independent. A patient screened in both January and March counts in both months' numerators, but each month's denominator reflects the at-risk pool at that specific time.

**Annual Rate** (subtotal rows):
```
annual_incidence_rate = SUM(all cases across 12 months) / at_risk_at_January × 100,000
```
The numerator is the sum of 12 monthly numerators (a patient could only become incident once — their first diagnosis month — so no double-counting). The denominator is fixed at January, providing a stable baseline for comparison across years or clusters.

**Screening Annual Rate** (subtotal rows):
```
cumulative_screening_rate = SUM(screened across 12 months) / SUM(at_risk across 12 months) × 100
```
This is a **person-month rate**: it counts screening events (a patient screened 3 times counts 3 times) over person-months of at-risk exposure. This differs from the annual incidence approach because screening is a repeatable event, whereas incidence is a one-time transition.

---

## Health Cluster Dimension

Each patient is assigned to a **health cluster** via `NMR.LEANHIS.PHC_ASSIGNMENT(PATIENTUID, HEALTH_CLUSTER)`. This dimension flows through the entire pipeline:

```
PHC_ASSIGNMENT
    │
    └──► stg_{cond}_cohort  (LEFT JOIN, COALESCE → 'Unassigned' for missing)
                │
                └──► stg_{cond}_patient_month  (pass-through from cohort)
                            │
                            └──► All 3 report views  (GROUP BY health_cluster)
```

### Report Row Structure

Every report has a 3-level row hierarchy:

| sort_order | Row Type | Example |
|:---:|---|---|
| `0` | Monthly detail | `Cluster A / Jan 2025 / at_risk=6 / screened=1 / rate=16.7%` |
| `1` | Cluster subtotal | `── Cluster A TOTAL ── / SUM(at_risk)=66 / SUM(screened)=19 / rate=28.8%` |
| `2` | Grand total | `── ALL CLUSTERS ── / SUM(at_risk)=131 / SUM(screened)=48 / rate=36.6%` |

Unassigned patients (no PHC record) appear as their own group labelled `'Unassigned'` with their own subtotal row.

### ORDER BY

```
ORDER BY health_cluster, sort_order, sort_key
```

The box-drawing character `─` (U+2500) sorts after all ASCII letters in Unicode, so the grand total row naturally appears last.

---

## Clinical Classification Thresholds

### Diabetes Mellitus

Screening result = `GREATEST(FBS_category, A1C_category)` — the worst marker determines classification.

**FBS** (auto-detects mg/dL vs mmol/L by value range):

| Category | mmol/L (value < 30) | mg/dL (value ≥ 30) |
|----------|--------------------|--------------------|
| normal | ≤ 5.5 | ≤ 99 |
| elevated | 5.6 – 6.9 | 100 – 125 |
| abnormal | > 6.9 | > 125 |

**HbA1c**:

| Category | Threshold |
|----------|-----------|
| normal | < 5.7 |
| elevated (prediabetes) | 5.7 – 6.4 |
| abnormal (diabetic range) | > 6.4 |

### Hypertension (ACC/AHA 2017)

SYS and DIA must be **paired from the same visit**. A single reading is not enough to classify.

| Category | Threshold |
|----------|-----------|
| normal | SYS < 120 **AND** DIA < 80 |
| elevated | SYS 120–129 **OR** DIA 80–89 |
| abnormal (Stage 1+2) | SYS ≥ 130 **OR** DIA ≥ 90 |

The worst of SYS or DIA determines classification when they disagree.

### Dyslipidemia

Screening result = `GREATEST(HDL, Triglyceride, Cholesterol, LDL)` — worst of 4 lipid markers.

**HDL** (gender-specific, no "elevated" category):

| Gender | normal | abnormal |
|--------|--------|----------|
| Male | ≥ 40 | < 40 |
| Female | ≥ 50 | < 50 |

**Triglyceride**:

| normal | elevated | abnormal |
|--------|----------|----------|
| < 150 | 150 – 199 | ≥ 200 |

**Total Cholesterol**:

| normal | elevated | abnormal |
|--------|----------|----------|
| < 200 | 200 – 239 | ≥ 240 |

**LDL**:

| normal | elevated | abnormal |
|--------|----------|----------|
| < 130 | 130 – 159 | ≥ 160 |

### Obesity (WHO BMI)

| Category | BMI Range |
|----------|-----------|
| underweight | < 18.5 |
| normal | 18.5 – 24.9 |
| elevated (overweight) | 25.0 – 29.9 |
| abnormal (obese) | ≥ 30.0 |

Outlier filter: BMI values < 10 or > 80 are excluded as clinically implausible.

---

## Deployment Guide

### Prerequisites

1. A Snowflake account with access to the `NMR.LEANHIS` schema
2. The `NMR.LEANHIS.PHC_ASSIGNMENT(PATIENTUID, HEALTH_CLUSTER)` table must exist
3. The `NMR.LEANHIS.DIAGNOSIS_CODES` table must exist (marked `[PLACEHOLDER]` — update if the real table name differs)

### Quick Deploy

A single concatenated SQL file is generated for deployment:

```bash
# Generate the deploy file
uv run python deploy_to_snowflake.py --year 2025 --output chi_reporting_deploy.sql

# Deploy to Snowflake
snowsql -f chi_reporting_deploy.sql
```

Or copy-paste the generated `chi_reporting_deploy.sql` into a Snowflake worksheet.

### Deployment Order

The 13 files deploy in dependency order:

```
 1. 00_config.sql              — Schema + report year parameter
 2. dm_staging_views.sql       — stg_dm_cohort, stg_dm_diagnosis, stg_dm_labs
 3. dm_analytical_view.sql     — stg_dm_patient_month
 4. dm_report_views.sql        — rpt_dm_screening/prevalence/incidence
 5. htn_staging_views.sql      — stg_htn_cohort, stg_htn_diagnosis, stg_htn_labs
 6. htn_analytical_view.sql    — stg_htn_patient_month
 7. htn_report_views.sql       — rpt_htn_screening/prevalence/incidence
 8. dlp_staging_views.sql      — stg_dlp_cohort, stg_dlp_diagnosis, stg_dlp_labs
 9. dlp_analytical_view.sql    — stg_dlp_patient_month
10. dlp_report_views.sql        — rpt_dlp_screening/prevalence/incidence
11. ob_staging_views.sql        — stg_ob_cohort, stg_ob_diagnosis, stg_ob_labs
12. ob_analytical_view.sql      — stg_ob_patient_month
13. ob_report_views.sql         — rpt_ob_screening/prevalence/incidence
```

### Changing the Report Year

Update one row in the config table, then re-run all views:

```sql
UPDATE CHI_REPORTING.chi_config
SET report_year = 2026,
    report_start = '2026-01-01'::DATE,
    report_end = '2027-01-01'::DATE;
```

### Querying Reports

```sql
-- Screening: per-cluster monthly breakdown
SELECT * FROM CHI_REPORTING.rpt_dm_screening_monthly
ORDER BY health_cluster, sort_order, sort_key;

-- Prevalence: per-cluster annual snapshot (WHERE sort_order = 2 for grand total)
SELECT * FROM CHI_REPORTING.rpt_dm_prevalence_annual
WHERE sort_order = 2;

-- Incidence: per-cluster monthly breakdown
SELECT * FROM CHI_REPORTING.rpt_dm_incidence_monthly
ORDER BY health_cluster, sort_order, sort_key;
```

---

## Local Simulation (DuckDB)

A local DuckDB simulation with 20 synthetic patients is available for development and testing:

```bash
# Generate synthetic data (creates data/chi_sim.db)
uv run python scripts/generate_synthetic_data.py
uv run python scripts/extend_data_htn_dlp_ob.py

# Create all views (mirrors the Snowflake deployment)
uv run python scripts/create_views_in_duckdb.py

# Run reports
uv run python scripts/run_all_reports.py all
# Or: uv run python scripts/run_all_reports.py dm
```

### Simulation Data Profile

| Attribute | Details |
|-----------|---------|
| Total patients | 20 |
| Eligible (total pop) | 17 |
| Clusters | Cluster A (7), Cluster B (6), Cluster C (3), Unassigned (1) |
| DM prevalent | 5, DM incident | 4 |
| HTN prevalent | 4, HTN incident | 3 |
| DLP prevalent | 3, DLP incident | 2 |
| OB prevalent | 3, OB incident | 1 |

### DuckDB → Snowflake Dialect Mapping

| DuckDB | Snowflake |
|--------|-----------|
| `strptime(x, '%Y%m')` | `TO_DATE(x::VARCHAR \|\| '01', 'YYYYMMDD')` |
| `strptime(x, '%Y%m') + INTERVAL 1 MONTH` | `ADD_MONTHS(TO_DATE(...), 1)` |
| `bool_or()` | `BOOLOR_AGG()` |
| `TRY_CAST(x AS DECIMAL(10,2))` | `TRY_TO_DECIMAL(x, 10, 2)` |
| `regexp_extract()` | `REGEXP_SUBSTR()` |
| `strftime(date, '%b %Y')` | `TO_VARCHAR(date, 'MON YYYY')` |
| `arg_max(val, order)` | `MAX_BY(val, order)` |

---

## File Reference

```
CHI_Report/
├── README.md                              ← This file
├── CLAUDE.md                              ← AI assistant instructions
├── conceptual_map_dm.md                   ← DM cohort definitions & logic flow
├── deploy_to_snowflake.py                 ← Deployment script generator
├── chi_reporting_deploy.sql               ← Generated deploy file
│
├── project_queries/
│   ├── 00_config.sql                      ← Schema + config table
│   ├── Diabetes/
│   │   ├── dm_staging_views.sql           ← stg_dm_cohort, diagnosis, labs
│   │   ├── dm_analytical_view.sql         ← stg_dm_patient_month
│   │   └── dm_report_views.sql            ← rpt_dm_screening/prevalence/incidence
│   ├── HTN/
│   │   ├── htn_staging_views.sql
│   │   ├── htn_analytical_view.sql
│   │   └── htn_report_views.sql
│   ├── DLP/
│   │   ├── dlp_staging_views.sql
│   │   ├── dlp_analytical_view.sql
│   │   └── dlp_report_views.sql
│   └── OBS/
│       ├── ob_staging_views.sql
│       ├── ob_analytical_view.sql
│       └── ob_report_views.sql
│
├── pyproject.toml                               ← Python project config
├── deploy_to_snowflake.py                       ← Deployment script generator
│
├── scripts/
│   ├── generate_synthetic_data.py                ← Creates 20-patient dataset
│   ├── extend_data_htn_dlp_ob.py                ← Adds HTN/DLP/OB data
│   ├── create_views_in_duckdb.py                ← All 24 views (DuckDB dialect)
│   └── run_all_reports.py                       ← Dynamic SQL runner
│
└── data/
    └── chi_sim.db                               ← DuckDB simulation database
```
