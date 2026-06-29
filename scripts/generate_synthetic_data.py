"""
generate_synthetic_data.py
===========================
Creates a DuckDB database (chi_sim.db) that simulates the NMR.LEANHIS EMR schema
with synthetic patient data covering all DM report scenarios.

Scenarios covered:
  - At-risk patients screened monthly (normal / elevated / abnormal results)
  - Incident E11 cases (first diagnosis in a specific month of 2025)
  - Prevalent E11 cases (diagnosed before 2025)
  - Type 1 DM (E10), Other DM (E13/E14), GDM (O24)
  - Prediabetes patients (included in at-risk pool)
  - Non-eligible: age < 18, no National ID, deceased before 2025
  - Patients with visits but no screening labs
  - Patients with only FBS, only A1C, or both
  - Lab-positive but no formal diagnosis (edge case)
  - Multi-month progression through categories

Report year: 2025
"""

import duckdb
import os
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chi_sim.db")

# Remove existing DB so we start fresh
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

con = duckdb.connect(DB_PATH)
con.execute("CREATE SCHEMA IF NOT EXISTS NMR")
con.execute("SET SCHEMA 'NMR'")

# ===========================================================================
# TABLE CREATION (mirrors NMR.LEANHIS structure)
# ===========================================================================

con.execute("""
    CREATE TABLE NMR.LEANHIS_PATIENTS (
        _ID         VARCHAR PRIMARY KEY,
        NATIONALID  VARCHAR,
        GENDERUID   VARCHAR,
        DATEOFBIRTH DATE,
        DATEOFDEATH DATE
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_PATIENTVISITS (
        _ID         INTEGER PRIMARY KEY,
        PATIENTUID  VARCHAR,
        STARTDATE   DATE
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_LABRESULTS (
        _ID              INTEGER PRIMARY KEY,
        PATIENTUID       VARCHAR,
        PATIENTVISITUID  INTEGER
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_LABRESULTS_RESULTVALUES (
        _ID           INTEGER PRIMARY KEY,
        LABRESULTS_ID  INTEGER,
        NAME          VARCHAR,
        RESULTVALUE   VARCHAR
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_OBSERVATIONS (
        _ID              INTEGER PRIMARY KEY,
        PATIENTUID       VARCHAR,
        PATIENTVISITUID  INTEGER
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES (
        _ID             INTEGER PRIMARY KEY,
        OBSERVATIONS_ID INTEGER,
        NAME            VARCHAR,
        RESULTVALUE     VARCHAR
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_DIAGNOSIS_CODES (
        _ID                   INTEGER PRIMARY KEY,
        PATIENTUID            VARCHAR,
        DIAGNOSIS_DATE        DATE,
        ICD10_CODE            VARCHAR,
        DIAGNOSIS_DESCRIPTION VARCHAR
    )
""")

con.execute("""
    CREATE TABLE NMR.LEANHIS_PHC_ASSIGNMENT (
        PATIENTUID      VARCHAR PRIMARY KEY,
        HEALTH_CLUSTER  VARCHAR
    )
""")


# ===========================================================================
# SYNTHETIC PATIENTS (21 patients covering all scenarios)
# ===========================================================================

patients = [
    # ── ELIGIBLE / AT-RISK ──────────────────────────────────────────────
    # P01: Healthy, screened every other month with normal results
    ("P01", "NAT-00001", "Male",   date(1979, 6,15), None),
    # P02: Female, screened in Mar with elevated FBS (prediabetic range)
    ("P02", "NAT-00002", "Female", date(1972, 3,22), None),
    # P03: Male, normal until Jun, then abnormal A1C + new E11 in Jun → INCIDENT
    ("P03", "NAT-00003", "Male",   date(1964,11, 8), None),
    # P06: Male, at-risk, NEVER screened → only in denominator
    ("P06", "NAT-00006", "Male",   date(1982, 1,30), None),
    # P10: Female, screened Jan normal, gets E11 in Feb → INCIDENT (early year)
    ("P10", "NAT-00010", "Female", date(1991, 5,14), None),
    # P12: Male, prediabetes (R73.03) before 2025, screened bimonthly → at-risk subgroup
    ("P12", "NAT-00012", "Male",   date(1959, 9, 3), None),
    # P13: Female, screened with A1C only (no FBS)
    ("P13", "NAT-00013", "Female", date(1985, 7,19), None),
    # P14: Male, screened with FBS only (no A1C)
    ("P14", "NAT-00014", "Male",   date(1986, 4,11), None),
    # P15: Female, progression: Jan normal → Jun elevated → Dec abnormal (no E11 dx yet)
    ("P15", "NAT-00015", "Female", date(1980, 2,28), None),
    # P17: Female, visits monthly but no screening labs → denominator only
    ("P17", "NAT-00017", "Female", date(1993,10, 5), None),
    # P18: Male, lab diabetic-range values but no E11 diagnosis → edge case
    ("P18", "NAT-00018", "Male",   date(1969, 8,17), None),
    # P19: Female, gets E11 diagnosis in Dec 2025 → INCIDENT (late year)
    ("P19", "NAT-00019", "Female", date(1989,12, 1), None),
    # P20: Male, gets E11 in Mar, abnormal labs → INCIDENT
    ("P20", "NAT-00020", "Male",   date(1962, 6,25), None),

    # ── PREVALENT DM (excluded from at-risk) ────────────────────────────
    # P04: E11 before 2025 → prevalent Type 2
    ("P04", "NAT-00004", "Female", date(1989, 8,12), None),
    # P05: E10 before 2025 → prevalent Type 1
    ("P05", "NAT-00005", "Female", date(1996, 2,17), None),
    # P11: O24 (GDM) → excluded from at-risk
    ("P11", "NAT-00011", "Female", date(1990,11,30), None),
    # P16: E13 (Other specified DM) → excluded from at-risk
    ("P16", "NAT-00016", "Male",   date(1974, 4, 2), None),

    # ── PREDIABETES-SPECIFIC (eligible, R73.03 only) ──────────────
    # P22: Female, prevalent prediabetes + HTN dx + BMI ≥ 25 → high-risk (≥2 factors)
    ("P22", "NAT-00022", "Female", date(1975, 7,14), None),
    # P23: Male, incident prediabetes (May 2025) + HTN + DLP + BMI ≥ 25 → high-risk
    ("P23", "NAT-00023", "Male",   date(1981,11,22), None),
    # P24: Female, prevalent prediabetes + no other risk factors → NOT high-risk
    ("P24", "NAT-00024", "Female", date(1988, 4, 5), None),

    # ── NOT ELIGIBLE ────────────────────────────────────────────────────
    # P07: Age 17 → under 18
    ("P07", "NAT-00007", "Female", date(2007, 3,10), None),  # turns 18 in Mar 2025
    # P08: No National ID
    ("P08", None,         "Male",   date(1969, 5,20), None),
    # P09: Deceased before Jan 1, 2025
    ("P09", "NAT-00009", "Male",   date(1954, 7, 4), date(2024, 11, 15)),
]

# Insert patients
con.executemany(
    "INSERT INTO NMR.LEANHIS_PATIENTS VALUES (?, ?, ?, ?, ?)",
    patients
)

# ===========================================================================
# PATIENT VISITS (monthly visits for most patients in 2025)
# ===========================================================================

visit_id = 0
visits = []
lab_results = []
lab_result_values = []
observations = []
observation_values = []

lab_rslt_id = 0
lab_val_id = 0
obs_id = 0
obs_val_id = 0

def add_fbs_lab(patient_uid, visit_date, visit_id, value, result_name="Fasting glucose"):
    """Add an FBS result via LABRESULTS."""
    global lab_rslt_id, lab_val_id
    lab_rslt_id += 1
    lab_val_id += 1
    lab_results.append((lab_rslt_id, patient_uid, visit_id))
    lab_result_values.append((lab_val_id, lab_rslt_id, result_name, str(value)))

def add_a1c_lab(patient_uid, visit_date, visit_id, value):
    """Add an A1C result via LABRESULTS."""
    global lab_rslt_id, lab_val_id
    lab_rslt_id += 1
    lab_val_id += 1
    lab_results.append((lab_rslt_id, patient_uid, visit_id))
    lab_result_values.append((lab_val_id, lab_rslt_id, "Hemoglobin A1c.", str(value)))

def add_fbs_obs(patient_uid, visit_date, visit_id, value):
    """Add an FBS result via OBSERVATIONS."""
    global obs_id, obs_val_id
    obs_id += 1
    obs_val_id += 1
    observations.append((obs_id, patient_uid, visit_id))
    observation_values.append((obs_val_id, obs_id, "Fasting glucose", str(value)))

def add_a1c_obs(patient_uid, visit_date, visit_id, value):
    """Add an A1C result via OBSERVATIONS."""
    global obs_id, obs_val_id
    obs_id += 1
    obs_val_id += 1
    observations.append((obs_id, patient_uid, visit_id))
    observation_values.append((obs_val_id, obs_id, "Hemoglobin A1c.", str(value)))

# Generate monthly visits for 2025
for month in range(1, 13):
    visit_date = date(2025, month, 15)  # mid-month visit

    # ── P01: screened every OTHER month, normal results ──
    if month % 2 == 0:  # Feb, Apr, Jun, Aug, Oct, Dec
        visit_id += 1
        visits.append((visit_id, "P01", visit_date))
        add_fbs_lab("P01", visit_date, visit_id, 88.0)    # normal FBS (mg/dL)
        add_a1c_lab("P01", visit_date, visit_id, 5.2)     # normal A1C
    else:
        # Visit without labs (odd months)
        visit_id += 1
        visits.append((visit_id, "P01", visit_date))

    # ── P02: screened in Mar only, elevated FBS ──
    if month == 3:
        visit_id += 1
        visits.append((visit_id, "P02", visit_date))
        add_fbs_lab("P02", visit_date, visit_id, 110.0)   # elevated FBS (mg/dL)
        add_a1c_lab("P02", visit_date, visit_id, 5.5)     # normal A1C
    elif month in (1, 6, 9):  # visit but no screening
        visit_id += 1
        visits.append((visit_id, "P02", visit_date))

    # ── P03: normal Jan-May, abnormal A1C + incident E11 in Jun ──
    if month <= 5:
        visit_id += 1
        visits.append((visit_id, "P03", visit_date))
        if month % 2 == 0:  # screen every other: Feb, Apr
            add_fbs_lab("P03", visit_date, visit_id, 95.0)   # normal FBS
            add_a1c_lab("P03", visit_date, visit_id, 5.4)    # normal A1C
    elif month >= 6:
        visit_id += 1
        visits.append((visit_id, "P03", visit_date))
        if month in (6, 8, 10, 12):
            add_fbs_lab("P03", visit_date, visit_id, 145.0)  # abnormal FBS
            add_a1c_lab("P03", visit_date, visit_id, 7.2)    # abnormal A1C
            if month == 6:
                # Duplicate A1C via OBSERVATIONS to test UNION ALL logic
                add_a1c_obs("P03", visit_date, visit_id, 7.2)

    # ── P04: prevalent E11, visited monthly (has labs but not in at-risk) ──
    visit_id += 1
    visits.append((visit_id, "P04", visit_date))
    if month == 6:
        add_a1c_lab("P04", visit_date, visit_id, 7.8)    # abnormal A1C (already diabetic)

    # ── P05: prevalent E10, occasional visits ──
    if month in (3, 6, 9, 12):
        visit_id += 1
        visits.append((visit_id, "P05", visit_date))

    # ── P06: at-risk, visits but NEVER screened ──
    visit_id += 1
    visits.append((visit_id, "P06", visit_date))

    # ── P07: age 17, turns 18 in Mar → not in total pop (age at Jan 1 matters) ──
    visit_id += 1
    visits.append((visit_id, "P07", visit_date))

    # ── P08: no National ID → not in total pop ──
    visit_id += 1
    visits.append((visit_id, "P08", visit_date))

    # ── P09: deceased → no visits in 2025 ──
    # (intentionally no visits for P09)

    # ── P10: normal Jan, incident E11 in Feb ──
    visit_id += 1
    visits.append((visit_id, "P10", visit_date))
    if month == 1:
        add_fbs_lab("P10", visit_date, visit_id, 90.0)
        add_a1c_lab("P10", visit_date, visit_id, 5.3)
    elif month >= 2 and month % 2 == 0:
        add_fbs_lab("P10", visit_date, visit_id, 155.0)
        add_a1c_lab("P10", visit_date, visit_id, 7.5)

    # ── P11: GDM, occasional visits ──
    if month in (2, 5, 8, 11):
        visit_id += 1
        visits.append((visit_id, "P11", visit_date))

    # ── P12: prediabetes, screened bimonthly ──
    visit_id += 1
    visits.append((visit_id, "P12", visit_date))
    if month % 2 == 0:
        add_fbs_lab("P12", visit_date, visit_id, 108.0)    # elevated FBS
        add_a1c_lab("P12", visit_date, visit_id, 5.9)      # elevated A1C
        # Also add FBS via OBSERVATIONS on same visit (duplicate to test dedup)
        add_fbs_obs("P12", visit_date, visit_id, 108.0)

    # ── P13: A1C only (no FBS ever) ──
    visit_id += 1
    visits.append((visit_id, "P13", visit_date))
    if month % 3 == 0:  # every 3 months
        add_a1c_lab("P13", visit_date, visit_id, 5.1)      # normal A1C only

    # ── P14: FBS only (no A1C ever) ──
    visit_id += 1
    visits.append((visit_id, "P14", visit_date))
    if month % 3 == 0:
        add_fbs_lab("P14", visit_date, visit_id, 102.0)    # elevated FBS only

    # ── P15: progression Jan normal → Jun elevated → Dec abnormal ──
    visit_id += 1
    visits.append((visit_id, "P15", visit_date))
    if month in (1, 6, 12):  # screened quarterly-ish
        if month == 1:
            add_fbs_lab("P15", visit_date, visit_id, 85.0)
            add_a1c_lab("P15", visit_date, visit_id, 5.3)
        elif month == 6:
            add_fbs_lab("P15", visit_date, visit_id, 112.0)
            add_a1c_lab("P15", visit_date, visit_id, 5.8)
        elif month == 12:
            add_fbs_lab("P15", visit_date, visit_id, 140.0)
            add_a1c_lab("P15", visit_date, visit_id, 7.0)

    # ── P16: other DM (E13), occasional visits ──
    if month in (1, 4, 7, 10):
        visit_id += 1
        visits.append((visit_id, "P16", visit_date))

    # ── P17: visits but no screening labs ever ──
    visit_id += 1
    visits.append((visit_id, "P17", visit_date))

    # ── P18: lab diabetic but NO E11 diagnosis → edge case ──
    visit_id += 1
    visits.append((visit_id, "P18", visit_date))
    if month % 3 == 0:
        add_fbs_lab("P18", visit_date, visit_id, 160.0)    # diabetic range FBS
        add_a1c_lab("P18", visit_date, visit_id, 8.0)      # diabetic range A1C

    # ── P19: at-risk all year, gets E11 in Dec ──
    visit_id += 1
    visits.append((visit_id, "P19", visit_date))
    if month <= 11:
        add_fbs_lab("P19", visit_date, visit_id, 92.0)     # normal until Dec
        add_a1c_lab("P19", visit_date, visit_id, 5.4)
    elif month == 12:
        add_fbs_lab("P19", visit_date, visit_id, 148.0)    # abnormal
        add_a1c_lab("P19", visit_date, visit_id, 7.3)      # abnormal

    # ── P20: incident E11 in Mar ──
    visit_id += 1
    visits.append((visit_id, "P20", visit_date))
    if month <= 2:
        add_fbs_lab("P20", visit_date, visit_id, 94.0)
        add_a1c_lab("P20", visit_date, visit_id, 5.5)
    else:
        add_fbs_lab("P20", visit_date, visit_id, 170.0)
        add_a1c_lab("P20", visit_date, visit_id, 9.0)

    # ── P22: monthly visits (prediabetes + HTN; risk-factor data added by extend script) ──
    visit_id += 1
    visits.append((visit_id, "P22", visit_date))

    # ── P23: monthly visits (incident prediabetes; risk-factor data added by extend script) ──
    visit_id += 1
    visits.append((visit_id, "P23", visit_date))

    # ── P24: monthly visits (prediabetes, NO other risk factors; single BMI reading) ──
    visit_id += 1
    visits.append((visit_id, "P24", visit_date))

# Insert all generated records
con.executemany("INSERT INTO NMR.LEANHIS_PATIENTVISITS VALUES (?, ?, ?)", visits)
con.executemany("INSERT INTO NMR.LEANHIS_LABRESULTS VALUES (?, ?, ?)", lab_results)
con.executemany("INSERT INTO NMR.LEANHIS_LABRESULTS_RESULTVALUES VALUES (?, ?, ?, ?)", lab_result_values)
if observations:
    con.executemany("INSERT INTO NMR.LEANHIS_OBSERVATIONS VALUES (?, ?, ?)", observations)
if observation_values:
    con.executemany("INSERT INTO NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES VALUES (?, ?, ?, ?)", observation_values)


# ===========================================================================
# DIAGNOSIS CODES (ICD-10)
# ===========================================================================

diagnoses = []
diag_id = 0

def add_dx(patient, dx_date, code, desc):
    global diag_id
    diag_id += 1
    diagnoses.append((diag_id, patient, dx_date, code, desc))

# P03: Incident E11 in June 2025
add_dx("P03", date(2025, 6, 20), "E11", "Type 2 diabetes mellitus")

# P04: Prevalent E11 (diagnosed in 2023)
add_dx("P04", date(2023, 4, 10), "E11", "Type 2 diabetes mellitus")

# P05: Prevalent E10 (Type 1, diagnosed in 2020)
add_dx("P05", date(2020, 1, 15), "E10", "Type 1 diabetes mellitus")

# P10: Incident E11 in Feb 2025
add_dx("P10", date(2025, 2, 18), "E11", "Type 2 diabetes mellitus")

# P11: GDM during pregnancy in 2024
add_dx("P11", date(2024, 7, 5), "O24", "Gestational diabetes mellitus")

# P12: Prediabetes (R73.03) diagnosed in 2024 — still at-risk
add_dx("P12", date(2024, 9, 12), "R73.03", "Prediabetes")

# Additional prediabetes diagnoses — progression cases (R73.03 → E11 same month)
add_dx("P03", date(2025, 6, 20), "R73.03", "Prediabetes")           # incident, same month as E11
add_dx("P15", date(2024,11, 15), "R73.03", "Prediabetes")           # pre-existing prediabetes
add_dx("P19", date(2025,12, 10), "R73.03", "Prediabetes")           # incident, same month as E11

# P22/P23/P24 — prediabetes cohort test cases (see extend script for risk-factor data)
add_dx("P22", date(2024, 3, 20), "R73.03", "Prediabetes")           # prevalent, high-risk
add_dx("P23", date(2025, 5, 12), "R73.03", "Prediabetes")           # incident, high-risk
add_dx("P24", date(2024, 8,  8), "R73.03", "Prediabetes")           # prevalent, NOT high-risk

# P15: No DM diagnosis yet (labs are abnormal but no formal E11)
# (no diagnosis for P15 — tests edge case)

# P16: Other specified DM (E13) in 2022
add_dx("P16", date(2022, 3, 8), "E13", "Other specified diabetes mellitus")

# P18: No DM diagnosis (despite diabetic-range labs)
# (no diagnosis for P18 — tests edge case)

# P19: Incident E11 in Dec 2025
add_dx("P19", date(2025, 12, 10), "E11", "Type 2 diabetes mellitus")

# P20: Incident E11 in Mar 2025
add_dx("P20", date(2025, 3, 5), "E11", "Type 2 diabetes mellitus")

con.executemany(
    "INSERT INTO NMR.LEANHIS_DIAGNOSIS_CODES VALUES (?, ?, ?, ?, ?)",
    diagnoses
)


# ===========================================================================
# PHC ASSIGNMENT (Health Cluster mapping)
# ===========================================================================
# Maps each patient to a health cluster. Patients without a record → 'Unassigned'.
# Cluster A (8 patients): P01, P02, P03, P04, P06, P12, P15, P22
# Cluster B (7 patients): P05, P10, P13, P14, P17, P19, P23
# Cluster C (4 patients): P16, P18, P20, P24
# Unassigned (1 patient):  P11 (GDM, deliberately missing)
# Ineligible patients (P07, P08, P09) are omitted — irrelevant for reports.

cluster_assignments = [
    ("P01", "Cluster A"), ("P02", "Cluster A"), ("P03", "Cluster A"),
    ("P04", "Cluster A"), ("P06", "Cluster A"), ("P12", "Cluster A"),
    ("P15", "Cluster A"), ("P22", "Cluster A"),
    ("P05", "Cluster B"), ("P10", "Cluster B"), ("P13", "Cluster B"),
    ("P14", "Cluster B"), ("P17", "Cluster B"), ("P19", "Cluster B"),
    ("P23", "Cluster B"),
    ("P16", "Cluster C"), ("P18", "Cluster C"), ("P20", "Cluster C"),
    ("P24", "Cluster C"),
    # P11 intentionally omitted — tests COALESCE → 'Unassigned'
]

con.executemany(
    "INSERT INTO NMR.LEANHIS_PHC_ASSIGNMENT VALUES (?, ?)",
    cluster_assignments
)


# ===========================================================================
# VERIFICATION QUERIES
# ===========================================================================

print("=" * 60)
print("SYNTHETIC DATA GENERATED — SUMMARY")
print("=" * 60)

for table in [
    "LEANHIS_PATIENTS", "LEANHIS_PATIENTVISITS",
    "LEANHIS_LABRESULTS", "LEANHIS_LABRESULTS_RESULTVALUES",
    "LEANHIS_OBSERVATIONS", "LEANHIS_OBSERVATIONS_OBSERVATIONVALUES",
    "LEANHIS_DIAGNOSIS_CODES", "LEANHIS_PHC_ASSIGNMENT"
]:
    count = con.execute(f"SELECT COUNT(*) FROM NMR.{table}").fetchone()[0]
    print(f"  {table:45s} {count:>6,} rows")

print()
print("Patients by scenario:")
print(f"  Total patients:          {len(patients)}")
print(f"  In total population:     {sum(1 for p in patients if p[2] is not None and p[4] is None and (2025 - p[3].year) > 18)}")
print(f"  At-risk (no DM dx):      ~13 (P01,02,03,06,10,12,13,14,15,17,18,19,20)")
print(f"  Prevalent DM:              4 (P04,05,11,16)")
print(f"  Incident E11 in 2025:      4 (P03-Jun, P10-Feb, P19-Dec, P20-Mar)")
print(f"  Prediabetes (at-risk):     1 (P12)")
print(f"  Not eligible:              3 (P07-age, P08-noID, P09-deceased)")
print(f"  Lab-positive no Dx:        1 (P18)")
print(f"  Never screened:            2 (P06, P17)")
print(f"  Clusters:                  Cluster A (7), Cluster B (6), Cluster C (3), Unassigned (1: P11)")
print()

con.close()
print(f"Database saved to: {DB_PATH}")
print("Done.")
