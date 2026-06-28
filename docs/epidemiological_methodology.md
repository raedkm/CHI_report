# Epidemiological Methodology — CHI Report Views

## Table of Contents

1. [Study Design](#study-design)
2. [Population Eligibility](#population-eligibility)
3. [Cohort Definitions](#cohort-definitions)
   - 3.1 [Prevalent Cohort](#prevalent-cohort)
   - 3.2 [At-Risk Cohort](#at-risk-cohort)
   - 3.3 [Dynamic Cohort Membership](#dynamic-cohort-membership)
4. [The At-Risk Population](#the-at-risk-population)
5. [Screening Thresholds](#screening-thresholds)
   - 5.1 [Diabetes Mellitus](#diabetes-mellitus-screening)
   - 5.2 [Hypertension](#hypertension-accaha-2017)
   - 5.3 [Dyslipidemia](#dyslipidemia)
   - 5.4 [Obesity](#obesity-who-bmi)
6. [Module 1: Epidemiological Surveillance](#module-1-epidemiological-surveillance)
   - 6.1 [Report 1 — Screening (Monthly Coverage)](#report-1---screening-monthly-coverage)
   - 6.2 [Report 2 — Prevalence (Annual Point Prevalence)](#report-2---prevalence-annual-point-prevalence)
   - 6.3 [Report 3 — Incidence (Monthly Incidence Rate)](#report-3---incidence-monthly-incidence-rate)
   - 6.4 [Monthly vs. Annual Rate Calculations](#monthly-vs-annual-rate-calculations)
   - 6.5 [Health Cluster Stratification](#health-cluster-stratification)
7. [Module 2: Compliance & Care Gap](#module-2-compliance--care-gap)
   - 7.0 [Module 2 Preamble](#module-2-preamble)
   - 7.1 [Report 4 — Control Level (Annual)](#report-4---control-level-annual)
   - 7.2 [Report 5 — Care Gap (Quarterly)](#report-5---care-gap-quarterly)
   - 7.3 [Report 6 — Care Gap (Annual)](#report-6---care-gap-annual)
   - 7.4 [Control Thresholds](#control-thresholds)
   - 7.5 [Quarterly Definitions & Follow-Up Criteria](#quarterly-definitions--follow-up-criteria)
8. [Assumptions & Limitations](#assumptions--limitations)
   - 8.1 [Shared Assumptions](#shared-assumptions-module-1--module-2)
   - 8.2 [Module 1 Assumptions & Limitations](#module-1-assumptions--limitations)
   - 8.3 [Module 2 Assumptions & Limitations](#module-2-assumptions--limitations)
9. [Reference: Formula Index](#reference-formula-index)

---

## Study Design

**Design type**: Retrospective cohort study using electronic medical record (EMR) data from the `NMR.LEANHIS` Snowflake schema.

**Observation period**: One calendar year (January 1 – December 31), configurable via the `CHI_REPORTING.chi_config` parameter table. Changing the report year requires updating a single row; all downstream views reference this configuration.

**Unit of analysis**: The **patient-month**. Each eligible patient contributes up to 12 monthly observations. The patient-month is the analytical grain from which all six epidemiological measures — screening, prevalence, incidence (Module 1) and control, quarterly care gap, annual care gap (Module 2) — are derived.

**Data sources**:

| Table | Content | Used By |
|-------|---------|---------|
| `PATIENTS` | Demographics, vital status | Cohort eligibility |
| `PATIENTVISITS` | Encounter dates | Monthly visit detection |
| `LABRESULTS` / `LABRESULTS_RESULTVALUES` | Laboratory test results | DM, DLP screening & control |
| `OBSERVATIONS` / `OBSERVATIONS_OBSERVATIONVALUES` | Clinical observations (vitals) | All four conditions |
| `DIAGNOSIS_CODES` | ICD-10 diagnosis records | Cohort classification, incidence detection |
| `PHC_ASSIGNMENT` | Health cluster assignment | Stratification dimension (both modules) |

---

## Population Eligibility

A patient is included in the **total population** for report year *Y* if they meet **all** of the following criteria at January 1 of year *Y*:

- **C1. Age**: > 18 years at January 1. Pediatric thresholds differ for most chronic conditions and are outside the scope of this reporting system.
- **C2. National ID**: Present and non-empty in the EMR. Ensures patient identity is verified and excludes transient or tourist encounters.
- **C3. Vital status**: Alive at January 1 (no death record with a date before the report start). Deceased patients cannot contribute person-time during the report year.

Patients meeting all three criteria are flagged `is_in_total_population = TRUE`. This flag is evaluated once per report year and does *not* change month-to-month. A patient who dies during the year remains in the denominator for that year's prevalence calculation (consistent with standard point prevalence methodology).

---

## Cohort Definitions

From the total population, two mutually exclusive cohorts are derived based on diagnosis history. These cohorts underpin both modules of the CHI reporting system:

```
TOTAL POPULATION (eligible at Jan 1)
│
├── PREVALENT COHORT
│   └── Has ≥1 diagnosis in the condition's ICD-10 code set (any date)
│       → Module 2 base population (Reports 4-6)
│       → Module 1 prevalence numerator
│
└── AT-RISK COHORT
    └── No diagnosis in the condition's ICD-10 code set
        → Module 1 screening and incidence denominator
        (Reports 1, 3)
```

### Prevalent Cohort

A patient is **prevalent** if they have *any* ICD-10 code in the condition's code set, regardless of whether it is the primary target code. This cohort is the base population for:

- **Module 1** — Report 2 (Prevalence numerator)
- **Module 2** — Reports 4, 5, 6 (denominator of all care-gap and control metrics)

| Condition | ICD-10 Code Set (Prevalent) | Target Code (Incidence) |
|-----------|------------------------------|--------------------------|
| Diabetes Mellitus (DM) | E10, E11, E13, E14, O24 | E11 |
| Hypertension (HTN) | I10, I11, I12, I13, I15 | I10 |
| Dyslipidemia (DLP) | E78 | E78 |
| Obesity (OB) | E66 | E66 |

> **Why the broader code set in DM?** A patient with Type 1 diabetes (E10) or gestational diabetes (O24) is already a known diabetic — screening them for Type 2 DM makes no clinical sense. The at-risk pool should exclude all known diabetics. However, incidence tracking focuses specifically on Type 2 (E11) because it is the preventable, lifestyle-related form that public health programs target.

### At-Risk Cohort

```
AT-RISK = TOTAL POPULATION − PREVALENT COHORT
```

The at-risk cohort is used **only by Module 1** (Reports 1 and 3) and includes:

- Patients with **no diagnosis** in the condition's code set before the report year
- Patients with **prediabetes** or abnormal screening results who lack a formal ICD-10 diagnosis
- Patients who have **never been screened**

### Dynamic Cohort Membership

Cohort assignment is **not static** across the year. The at-risk pool shrinks month-by-month as patients receive their first diagnosis and transition to the prevalent cohort. The staging system evaluates `is_at_risk_start` at each month boundary, not once at the start of the year. This dynamic evaluation is relevant only to Module 1; Module 2's base population is fixed at a single reference date (see [§7.0](#module-2-preamble)).

```
                  ┌── Incident in Mar → leaves at-risk pool for Apr–Dec
                  │
Jan ─── Feb ─── Mar ─── Apr ─── May ─── Jun ─── Jul ─── Aug ─── Sep ─── Oct ─── Nov ─── Dec

At-risk at Jan 1: 13 patients
At-risk at Dec 1: 10 patients (3 became incident during the year)
```

---

## The At-Risk Population

### Definition

For month *M*:

```
is_at_risk_start(M) = TRUE  if patient is in TOTAL POPULATION
                            AND has no diagnosis in the condition's ICD-10 set
                            with diagnosis date < first day of month M

is_at_risk_start(M) = FALSE otherwise
```

### Why Monthly Evaluation?

Three epidemiological reasons:

1. **Accurate denominators**. The at-risk population is the denominator for both screening and incidence rates. Using a fixed year-start denominator would overstate the population at risk in later months.
2. **Censoring at diagnosis**. A patient can only be an incident case once. After their first diagnosis, they leave the at-risk pool. The monthly evaluation correctly censors them from subsequent months' denominators.
3. **Time-varying exposure**. Screening behavior changes when patients know they have a condition. A patient diagnosed in March should not be counted as "at-risk but unscreened" in November — they are already under management.

---

## Screening Thresholds

Screening thresholds classify **at-risk** patients (Module 1 base population) into Normal / Elevated / Abnormal categories based on the most recent screening test result. These cut-points are used by Module 1's Screening report (Report 1) only. Module 2 uses a separate set of control thresholds ([§7.4](#control-thresholds)) that classify *prevalent* patients into control tiers.

### Diabetes Mellitus (Screening)

Screening category = `max(FBS_category, A1C_category)`. FBS auto-detects units by value range (< 30 = mmol/L, ≥ 30 = mg/dL).

| Category | FBS (mmol/L) | FBS (mg/dL) | HbA1c (%) |
|----------|:------------:|:-----------:|:---------:|
| Normal | ≤ 5.5 | ≤ 99 | < 5.7 |
| Elevated | 5.6 – 6.9 | 100 – 125 | 5.7 – 6.4 |
| Abnormal | > 6.9 | > 125 | > 6.4 |

### Hypertension (ACC/AHA 2017)

SYS and DIA must be **paired from the same visit**. Classification = worst of SYS or DIA.

| Category | Systolic (mmHg) | Diastolic (mmHg) |
|----------|:---------------:|:----------------:|
| Normal | < 120 **and** < 80 |
| Elevated | 120 – 129 **or** 80 – 89 |
| Abnormal | ≥ 130 **or** ≥ 90 |

### Dyslipidemia

Screening category = `max(HDL, Triglyceride, Cholesterol, LDL)`.

**HDL** (gender-specific; no "elevated" tier):

| Gender | Normal | Abnormal |
|--------|:------:|:--------:|
| Male | ≥ 40 | < 40 |
| Female | ≥ 50 | < 50 |

**Triglyceride, Cholesterol, LDL**:

| Marker | Normal | Elevated | Abnormal |
|--------|:------:|:--------:|:--------:|
| Triglyceride | < 150 | 150 – 199 | ≥ 200 |
| Total Cholesterol | < 200 | 200 – 239 | ≥ 240 |
| LDL | < 130 | 130 – 159 | ≥ 160 |

### Obesity (WHO BMI)

| Category | BMI (kg/m²) |
|----------|:-----------:|
| Underweight | < 18.5 |
| Normal | 18.5 – 24.9 |
| Elevated (Overweight) | 25.0 – 29.9 |
| Abnormal (Obese) | ≥ 30.0 |

BMI values < 10 or > 80 are excluded as clinically implausible (likely data entry errors).

---

## Module 1: Epidemiological Surveillance

Module 1 answers: *How much disease exists in the population, how fast is it appearing, and are we screening effectively?* Three reports derive from the **at-risk** cohort (§3.2), using **screening thresholds** (§5).

### Report 1 — Screening (Monthly Coverage)

#### Epidemiological Question

*What proportion of the at-risk population received screening for the condition each month?*

#### Measure Type

**Monthly screening coverage rate** — a process measure reflecting healthcare system reach.

#### Formula

$$\text{Screening Rate}_{M} = \frac{\text{Patients screened during month } M}{\text{Patients at-risk at start of month } M} \times 100$$

#### Numerator

A patient is counted as **screened** in month *M* if:

1. They are at-risk at the start of month *M* (`is_at_risk_start = TRUE`), **and**
2. They had the required screening test(s) recorded during month *M*.

| Condition | Required Test(s) | Logic |
|-----------|------------------|-------|
| DM | Fasting Blood Sugar (FBS) **or** HbA1c | Either test counts |
| HTN | Systolic BP **and** Diastolic BP (same visit) | Both must be present |
| DLP | HDL **or** LDL | Either lipid component counts |
| OB | BMI | Single measurement |

#### Denominator

The at-risk population at the start of month *M*.

#### Stratification by Result Category

Screened patients are classified by their **worst** result (the most clinically concerning marker determines the category) using the screening thresholds in §5:

| Category | Clinical Meaning |
|----------|------------------|
| Normal | All markers within normal range |
| Elevated | ≥ 1 marker in borderline range, none abnormal |
| Abnormal | ≥ 1 marker in disease-indicating range |

For Obesity, a fourth category exists: **Underweight** (BMI < 18.5).

#### Interpretation Guide

- **High screening rate + low abnormal rate**: Effective prevention; population is healthy.
- **High screening rate + high abnormal rate**: Good detection; high undiagnosed burden exists.
- **Low screening rate**: Insufficient healthcare reach; disease burden is unknown.
- **Zero screening**: No data; the at-risk population's status is unknown.

#### Annual Cumulative Rate (Subtotal Rows)

$$\text{Cumulative Screening Rate}_{\text{annual}} = \frac{\sum_{m=1}^{12} \text{Screened}_m}{\sum_{m=1}^{12} \text{At-Risk}_m} \times 100$$

This is a **person-month rate**: a patient screened in 3 different months contributes 3 to the numerator and 3 person-months to the denominator. It measures screening *encounters*, not unique patients screened per year.

### Report 2 — Prevalence (Annual Point Prevalence)

#### Epidemiological Question

*What proportion of the total eligible population had the condition at the end of the report year?*

#### Measure Type

**Point prevalence** — a cross-sectional snapshot as of December 31.

#### Formula

$$\text{Prevalence}_{\text{annual}} = \frac{\text{Patients with target ICD-10 code at Dec 31}}{\text{Total eligible population at Jan 1}} \times 100$$

#### Numerator

A patient is counted as **prevalent** if they have the target ICD-10 code with a diagnosis date ≤ December 31 of the report year.

#### Denominator

The total eligible population at January 1. This denominator is **fixed** for the year.

> **Why use the fixed denominator?** Point prevalence is a cross-sectional measure. The January 1 population represents the community at the start of the observation period. Removing patients who die during the year would underestimate prevalence.

#### Sub-Components

$$\text{Prevalent} = \text{Pre-existing} + \text{Incident During Year}$$

| Component | Definition | Clinical Meaning |
|-----------|------------|------------------|
| Pre-existing | First diagnosis **before** Jan 1 | Known cases; already under management |
| Incident during year | First diagnosis **during** report year | Newly detected cases |

#### Interpretation

- Rising prevalence over years may indicate improved detection, increasing disease burden, or both.
- A high ratio of pre-existing to incident cases suggests a mature detection program.
- A high ratio of incident to pre-existing cases suggests either a recent screening push or genuinely increasing disease incidence.

### Report 3 — Incidence (Monthly Incidence Rate)

#### Epidemiological Question

*At what rate are new cases of the condition developing in the at-risk population?*

#### Measure Type

**Monthly cumulative incidence proportion** and **annualized incidence rate** (using January baseline).

#### Monthly Formula

$$\text{Incidence Rate}_{M} = \frac{\text{New cases diagnosed during month } M}{\text{Patients at-risk at start of month } M} \times 100{,}000$$

#### Incident Case Definition

A patient is an **incident case** in month *M* if **all** of the following are true:

1. They are at-risk at the start of month *M* (no prior diagnosis of the target condition).
2. They received the **first-ever** target ICD-10 code during month *M*.
3. The diagnosis date falls within the calendar boundaries of month *M*.

A patient can be incident **only once**. After their first diagnosis, they are removed from the at-risk pool for all subsequent months.

#### Why Per 100,000?

Incidence rates are expressed per 100,000 population to produce readable numbers. Monthly incidence of chronic diseases is typically low (a few cases per thousand per month), so per-100,000 scaling avoids small decimals.

#### Annual Incidence Rate (Subtotal Rows)

$$\text{Annual Incidence Rate} = \frac{\sum_{m=1}^{12} \text{Incident Cases}_m}{\text{At-Risk Population at January}} \times 100{,}000$$

> **Why January as denominator?** Using a fixed baseline (the population at risk on January 1) provides a stable denominator for comparison across clusters and years. Summing monthly denominators would make later months' cases appear more concentrated as the at-risk pool shrinks. The January baseline answers: *Of the population at risk on January 1, how many developed the condition during the year?*

### Monthly vs. Annual Rate Calculations

| Aspect | Monthly Rate | Annual Rate (Subtotal/Grand Total) |
|--------|--------------|-------------------------------------|
| **Denominator** | At-risk at month start (varies each month) | January at-risk (fixed baseline) |
| **Numerator** | Cases/events in that specific month | Sum of all monthly cases/events |
| **Interpretation** | "This month, X per 100,000 at-risk developed the condition" | "Of those at risk on Jan 1, X per 100,000 developed the condition during the year" |
| **Use case** | Monitoring month-to-month variation, seasonal patterns | Comparing across clusters, facilities, or years |

#### Worked Example

Using the DM simulation data:

| Month | At-Risk Start | New Cases | Monthly Rate (per 100k) |
|-------|:-------------:|:---------:|:-----------------------:|
| Jan | 13 | 0 | 0 |
| Feb | 13 | 1 | 7,692 |
| Mar | 12 | 1 | 8,333 |
| Jun | 11 | 1 | 9,091 |
| Dec | 10 | 1 | 10,000 |
| **Annual** | **13 (Jan)** | **4 (total)** | **30,769** |

The monthly rate rises across the year (0 → 10,000) even with a constant 1 case/month because the denominator shrinks. The annual rate (30,769 per 100k) uses the fixed January denominator of 13 to provide a single, comparable number.

### Health Cluster Stratification

#### Rationale

Health clusters represent organizational units (geographic regions, facility catchments, or care networks). Stratifying epidemiological measures by cluster answers:

- Are some clusters screening more effectively than others?
- Is disease burden concentrated in specific clusters?
- Are new cases appearing at different rates across clusters?
- Which clusters have patients with no PHC assignment?

Cluster stratification is applied identically in Module 2 (Reports 4–6); see [§7](#module-2-compliance--care-gap) for report-specific rate forms.

#### Method

Health cluster is a **patient-level attribute** from `NMR.LEANHIS.PHC_ASSIGNMENT`. It is attached at the cohort level and flows through to all reports:

$$\text{Metric}_{\text{cluster}} = \frac{\text{Numerator}_{\text{cluster}}}{\text{Denominator}_{\text{cluster}}} \times \text{Scaling Factor}$$

Each cluster's rate is calculated independently using that cluster's own numerator and denominator. The grand total row sums across all clusters.

#### Unassigned Patients

Patients with no PHC record are labeled `'Unassigned'` and reported as a separate group. This is methodologically important: if unassigned patients have systematically different screening rates or disease burden, it may indicate a data quality issue or a genuinely underserved population.

---

## Module 2: Compliance & Care Gap

Module 2 answers: *Of those with disease, how well are we managing them and closing follow-up gaps?* Three reports derive from the **prevalent** cohort ([§3.1](#prevalent-cohort)), using **control thresholds** ([§7.4](#control-thresholds)).

### Module 2 Preamble

#### Base Population

The base population for all Module 2 reports is the **prevalent cohort at the reference date**, as defined in [§3.1](#prevalent-cohort). Unlike Module 1's at-risk pool, no further exclusion is applied for incident cases within the report year — any patient diagnosed at any time before the reference date is included.

#### Reference Date

- For **Report 4** (Control Level) and **Report 6** (Care Gap Annual): the prevalent cohort is evaluated as of the end of the report year (December 31). This matches the point-prevalence reference date used by Report 2.
- For **Report 5** (Care Gap Quarterly): the prevalent cohort is evaluated at the start of each quarter, so quarters-completed counts include all patients diagnosed before that quarter began.

#### Configuration

All control thresholds and the quarterly target are stored in dedicated config tables — `CHI_REPORTING.chi_control_thresholds` and `CHI_REPORTING.chi_care_gap_config` — rather than hardcoded in views. Updating thresholds does not require view re-creation; only the config tables are updated.

#### Condition-Specific Follow-Up Markers

Each condition defines a marker that indicates a meaningful follow-up visit:

| Condition | Completed if patient had ... |
|-----------|-----------------------------|
| DM | ≥ 1 HbA1c measurement that quarter |
| HTN | ≥ 1 visit with paired SYS **and** DIA that quarter |
| DLP | ≥ 1 lipid panel component (HDL/LDL/CHOL/TRIG) that quarter |
| OB | ≥ 1 BMI measurement that quarter |

### Report 4 — Control Level (Annual)

#### Epidemiological Question

*Of patients diagnosed with the condition, what proportion have their disease under control based on the most recent monitoring marker?*

#### Measure Type

**Annual disease control classification** — an outcome proxy reflecting adequacy of disease management.

#### Base Population

**Prevalent cohort as of December 31** ([§3.1](#prevalent-cohort)). Each prevalent patient contributes one row.

#### Formula — Patient-Level Classification

For each prevalent patient, the most recent monitoring marker value(s) within the report year are extracted and classified against the control thresholds ([§7.4](#control-thresholds)):

$$\text{level\_order}_{\text{patient}} = \max_{m \in \text{markers}} \left( \text{level\_order}( \text{value}_{m}, \text{thresholds}_{m} ) \right)$$

- **DM**: single marker (A1C) — `level_order = level_order(A1C)`
- **HTN**: two markers (SYS, DIA) from the most recent paired visit — `max(SYS_level, DIA_level)`
- **DLP**: four markers (HDL, LDL, CHol, Trig) — `max(HDL_level, LDL_level, CHol_level, Trig_level)`
- **OB**: single marker (BMI) — `level_order = level_order(BMI)`

`level_order = 0` is best (controlled); higher values indicate worsening control. The control *label* (the human-readable tier name) is looked up from the threshold row that matched the patient's value.

#### Report-Level Formula

$$\text{Pct}_{\text{level}, \text{cluster}} = \frac{\text{Prevalent patients in control level (cluster)}}{\text{Prevalent patients (cluster)}} \times 100$$

The aggregated report groups prevalent patients by `health_cluster` × `control_level`, with cluster subtotals and a grand total row.

#### Stratification by Marker Set

| Condition | Markers | Aggregation |
|-----------|---------|-------------|
| DM | A1C only | Single-marker classification |
| HTN | SYS + DIA (paired) | `max` of two marker levels |
| DLP | HDL, LDL, CHol, Trig | `max` of four marker levels |
| OB | BMI only | Single-marker classification |

HDL has gender-specific control thresholds (Male: ≥ 40 controlled; Female: ≥ 50 controlled) and is inverted — lower HDL = worse control.

#### Not Monitored

Prevalent patients with no measurement of the relevant marker during the report year are classified as **Not Monitored**. This category is reported explicitly and is distinct from any controlled or uncontrolled tier. It is informative on its own: a high Not-Monitored proportion signals a follow-up process failure independent of disease control.

#### Interpretation Guide

- **High "Controlled" %**: Effective disease management across the cluster's prevalent population.
- **High "Uncontrolled" %**: Treatment intensification is needed; consider outreach to specific clusters or populations.
- **High "Not Monitored" %**: Patients are diagnosed but not receiving guideline-recommended follow-up labs/visits. This is itself a care-gap signal and feeds into Reports 5–6.
- **Worst-level distribution**: Compare across clusters to identify where the most severely uncontrolled patients are concentrated.

### Report 5 — Care Gap (Quarterly)

#### Epidemiological Question

*In each quarter of the report year, what proportion of prevalent patients completed a guideline-recommended follow-up visit with the relevant lab?*

#### Measure Type

**Quarterly care-gap completion rate** — a process measure reflecting continuity of care for diagnosed patients.

#### Base Population

**Prevalent cohort as of the start of each quarter** ([§3.1](#prevalent-cohort)). The denominator is re-evaluated at each quarter boundary so that patients diagnosed mid-year enter the denominator in the quarter following their diagnosis.

#### Quarterly Definitions

| Quarter | Months | Reporting |
|---------|--------|-----------|
| Q1 | January – March | Months 1–3 |
| Q2 | April – June | Months 4–6 |
| Q3 | July – September | Months 7–9 |
| Q4 | October – December | Months 10–12 |

A quarter is **completed** for a patient if the patient had ≥ 1 follow-up marker in any month of that quarter (see condition-specific criteria in [§7.0](#module-2-preamble)).

#### Formula

$$\text{Completion Rate}_{Q, \text{cluster}} = \frac{\text{Prevalent patients completing follow-up in quarter } Q \text{ (cluster)}}{\text{Prevalent patients at start of quarter } Q \text{ (cluster)}} \times 100$$

#### Complementary Gap Rate

The inverse metric is also reported directly:

$$\text{Gap Rate}_{Q, \text{cluster}} = 100\% - \text{Completion Rate}_{Q, \text{cluster}}$$

#### Interpretation Guide

- **Declining completion across quarters**: Patients who completed follow-up early in the year are dropping off by year-end — investigate clinic accessibility, scheduling, or reminder systems.
- **Uniformly low completion**: Systemic care-coordination failure; consider population-level outreach.
- **Cluster-level variation**: Identifies which facilities are performing well vs. under-performing on continuity-of-care for diagnosed patients.

### Report 6 — Care Gap (Annual)

#### Epidemiological Question

*Across the four quarters of the report year, how many prevalent patients completed follow-up in 0, 1, 2, 3, or all 4 quarters — and what proportion met the recommended target?*

#### Measure Type

**Annual care-gap distribution** — an outcome-oriented summary of follow-up continuity across the year.

#### Base Population

**Prevalent cohort as of December 31** ([§3.1](#prevalent-cohort)). All prevalent patients are counted, regardless of when they were diagnosed.

#### Formula

For each prevalent patient, count the number of quarters in which they completed follow-up:

$$\text{quarters\_completed}_{\text{patient}} = \sum_{Q=1}^{4} \mathbb{1}[\text{patient completed follow-up in quarter } Q]$$

Patients are then binned by `quarters_completed ∈ {0, 1, 2, 3, 4}`. The aggregated report shows the count and percentage of prevalent patients in each bin, stratified by `health_cluster`.

#### Meeting Target

The target is configured in `chi_care_gap_config.target_quarters_completed` (default: 3). Patients are flagged:

$$\text{meets\_target}_{\text{patient}} = \mathbb{1}[\text{quarters\_completed}_{\text{patient}} \geq \text{target\_quarters\_completed}]$$

The aggregated report includes a `≥ Target` summary row per cluster, plus a grand-total row across all clusters:

$$\text{Pct Meeting Target}_{\text{cluster}} = \frac{\text{Prevalent patients meeting target (cluster)}}{\text{Prevalent patients (cluster)}} \times 100$$

#### Interpretation Guide

- **Most patients in 0–1 quarters**: Severe follow-up failure; the prevalent cohort is not receiving guideline-recommended care.
- **Bimodal distribution (0 and 4 quarters)**: Patients are either fully engaged or completely lost to follow-up; consider targeted outreach to the 0-quarter group.
- **Bell-shaped around 2 quarters**: Patients receive intermittent but not guideline-concordant care; consider structured recall systems.
- **Most patients at or above target**: Effective continuity of care for the prevalent population.

### Control Thresholds

Control thresholds classify **prevalent** patients (Module 2 base population) into a controlled tier plus one or more uncontrolled tiers based on their most recent monitoring marker value. These are stored in the `CHI_REPORTING.chi_control_thresholds` config table and are distinct from the screening thresholds in [§5](#screening-thresholds) (which classify at-risk patients for case-finding).

#### Threshold Schema

Each row of `chi_control_thresholds` defines one (condition, marker, gender, level) tuple with inclusive lower bound `min_value` and exclusive upper bound `max_value`:

| condition | marker | gender | min | max | order | label |
|-----------|--------|--------|:---:|:---:|:-----:|-------|
| `dm` | `a1c` | `All` | `NULL` | 7.0 | 0 | `Controlled (A1C < 7.0%)` |
| `dm` | `a1c` | `All` | 7.0 | 8.0 | 1 | `Uncontrolled (A1C 7.0–7.9%)` |
| … | … | … | … | … | … | … |

A patient's marker value is matched against the row whose `[min, max)` range contains it. `level_order` is the sort key: 0 = best (controlled); higher values are worse. The `label` is the human-readable tier name shown in reports.

#### Default Thresholds by Condition

**DM (A1C only)**:

| Order | Label | Range (%) |
|:-----:|-------|:---------:|
| 0 | Controlled | < 7.0 |
| 1 | Uncontrolled | 7.0 – 7.9 |
| 2 | Uncontrolled | 8.0 – 8.9 |
| 3 | Uncontrolled | ≥ 9.0 |

**HTN (SYS + DIA, paired)**:

| Marker | Order | Label | Range |
|--------|:-----:|-------|-------|
| SYS | 0 | Controlled | < 130 mmHg |
| SYS | 1 | Uncontrolled | 130 – 139 |
| SYS | 2 | Uncontrolled | 140 – 159 |
| SYS | 3 | Uncontrolled | ≥ 160 |
| DIA | 0 | Controlled | < 80 mmHg |
| DIA | 1 | Uncontrolled | 80 – 89 |
| DIA | 2 | Uncontrolled | 90 – 99 |
| DIA | 3 | Uncontrolled | ≥ 100 |

**DLP (HDL, LDL, CHol, Trig — `max` of 4)**:

| Marker | Gender | Order | Label | Range (mg/dL) |
|--------|--------|:-----:|-------|:-------------:|
| LDL | All | 0 | Controlled | < 100 |
| LDL | All | 1 | Uncontrolled | 100 – 129 |
| LDL | All | 2 | Uncontrolled | 130 – 159 |
| LDL | All | 3 | Uncontrolled | ≥ 160 |
| CHol | All | 0 | Controlled | < 200 |
| CHol | All | 1 | Uncontrolled | 200 – 239 |
| CHol | All | 2 | Uncontrolled | 240 – 279 |
| CHol | All | 3 | Uncontrolled | ≥ 280 |
| Trig | All | 0 | Controlled | < 150 |
| Trig | All | 1 | Uncontrolled | 150 – 199 |
| Trig | All | 2 | Uncontrolled | 200 – 499 |
| Trig | All | 3 | Uncontrolled | ≥ 500 |
| HDL | Male | 0 | Controlled | ≥ 40 |
| HDL | Male | 1 | Uncontrolled | < 40 |
| HDL | Female | 0 | Controlled | ≥ 50 |
| HDL | Female | 1 | Uncontrolled | < 50 |

**OB (BMI only, WHO)**:

| Order | Label | Range (kg/m²) |
|:-----:|-------|:-------------:|
| 0 | Controlled | 18.5 – 24.9 |
| 1 | Uncontrolled | 25.0 – 29.9 |
| 2 | Uncontrolled | 30.0 – 34.9 |
| 3 | Uncontrolled | ≥ 35.0 |

### Quarterly Definitions & Follow-Up Criteria

The care-gap module partitions the report year into four calendar quarters and applies a condition-specific "completed follow-up" criterion per quarter. Both pieces are shared across Reports 5 and 6.

#### Quarter Boundaries

See Report 5 ([§7.2](#report-5---care-gap-quarterly)) for the quarter-month mapping. Q1 = months 1–3, Q2 = 4–6, Q3 = 7–9, Q4 = 10–12. Boundaries align with calendar quarters.

#### Follow-Up "Completed" Criteria

A quarter is marked **completed** for a prevalent patient if any of the condition's follow-up markers was recorded in any month of that quarter:

| Condition | Completed if patient had ... | Source table(s) |
|-----------|------------------------------|-----------------|
| DM | ≥ 1 HbA1c measurement that quarter | LAB + OBS |
| HTN | ≥ 1 visit with paired SYS **and** DIA | OBS only |
| DLP | ≥ 1 lipid panel component (HDL/LDL/CHOL/TRIG) | LAB + OBS |
| OB | ≥ 1 BMI measurement that quarter | OBS only |

> **Why HTN requires a paired visit.** Screening classification already requires SYS+DIA to be from the same visit ([§5.2](#hypertension-accaha-2017)) for clinical validity. The same constraint is carried into care-gap completion: a patient with only SYS or only DIA recorded that quarter is not counted as having completed follow-up.

#### Target Configuration

The quarterly target (default: 3 quarters) is stored in `chi_care_gap_config.target_quarters_completed` and is read by Report 6 via `CROSS JOIN`. Changing the target does not require view re-creation.

---

## Assumptions & Limitations

### Shared Assumptions (Module 1 & Module 2)

1. **Complete diagnosis capture**. It is assumed that all diagnoses are recorded in the EMR with accurate ICD-10 codes and dates. Undiagnosed patients are misclassified as at-risk (Module 1) or non-prevalent (Module 2).
2. **Lab result accuracy**. Both screening classifications (Module 1) and control classifications (Module 2) assume lab/observation values are correctly recorded. Transcription errors may cause misclassification. The DM dual-unit auto-detection mitigates but does not eliminate this.
3. **PHC assignment completeness**. Patients without a PHC record are assumed to be genuinely unassigned, not the result of a data integration gap.
4. **Visit-date alignment**. Lab results and observations are attributed to the month of the associated patient visit, not the date the result was entered or verified.
5. **No loss to follow-up**. Patients who leave the catchment area but have no death record are assumed to remain in the population. This may overstate the denominator for both modules.

### Module 1 Assumptions & Limitations

1. **Screening ≠ diagnosis**. A patient with an abnormal screening result does not necessarily have the disease. The screening report measures test coverage and results, not confirmed diagnoses.
2. **First diagnosis ≠ disease onset**. The incidence measure captures the date a diagnosis was *recorded*, not the date the disease *developed*. A patient diagnosed with E11 in June may have had undiagnosed diabetes for years.
3. **Screening encounter double-counting**. The annual cumulative screening rate counts screening *events*, not unique patients. A patient screened every month contributes 12 to the numerator. This metric measures testing volume, not the proportion of the population ever screened.
4. **Denominator stability in small clusters**. For small health clusters, a single incident case can produce a very high rate (e.g., 1 case / 2 at-risk = 50,000 per 100k). Rates for clusters with < 5 at-risk patients should be interpreted with caution.
5. **ICD-10 coding variability**. Different clinicians may code the same condition differently. A patient with Type 2 diabetes coded as E14 (unspecified DM) would be counted in the prevalent cohort for screening/incidence exclusion but not in the E11-specific prevalence numerator.
6. **Cross-sectional prevalence denominator**. The prevalence denominator is fixed at January 1. Patients who turn 18, receive a National ID, or immigrate into the catchment during the year are not captured.

### Module 2 Assumptions & Limitations

1. **Control thresholds are treatment targets, not physiological norms**. The default A1C target (< 7.0%), BP target (< 130 / < 80), and lipid targets reflect guideline-recommended treatment goals for the general diabetic / hypertensive / dyslipidemic population. Individualized targets may differ (e.g., tighter control for some patients, more relaxed for frail elderly). The report applies a uniform threshold across all prevalent patients; clinical interpretation should account for individual variation.
2. **"Completed" is a process proxy, not an outcome**. Report 5 measures whether a lab/visit was *recorded*, not whether the patient's disease is *well managed*. A patient with quarterly HbA1c measurements all above 9.0% is counted as having completed follow-up each quarter — but is severely uncontrolled. Combine Report 4 (control level) and Report 5 (completion) for a complete picture.
3. **Mid-year diagnoses contribute partial-year data**. A patient diagnosed in October contributes to the prevalent cohort as of December 31 (Report 4 and Report 6 denominators) and to Report 5 from Q4 onward only. They have 1 quarter to complete follow-up, making them structurally unable to meet a target of 3 quarters. Report 6's annual distribution should be interpreted with awareness of the incident case mix.
4. **"Not Monitored" conflates care gaps and data gaps**. A prevalent patient with no measurement during the year may genuinely be lost to follow-up (a care-gap signal) or may have measurements recorded in systems not captured by the EMR (a data-coverage issue). Report 5's per-quarter completion rate is the primary mechanism to distinguish these.
5. **Multi-marker aggregation masks individual marker issues**. For HTN (SYS+DIA) and DLP (4 markers), the overall control level is the `max` across markers. A patient with controlled LDL but severely uncontrolled HDL is reported at the worst marker's level only — the underlying multi-marker profile is not visible in the aggregated report.
6. **HDL gender-specific thresholds assume recorded gender is correct**. Patients with miscoded or missing gender inherit Male thresholds by default. Gender-specific reports should be cross-checked against the cohort view's gender distribution.
7. **Quarterly boundaries align with calendar quarters, not patient-level follow-up windows**. Q1 = Jan–Mar is a calendar convention. A patient diagnosed on March 15 has only 16 days to complete Q1 follow-up before the quarter ends; the report does not normalize for time-in-quarter.

---

## Reference: Formula Index

| Module | Report | Detail Row Formula | Subtotal / Grand Total Formula |
|:------:|--------|--------------------|--------------------------------|
| **M1** | Screening | $\frac{\text{Screened}_m}{\text{At-Risk}_m} \times 100$ | $\frac{\sum\text{Screened}_m}{\sum\text{At-Risk}_m} \times 100$ (cumulative) |
| **M1** | Prevalence | — (annual only) | $\frac{\text{Prevalent}_{\text{Dec 31}}}{\text{Total Pop}_{\text{Jan 1}}} \times 100$ |
| **M1** | Incidence | $\frac{\text{New Cases}_m}{\text{At-Risk}_m} \times 100{,}000$ | $\frac{\sum\text{New Cases}_m}{\text{At-Risk}_{\text{Jan}}} \times 100{,}000$ (annualized) |
| **M2** | Control | $\frac{\text{Pts in level}_{c}}{\text{Prevalent}_{c}} \times 100$ | $\frac{\sum\text{Pts in level}}{\sum\text{Prevalent}} \times 100$ |
| **M2** | Care Gap Q | $\frac{\text{Completed}_Q}{\text{Prevalent}_Q} \times 100$ | $\frac{\sum\text{Completed}_Q}{\sum\text{Prevalent}_Q} \times 100$ |
| **M2** | Care Gap Annual | $\frac{\text{Pts in bin}}{\text{Prevalent}} \times 100$ | Bins + `≥ Target` row per cluster |

Where *m* = month (1–12), *c* = cluster, *Q* = quarter (1–4), "bin" = {0, 1, 2, 3, 4} quarters completed.