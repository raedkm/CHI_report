# Diabetes Mellitus (DM) — Conceptual Map & Report Logic

## Three Report Types

```
                    ┌──────────────────────────────────────────┐
                    │         TOTAL POPULATION                  │
                    │  Age >18, Alive at 01 Jan YYYY,          │
                    │  Has National ID                          │
                    └────────────────┬─────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
     ┌────────▼────────┐   ┌────────▼────────┐   ┌─────────▼────────┐
     │  WITH DIABETES   │   │  WITHOUT DIABETES│   │                  │
     │  (Prevalent)     │   │  (At-Risk Pool)  │   │   DECEASED /     │
     │                  │   │                  │   │   LEFT COHORT    │
     │  E10 (Type 1)    │   │  Prediabetes ✓   │   │                  │
     │  E11 (Type 2)    │   │  No DM history   │   │  (removed from   │
     │  E13 (Other)     │   │                  │   │   denominator)   │
     │  E14 (Unspec)    │   └────────┬─────────┘   │                  │
     │  O24 / GDM       │            │             └──────────────────┘
     └────────┬─────────┘            │
              │                      │
              │            ┌─────────▼─────────┐
              │            │     SCREENED       │
              │            │  (FBS or A1C done) │
              │            └─────────┬─────────┘
              │                      │
              │         ┌────────────┼────────────┐
              │         │            │            │
              │    ┌────▼────┐ ┌─────▼─────┐ ┌───▼──────┐
              │    │ Normal  │ │ Elevated  │ │ Abnormal │
              │    │         │ │(Prediabet)│ │(Diabetic)│
              │    └─────────┘ └───────────┘ └───┬──────┘
              │                                  │
              └──────────────────────────────────┘
                              │
                     ┌────────▼────────┐
                     │  INCIDENT CASE  │
                     │  (New E11 Dx)   │
                     └─────────────────┘
```

---

## Report 1: Screening Report (Monthly)

| Aspect | Definition |
|--------|-----------|
| **Period** | Calendar month (e.g., Jan 2025) |
| **Denominator** | **At-Risk Population** — Unique individuals age >18 WITHOUT any diabetes diagnosis (E10, E11, E13, E14, O24, GDM) as of month-end. Prediabetes patients ARE included in denominator. |
| **Numerator** | **Screened Patients** — Unique individuals from the denominator who completed FBS **or** A1C during the month |
| **Output Metric** | `SCREENING_RATE = Screened / At-Risk × 100` |
| **Stratification** | By screening result category: Normal / Elevated / Abnormal (among those screened) |

## Report 2: Prevalence Report (Annual)

| Aspect | Definition |
|--------|-----------|
| **Period** | Calendar year (snapshot as of Dec 31) |
| **Denominator** | **Total Population** — Unique individuals age >18, alive at Jan 1 of report year, with National ID |
| **Numerator** | **All DM Cases** — Unique individuals with ICD-10 E11 at Dec 31 of report year (includes both pre-existing and newly diagnosed during the year) |
| **Output Metric** | `PREVALENCE_RATE = DM Cases / Total Population × 100` |

## Report 3: Incidence Report (Monthly)

| Aspect | Definition |
|--------|-----------|
| **Period** | Calendar month (e.g., Jan 2025) |
| **Denominator** | **At-Risk Population** — Same as Screening denominator. Unique individuals age >18 WITHOUT any diabetes diagnosis (E10, E11, E13, E14, O24, GDM) at month start. Prediabetes IS included. |
| **Numerator** | **Incident Cases** — Unique individuals from the denominator who received a NEW ICD-10 E11 diagnosis during the month (first-ever E11 code) |
| **Output Metric** | `INCIDENCE_RATE = New E11 Cases / At-Risk × 100,000` (per 100,000) |

---

## Population Cohort Definitions

```
COHORT_TOTAL
├── Inclusion:  Age >18 at Jan 1 of report year
│               Has National ID (not null/blank)
│               Alive (no death record before Jan 1 of report year)
│
├── COHORT_DM_PREVALENT  (excluded from At-Risk)
│   ├── E10  — Type 1 DM
│   ├── E11  — Type 2 DM
│   ├── E13  — Other specified DM
│   ├── E14  — Unspecified DM
│   └── O24  — Gestational DM (GDM)
│
├── COHORT_PREDIABETES  (part of At-Risk, flagged for subgroup analysis)
│   └── R73.03 / R73.09 — Prediabetes or abnormal glucose
│
└── COHORT_AT_RISK  (Screening + Incidence denominator)
    └── = COHORT_TOTAL − COHORT_DM_PREVALENT
        (includes COHORT_PREDIABETES)
```

---

## ICD-10 Code Reference

| Code | Description | Cohort Assignment |
|------|-------------|-------------------|
| E10 | Type 1 diabetes mellitus | DM Prevalent |
| E11 | Type 2 diabetes mellitus | DM Prevalent / Incident numerator |
| E13 | Other specified diabetes mellitus | DM Prevalent |
| E14 | Unspecified diabetes mellitus | DM Prevalent |
| O24 | Diabetes mellitus in pregnancy, childbirth, and the puerperium | DM Prevalent (GDM) |
| R73.03 | Prediabetes | At-Risk (subgroup) |
| R73.09 | Other abnormal glucose | At-Risk (subgroup) |

---

## Lab Test Reference

| Test Name Variants (from EMR) | Used For |
|-------------------------------|----------|
| `Fasting glucose` | Screening numerator |
| `Fasting glucose [Mass or Moles/volume] in Serum or Plasma` | Screening numerator |
| `GLUCOSE FASTING` | Screening numerator |
| `Hemoglobin A1c.` | Screening numerator |

---

## Data Flow (Source → Staging → Report)

```
NMR.LEANHIS.PATIENTS ─────────┐
NMR.LEANHIS.PATIENTVISITS ────┤
NMR.LEANHIS.OBSERVATIONS ─────┤──► STAGING TABLES ──► 3 REPORT OUTPUTS
NMR.LEANHIS.LABRESULTS ───────┤    (per-patient,       (Screening Monthly,
NMR.LEANHIS.DIAGNOSIS_CODES ──┘     per-month grain)    Prevalence Annual,
                                                        Incidence Monthly)
```
