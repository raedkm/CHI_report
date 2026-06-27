# SQL Table Definitions — Diabetes Mellitus (DM) Reports

## Naming Convention

| Prefix | Purpose | Grain |
|--------|---------|-------|
| `stg_` | Staging table — derived from source EMR, transformed & cleaned | Patient-level |
| `rpt_` | Report output table — aggregated metrics ready for Excel/BI | Summary-level |

Condition suffix: `_dm` (Diabetes Mellitus), `_htn` (Hypertension), `_dlp` (Dyslipidemia), `_ob` (Obesity)

---

## Staging Tables

### 1. `stg_dm_cohort`

**Purpose:** One row per patient per report year. Defines which population cohorts each patient belongs to.

| Column | Type | Description |
|--------|------|-------------|
| `patient_key` | VARCHAR | Unique patient identifier (hashed National ID) |
| `report_year` | INTEGER | Report year (e.g., 2025) |
| `national_id_hash` | VARCHAR | De-identified National ID |
| `gender` | VARCHAR | 'Male' / 'Female' |
| `date_of_birth` | DATE | Patient date of birth |
| `age_at_jan1` | INTEGER | Age in years at Jan 1 of report year |
| `date_of_death` | DATE | Date of death, NULL if alive |
| `is_alive_at_jan1` | BOOLEAN | Alive at Jan 1 of report year (death date is NULL or after Jan 1) |
| `has_national_id` | BOOLEAN | National ID present and valid |
| `is_in_total_population` | BOOLEAN | TRUE if age>18 AND alive AND has National ID at Jan 1 |
| `first_any_dm_date` | DATE | Earliest date of any DM diagnosis (E10, E11, E13, E14, O24) |
| `first_e11_date` | DATE | Earliest date of E11 (Type 2 DM) diagnosis |
| `has_dm_type1` | BOOLEAN | Ever diagnosed E10 |
| `has_dm_type2` | BOOLEAN | Ever diagnosed E11 |
| `has_dm_other` | BOOLEAN | Ever diagnosed E13 or E14 |
| `has_gdm` | BOOLEAN | Ever diagnosed O24 (gestational DM) |
| `has_any_dm_diagnosis` | BOOLEAN | Has any DM diagnosis (E10, E11, E13, E14, O24) |
| `has_prediabetes` | BOOLEAN | Ever diagnosed R73.03 or R73.09 (prediabetes) |
| `is_in_at_risk` | BOOLEAN | TRUE if `is_in_total_population` AND NOT `has_any_dm_diagnosis` (**prediabetes IS included in at-risk**) |
| `is_dm_prevalent` | BOOLEAN | TRUE if `is_in_total_population` AND `has_any_dm_diagnosis` |

**Source tables:** `NMR.LEANHIS.PATIENTS`, `NMR.LEANHIS.PATIENTVISITS` (or a diagnosis codes table)

---

### 2. `stg_dm_diagnosis`

**Purpose:** One row per diagnosis record. Extracts DM-related ICD-10 codes from EMR.

| Column | Type | Description |
|--------|------|-------------|
| `patient_key` | VARCHAR | Patient identifier |
| `diagnosis_date` | DATE | Date the diagnosis was recorded |
| `icd10_code` | VARCHAR | ICD-10 code (e.g., 'E11', 'E10', 'O24') |
| `icd10_description` | VARCHAR | Plain-text description |
| `diagnosis_source` | VARCHAR | Source EMR table the record came from |
| `diagnosis_rank` | INTEGER | 1 = first occurrence of this code for this patient (used for incidence) |

**Source tables:** NMR.LEANHIS diagnosis/problem list table (to be identified)

---

### 3. `stg_dm_labs`

**Purpose:** One row per relevant lab/observation result. Standardizes result names and units.

| Column | Type | Description |
|--------|------|-------------|
| `patient_key` | VARCHAR | Patient identifier |
| `visit_date` | DATE | Date of visit when lab was drawn |
| `result_name` | VARCHAR | Standardized result name (see mapping below) |
| `result_value` | DECIMAL(10,2) | Numeric result value |
| `result_unit` | VARCHAR | Unit of measure |
| `source_table` | VARCHAR | 'LABRESULTS' or 'OBSERVATIONS' |
| `visit_year_month` | INTEGER | YYYYMM integer key for monthly grouping |

**Result Name Standardization:**

| Standard Name | Raw EMR Names Matched |
|--------------|----------------------|
| `FBS` | 'Fasting glucose', 'Fasting glucose [Mass or Moles/volume] in Serum or Plasma', 'GLUCOSE FASTING' |
| `A1C` | 'Hemoglobin A1c.' |

**Source tables:** `NMR.LEANHIS.LABRESULTS` + `LABRESULTS_RESULTVALUES`, `NMR.LEANHIS.OBSERVATIONS` + `OBSERVATIONS_OBSERVATIONVALUES`

---

### 4. `stg_dm_patient_month`

**Purpose:** One row per patient per month. The core analytical table — every report query reads from this.

| Column | Type | Description |
|--------|------|-------------|
| `patient_key` | VARCHAR | Patient identifier |
| `report_year` | INTEGER | Report year |
| `report_month` | INTEGER | 1–12 |
| `year_month_key` | INTEGER | YYYYMM integer |
| `age_at_month_start` | INTEGER | Age at start of this month |
| `is_alive_at_start` | BOOLEAN | Alive at month start |
| `is_in_total_population` | BOOLEAN | Still meets total population criteria |
| `is_at_risk_start` | BOOLEAN | No DM diagnosis before this month starts (at-risk pool) |
| `is_at_risk_end` | BOOLEAN | No DM diagnosis before this month ends |
| `has_any_dm_before` | BOOLEAN | Had any DM diagnosis before this month |
| `has_e11_before` | BOOLEAN | Had E11 diagnosis before this month |
| `had_visit` | BOOLEAN | Had at least 1 visit during this month |
| `had_fbs` | BOOLEAN | Had FBS result during this month |
| `had_a1c` | BOOLEAN | Had A1C result during this month |
| `is_screened` | BOOLEAN | `had_fbs OR had_a1c` — screening numerator flag |
| `last_fbs_value` | DECIMAL(10,2) | Most recent FBS value in month |
| `last_a1c_value` | DECIMAL(10,2) | Most recent A1C value in month |
| `fbs_category` | VARCHAR | 'normal' / 'elevated' / 'abnormal' (see thresholds) |
| `a1c_category` | VARCHAR | 'normal' / 'elevated' / 'abnormal' |
| `screening_category` | VARCHAR | Worst of `fbs_category` and `a1c_category` |
| `received_new_e11` | BOOLEAN | First-ever E11 diagnosis occurred in this month → INCIDENT CASE |
| `has_e11_at_end` | BOOLEAN | Has E11 diagnosis as of this month end → PREVALENT CASE |
| `has_prediabetes_before` | BOOLEAN | Has prediabetes diagnosis before this month |

**Screening Category Thresholds (same as current SQL logic):**

| Category | FBS (mg/dL) | FBS (mmol/L) | A1C (%) |
|----------|------------|--------------|---------|
| `normal` | ≤ 99 | ≤ 5.5 | < 5.7 |
| `elevated` | 100–125 | 5.6–6.9 | 5.7–6.4 |
| `abnormal` | > 125 | > 6.9 | > 6.4 |

---

## Report Output Tables

### 5. `rpt_dm_screening_monthly`

**Purpose:** Monthly screening report — one row per month. Ready for Excel export.

| Column | Type | Description |
|--------|------|-------------|
| `report_year` | INTEGER | Report year |
| `report_month` | INTEGER | 1–12 |
| `period_label` | VARCHAR | 'JAN 2025', 'FEB 2025', etc. |
| `at_risk_population` | INTEGER | **Denominator** — At-risk patients at month end (no DM dx) |
| `screened_count` | INTEGER | **Numerator** — At-risk patients with FBS or A1C this month |
| `normal_count` | INTEGER | Screened patients with normal results |
| `elevated_count` | INTEGER | Screened patients with elevated/prediabetic results |
| `abnormal_count` | INTEGER | Screened patients with diabetic-range results |
| `screening_rate_pct` | DECIMAL(8,4) | `screened_count / at_risk_population * 100` |
| `abnormal_rate_pct` | DECIMAL(8,4) | `abnormal_count / screened_count * 100` |
| `sort_key` | INTEGER | YYYYMM for ordering |

---

### 6. `rpt_dm_prevalence_annual`

**Purpose:** Annual prevalence report — one row per year. Snapshot at Dec 31.

| Column | Type | Description |
|--------|------|-------------|
| `report_year` | INTEGER | Report year |
| `total_population` | INTEGER | **Denominator** — Total eligible population at Jan 1 |
| `prevalent_dm_count` | INTEGER | **Numerator** — Patients with E11 at Dec 31 of report year |
| `incident_during_year` | INTEGER | Sub-count: newly diagnosed E11 during this year |
| `pre_existing_dm_count` | INTEGER | Sub-count: E11 diagnosed before this year |
| `prevalence_rate_pct` | DECIMAL(8,4) | `prevalent_dm_count / total_population * 100` |
| `period_label` | VARCHAR | '── 2025 TOTAL ──' |

---

### 7. `rpt_dm_incidence_monthly`

**Purpose:** Monthly incidence report — one row per month.

| Column | Type | Description |
|--------|------|-------------|
| `report_year` | INTEGER | Report year |
| `report_month` | INTEGER | 1–12 |
| `period_label` | VARCHAR | 'JAN 2025', etc. |
| `at_risk_population_start` | INTEGER | **Denominator** — At-risk patients at month start |
| `incident_cases` | INTEGER | **Numerator** — Patients who received first-ever E11 this month |
| `incidence_rate_per_100k` | DECIMAL(8,2) | `incident_cases / at_risk_population_start * 100000` |
| `sort_key` | INTEGER | YYYYMM for ordering |

---

## Relationship Diagram (Simplified)

```
NMR.LEANHIS (Source EMR)
    │
    ├──► stg_dm_cohort          (patient × year — who belongs where)
    ├──► stg_dm_diagnosis       (patient × diagnosis — ICD-10 records)
    └──► stg_dm_labs            (patient × lab — FBS/A1C results)
                │
                └──► stg_dm_patient_month  (patient × month — unified analytical grain)
                            │
                            ├──► rpt_dm_screening_monthly
                            ├──► rpt_dm_prevalence_annual
                            └──► rpt_dm_incidence_monthly
```
