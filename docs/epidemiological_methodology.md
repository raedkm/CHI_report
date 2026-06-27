# Epidemiological Methodology — CHI Report Views

## Table of Contents

1. [Study Design](#study-design)
2. [Population Eligibility](#population-eligibility)
3. [Cohort Definitions](#cohort-definitions)
4. [The At-Risk Population](#the-at-risk-population)
5. [Report 1: Screening (Monthly Coverage)](#report-1-screening-monthly-coverage)
6. [Report 2: Prevalence (Annual Point Prevalence)](#report-2-prevalence-annual-point-prevalence)
7. [Report 3: Incidence (Monthly Incidence Rate)](#report-3-incidence-monthly-incidence-rate)
8. [Monthly vs. Annual Rate Calculations](#monthly-vs-annual-rate-calculations)
9. [Health Cluster Stratification](#health-cluster-stratification)
10. [Condition-Specific Clinical Thresholds](#condition-specific-clinical-thresholds)
11. [Assumptions & Limitations](#assumptions--limitations)

---

## Study Design

**Design type**: Retrospective cohort study using electronic medical record (EMR) data.

**Observation period**: One calendar year (January 1 – December 31), configurable via `CHI_REPORTING.chi_config`.

**Unit of analysis**: The patient-month. Each eligible patient contributes up to 12 monthly observations. The patient-month is the analytical grain from which all three epidemiological measures are derived.

**Data source**: `NMR.LEANHIS` EMR schema (Snowflake). Raw tables include demographics (`PATIENTS`), encounters (`PATIENTVISITS`), laboratory results (`LABRESULTS` / `LABRESULTS_RESULTVALUES`), clinical observations (`OBSERVATIONS` / `OBSERVATIONS_OBSERVATIONVALUES`), and diagnoses (`DIAGNOSIS_CODES`).

---

## Population Eligibility

A patient is included in the **total population** for report year *Y* if they meet **all** of the following criteria at January 1 of year *Y*:

| Criterion | Definition | Rationale |
|-----------|-----------|-----------|
| **Age** | > 18 years at January 1 | Adult population only; pediatric thresholds differ for most conditions |
| **National ID** | Present and non-empty in the EMR | Ensures patient identity is verified; excludes transient/tourist encounters |
| **Vital status** | Alive at January 1 (no death record before report start) | Deceased patients cannot contribute person-time during the report year |

Patients who meet all three criteria are flagged `is_in_total_population = TRUE`. This flag is evaluated once per report year and does not change month-to-month — a patient who dies during the year remains in the denominator for that year's prevalence calculation.

---

## Cohort Definitions

From the total population, two mutually exclusive cohorts are derived based on diagnosis history:

```
TOTAL POPULATION (eligible at Jan 1)
│
├── PREVALENT COHORT
│   └── Has ≥1 diagnosis in the condition's ICD-10 code set
│       with a diagnosis date before the report year starts
│       → Excluded from at-risk pool
│       → Counted in prevalence numerator
│
└── AT-RISK COHORT
    └── No diagnosis in the condition's ICD-10 code set
        before the report year starts
        → Denominator for screening and incidence reports
        → Includes patients with abnormal labs but no formal diagnosis
```

### Prevalent Cohort

A patient is prevalent if they have **any** ICD-10 code in the condition's code set, regardless of whether it is the primary target code:

| Condition | ICD-10 Code Set | Target Code (used for incidence) |
|-----------|----------------|----------------------------------|
| DM | E10, E11, E13, E14, O24 | E11 |
| HTN | I10, I11, I12, I13, I15 | I10 |
| DLP | E78 | E78 |
| OB | E66 | E66 |

> **Why the distinction?** DM is the clearest example: a patient with Type 1 (E10) or gestational diabetes (O24) is already a known diabetic — screening them for DM makes no clinical sense. But incidence tracking focuses specifically on Type 2 (E11) because it is the preventable/lifestyle-related form that public health programs target.

### At-Risk Cohort

```
AT-RISK = TOTAL POPULATION − PREVALENT COHORT
```

The at-risk cohort includes:
- Patients with **no diagnosis** in the condition's code set before the report year
- Patients with **prediabetes** or abnormal screening results who lack a formal ICD-10 diagnosis
- Patients who have never been screened

### Dynamic Cohort Membership

Cohort assignment is **not static** across the year. The at-risk pool shrinks month-by-month as patients receive their first diagnosis and transition to the prevalent cohort.

```
                  ┌── Incident in Mar → leaves at-risk pool for Apr─Dec
                  │
Jan ─── Feb ─── Mar ─── Apr ─── May ─── Jun ─── Jul ─── Aug ─── Sep ─── Oct ─── Nov ─── Dec
  │                                                               
  └── At-risk at Jan 1: 13 patients
       At-risk at Dec 1: 10 patients (3 became incident during the year)
```

This is why the staging system evaluates `is_at_risk_start` at **each month boundary** — not once at the start of the year. A patient diagnosed in March is at-risk for January, February, and March (inclusive of the month of first diagnosis for screening), but is removed from the at-risk denominator for April through December.

---

## The At-Risk Population

### Definition

```
is_at_risk_start(month M) = TRUE if:
    patient is in TOTAL POPULATION
    AND patient has NO diagnosis in the condition's ICD-10 code set
        with a diagnosis date < first day of month M
```

### Monthly Evaluation

For each patient-month, the analytical view (`stg_{cond}_patient_month`) checks:

```sql
has_dx_before_month = (first_diagnosis_date IS NOT NULL
                       AND first_diagnosis_date < first_day_of_month)

is_at_risk_start = (NOT has_dx_before_month)
```

### Why Monthly?

Three epidemiological reasons:

1. **Accurate denominators**: The at-risk population is the denominator for both screening and incidence rates. Using a fixed year-start denominator would overstate the population at risk in later months (patients who developed the condition during the year are no longer at risk).

2. **Censoring at diagnosis**: A patient can only be an incident case once. After their first diagnosis, they leave the at-risk pool. The monthly evaluation correctly censors them from subsequent months' denominators.

3. **Time-varying exposure**: Screening behavior changes when patients know they have a condition. A patient diagnosed in March should not be counted as "at-risk but unscreened" in November — they're already under management.

---

## Report 1: Screening (Monthly Coverage)

### Epidemiological Question

> *What proportion of the at-risk population received screening for the condition each month?*

### Measure Type

**Monthly screening coverage rate** — a process measure reflecting healthcare system reach.

### Formula

$$\text{Screening Rate}_{\text{month}} = \frac{\text{Patients screened during month}}{\text{Patients at-risk at month start}} \times 100$$

### Numerator

A patient is counted as **screened** in month *M* if:

1. They are at-risk at the start of month *M* (`is_at_risk_start = TRUE`), **AND**
2. They had the required screening test(s) recorded during month *M*

Screening requirements vary by condition:

| Condition | Required Test(s) | Logic |
|-----------|-----------------|-------|
| DM | Fasting Blood Sugar (FBS) **or** HbA1c | Either test counts |
| HTN | Systolic BP **and** Diastolic BP from the **same visit** | Both must be present |
| DLP | HDL **or** LDL | Either lipid component counts |
| OB | BMI | Single measurement |

### Denominator

The at-risk population at the start of month *M* — patients who have not been diagnosed with the condition before month *M* begins.

### Stratification

Screened patients are further classified by their **worst** result:

| Category | Clinical Meaning |
|----------|-----------------|
| **Normal** | All markers within normal range |
| **Elevated** | At least one marker in borderline/prediabetic range, none abnormal |
| **Abnormal** | At least one marker in disease-indicating range |

For Obesity, a fourth category exists: **Underweight** (BMI < 18.5).

### Interpretation

- High screening rate + low abnormal rate → effective prevention, population is healthy
- High screening rate + high abnormal rate → good detection, high undiagnosed burden
- Low screening rate → insufficient healthcare reach, unknown disease burden
- Zero screening → no data; the at-risk population's status is unknown

### Annual Cumulative Rate (Subtotal Rows)

The cluster subtotal and grand total rows report a cumulative measure:

$$\text{Cumulative Screening Rate}_{\text{annual}} = \frac{\sum_{m=1}^{12} \text{Screened}_m}{\sum_{m=1}^{12} \text{At-Risk}_m} \times 100$$

This is a **person-month rate**: a patient screened in 3 different months contributes 3 to the numerator and 3 person-months to the denominator. It measures screening *encounters* per person-month of at-risk time, not unique patients screened per year.

---

## Report 2: Prevalence (Annual Point Prevalence)

### Epidemiological Question

> *What proportion of the total eligible population had the condition at the end of the report year?*

### Measure Type

**Point prevalence** — a snapshot as of December 31.

### Formula

$$\text{Prevalence}_{\text{annual}} = \frac{\text{Patients with target ICD-10 code at Dec 31}}{\text{Total eligible population at Jan 1}} \times 100$$

### Numerator

A patient is counted as **prevalent** if they have the **target ICD-10 code** diagnosed on or before December 31 of the report year:

- DM: E11 (Type 2 diabetes mellitus)
- HTN: I10 (Essential hypertension)
- DLP: E78 (Disorders of lipoprotein metabolism)
- OB: E66 (Overweight and obesity)

### Denominator

The total eligible population at January 1. This denominator is **fixed** for the year — patients who die or otherwise leave the cohort during the year are not removed.

> **Why use the Jan 1 denominator?** Point prevalence is a cross-sectional measure. The January 1 population represents the community at the start of the observation period. Removing patients who die during the year would underestimate prevalence (the denominator would exclude patients who contributed to disease burden for part of the year).

### Sub-Components

Prevalent cases are decomposed into:

| Component | Definition | Clinical Meaning |
|-----------|-----------|-----------------|
| **Pre-existing** | First diagnosis date **before** January 1 of the report year | Known cases — already under management |
| **Incident during year** | First diagnosis date **during** the report year | Newly detected cases — may represent true new disease or previously undiagnosed disease now captured |

$$\text{Prevalent} = \text{Pre-existing} + \text{Incident During Year}$$

### Interpretation

- Rising prevalence over years may indicate improved detection (more screening → more diagnosis), increasing disease burden, or both
- A high ratio of pre-existing to incident cases suggests a mature detection program
- A high ratio of incident to pre-existing cases suggests either a recent screening push or a genuinely increasing disease incidence

---

## Report 3: Incidence (Monthly Incidence Rate)

### Epidemiological Question

> *At what rate are new cases of the condition developing in the at-risk population?*

### Measure Type

**Monthly incidence rate** (cumulative incidence proportion per month) and **annualized incidence rate** (using January baseline).

### Monthly Formula

$$\text{Incidence Rate}_{\text{month}} = \frac{\text{New cases diagnosed during month}}{\text{Patients at-risk at month start}} \times 100{,}000$$

### Numerator — Incident Case Definition

A patient is an **incident case** in month *M* if **all** of the following are true:

1. They are at-risk at the start of month *M* (no prior diagnosis of the target condition)
2. They received the **first-ever** target ICD-10 code during month *M*
3. The diagnosis date falls within the calendar boundaries of month *M*

A patient can be incident **only once**. After their first diagnosis, they are removed from the at-risk pool for all subsequent months.

### Denominator

The at-risk population at the start of month *M*. This denominator **shrinks** across months as patients become incident cases and leave the at-risk pool.

### Why Per 100,000?

Incidence rates are expressed per 100,000 population to produce readable numbers. Monthly incidence of chronic diseases is typically low (a few cases per thousand per month), so per-100,000 scaling avoids small decimals.

### Interpretation

- **Monthly rate** reflects the intensity of new case detection in that specific month
- Seasonal patterns may emerge (e.g., higher detection in months with more clinic visits)
- A spike in a single month may indicate a screening campaign rather than a true disease outbreak
- Consistently rising monthly rates over years suggest increasing disease burden

### Annual Incidence Rate (Subtotal Rows)

The cluster subtotal and grand total rows report an annualized rate:

$$\text{Annual Incidence Rate} = \frac{\sum_{m=1}^{12} \text{Incident Cases}_m}{\text{At-Risk Population at January}} \times 100{,}000$$

**Why January at-risk as denominator?** Using a fixed baseline (the population at risk at the start of the year) provides a stable denominator for comparison across clusters and years. If we summed the monthly denominators, the shrinking at-risk pool would make later months' cases appear more "concentrated." The January baseline answers the question: *Of the population at risk on January 1, how many developed the condition during the year?*

---

## Monthly vs. Annual Rate Calculations

| Aspect | Monthly Rate | Annual Rate (Subtotal/Grand Total) |
|--------|-------------|-------------------------------------|
| **Denominator** | At-risk at month start (varies each month) | January at-risk (fixed baseline) |
| **Numerator** | Cases/events in that specific month | Sum of all monthly cases/events |
| **Interpretation** | "This month, X per 100,000 at-risk developed the condition" | "Of those at risk on Jan 1, X per 100,000 developed the condition during the year" |
| **Use case** | Monitoring month-to-month variation, seasonal patterns | Comparing across clusters, facilities, or years |

### Why Different Denominators?

The monthly rate uses the **current** at-risk pool because the epidemiological question is "what is happening right now?" The annual rate uses the **January** at-risk pool because the question is "over the whole year, what happened to the population that started at risk?"

A concrete illustration using the DM simulation data:

| Month | At-Risk Start | New Cases | Monthly Rate (per 100k) |
|-------|:---:|:---:|:---:|
| Jan | 13 | 0 | 0 |
| Feb | 13 | 1 | 7,692 |
| Mar | 12 | 1 | 8,333 |
| Jun | 11 | 1 | 9,091 |
| Dec | 10 | 1 | 10,000 |
| **Annual** | **13 (Jan)** | **4 (total)** | **30,769** |

The monthly rate rises across the year (0 → 10,000) even with a constant 1 case/month because the denominator shrinks. The annual rate (30,769 per 100k) uses the fixed January denominator of 13 to provide a single, comparable number.

---

## Health Cluster Stratification

### Rationale

Health clusters represent organizational units (geographic regions, facility catchments, or care networks). Stratifying epidemiological measures by cluster answers:

- Are some clusters screening more effectively than others?
- Is disease burden concentrated in specific clusters?
- Are new cases appearing at different rates across clusters?
- Which clusters have patients with no PHC assignment (the "Unassigned" group)?

### Method

Health cluster is a **patient-level attribute** from `NMR.LEANHIS.PHC_ASSIGNMENT`. It is attached at the cohort level and flows through to all reports:

$$\text{Metric}_{\text{cluster}} = \frac{\text{Numerator}_{\text{cluster}}}{\text{Denominator}_{\text{cluster}}} \times \text{Scaling Factor}$$

Each cluster's rate is calculated independently using that cluster's own numerator and denominator. The grand total row sums across all clusters.

### Unassigned Patients

Patients with no PHC record are labeled `'Unassigned'` and reported as a separate group. This is methodologically important: if unassigned patients have systematically different screening rates or disease burden, it may indicate a data quality issue or a genuinely underserved population.

---

## Condition-Specific Clinical Thresholds

### Diabetes Mellitus

Screening category = **worst** of FBS and HbA1c. FBS auto-detects units by value range.

| Category | FBS (mmol/L) | FBS (mg/dL) | HbA1c (%) |
|----------|-------------|------------|-----------|
| Normal | ≤ 5.5 | ≤ 99 | < 5.7 |
| Elevated | 5.6 – 6.9 | 100 – 125 | 5.7 – 6.4 |
| Abnormal | > 6.9 | > 125 | > 6.4 |

### Hypertension (ACC/AHA 2017)

SYS and DIA must be **paired from the same visit**. Classification = worst of SYS or DIA.

| Category | Systolic (mmHg) | Diastolic (mmHg) |
|----------|:---:|:---:|
| Normal | < 120 **and** < 80 |
| Elevated | 120 – 129 **or** 80 – 89 |
| Abnormal | ≥ 130 **or** ≥ 90 |

### Dyslipidemia

Screening category = **worst** of HDL, Triglyceride, Cholesterol, LDL.

**HDL** (gender-specific, no "elevated" tier):

| Gender | Normal | Abnormal |
|--------|:---:|:---:|
| Male | ≥ 40 | < 40 |
| Female | ≥ 50 | < 50 |

**Triglyceride, Cholesterol, LDL**:

| Marker | Normal | Elevated | Abnormal |
|--------|:---:|:---:|:---:|
| Triglyceride | < 150 | 150 – 199 | ≥ 200 |
| Total Cholesterol | < 200 | 200 – 239 | ≥ 240 |
| LDL | < 130 | 130 – 159 | ≥ 160 |

### Obesity (WHO BMI)

| Category | BMI (kg/m²) |
|----------|:---:|
| Underweight | < 18.5 |
| Normal | 18.5 – 24.9 |
| Elevated (Overweight) | 25.0 – 29.9 |
| Abnormal (Obese) | ≥ 30.0 |

BMI values < 10 or > 80 are excluded as clinically implausible (likely data entry errors).

---

## Assumptions & Limitations

### Assumptions

1. **Complete diagnosis capture**: It is assumed that all diagnoses are recorded in the EMR with accurate ICD-10 codes and dates. Undiagnosed patients are misclassified as at-risk.

2. **Lab result accuracy**: Screening classifications assume lab/observation values are correctly recorded. Transcription errors (e.g., mg/dL entered as mmol/L) may cause misclassification. The DM dual-unit auto-detection mitigates but does not eliminate this.

3. **PHC assignment completeness**: Patients without a PHC record are assumed to be genuinely unassigned, not the result of a data integration gap.

4. **Visit-date alignment**: Lab results and observations are attributed to the month of the associated patient visit (`PATIENTVISITS.STARTDATE`), not the date the result was entered or verified.

5. **No loss to follow-up**: Patients who leave the catchment area but have no death record are assumed to remain in the population. This may overstate the denominator.

### Limitations

1. **Screening ≠ diagnosis**: A patient with an abnormal screening result does not necessarily have the disease. The screening report measures test coverage and results, not confirmed diagnoses.

2. **First diagnosis ≠ disease onset**: The incidence measure captures the date a diagnosis was *recorded*, not the date the disease *developed*. A patient diagnosed with E11 in June may have had undiagnosed diabetes for years. Incidence rates therefore reflect detection as much as true disease occurrence.

3. **Screening encounter double-counting**: The annual cumulative screening rate counts screening *events*, not unique patients. A patient screened every month contributes 12 to the numerator. This metric is useful for measuring testing volume but does not reflect the proportion of the population ever screened during the year.

4. **Denominator stability in small clusters**: For small health clusters, a single incident case can produce a very high rate (e.g., 1 case / 2 at-risk = 50,000 per 100k). Rates for clusters with < 5 at-risk patients should be interpreted with caution.

5. **ICD-10 coding variability**: Different clinicians may code the same condition differently. A patient with Type 2 diabetes coded as E14 (unspecified DM) would be counted in the prevalent cohort for screening/incidence exclusion but not in the E11-specific prevalence numerator. This may cause the prevalence numerator to be smaller than expected relative to the at-risk denominator.

6. **Cross-sectional prevalence denominator**: The prevalence denominator is fixed at January 1. Patients who turn 18, receive a National ID, or immigrate into the catchment during the year are not captured.

---

## Reference

### Rate Formulas Summary

| Report | Detail Row Formula | Subtotal/Grand Total Formula |
|--------|-------------------|------------------------------|
| **Screening** | $\frac{\text{Screened}_m}{\text{At-Risk}_m} \times 100$ | $\frac{\sum\text{Screened}_m}{\sum\text{At-Risk}_m} \times 100$ (cumulative) |
| **Prevalence** | — (annual only) | $\frac{\text{Prevalent}_{\text{Dec 31}}}{\text{Total Pop}_{\text{Jan 1}}} \times 100$ |
| **Incidence** | $\frac{\text{New Cases}_m}{\text{At-Risk}_m} \times 100{,}000$ | $\frac{\sum\text{New Cases}_m}{\text{At-Risk}_{\text{Jan}}} \times 100{,}000$ (annualized) |

Where *m* = month (1–12).
