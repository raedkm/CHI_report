"""
extend_data_htn_dlp_ob.py
=========================
Adds HTN (BP), DLP (lipids), and Obesity (BMI) data to the existing
chi_sim.db for the same 20 patients.

Run after generate_synthetic_data.py.
"""
import duckdb
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chi_sim.db")
con = duckdb.connect(DB_PATH)

# Tables already exist. We're adding new lab/observation records.

# Find the max IDs to continue from
max_lab_id = con.execute("SELECT COALESCE(MAX(_ID), 0) FROM NMR.LEANHIS_LABRESULTS").fetchone()[0]
max_lab_val_id = con.execute("SELECT COALESCE(MAX(_ID), 0) FROM NMR.LEANHIS_LABRESULTS_RESULTVALUES").fetchone()[0]
max_obs_id = con.execute("SELECT COALESCE(MAX(_ID), 0) FROM NMR.LEANHIS_OBSERVATIONS").fetchone()[0]
max_obs_val_id = con.execute("SELECT COALESCE(MAX(_ID), 0) FROM NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES").fetchone()[0]
max_dx_id = con.execute("SELECT COALESCE(MAX(_ID), 0) FROM NMR.LEANHIS_DIAGNOSIS_CODES").fetchone()[0]

# Get all visits for reference
visits_map = {}
for row in con.execute("""
    SELECT PATIENTUID, _ID, STARTDATE
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    ORDER BY PATIENTUID, STARTDATE
""").fetchall():
    pid, vid, dt = row
    month = dt.month
    key = (pid, month)
    if key not in visits_map:
        visits_map[key] = vid  # keep first visit of month per patient

# ===========================================================================
# HELPER: Add a BP observation (Systolic & Diastolic paired)
# ===========================================================================
def add_bp(pid, month, sys_val, dia_val):
    global max_obs_id, max_obs_val_id
    vid = visits_map.get((pid, month))
    if vid is None:
        return
    # Systolic
    max_obs_id += 1; max_obs_val_id += 1
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS VALUES (?, ?, ?)",
                (max_obs_id, pid, vid))
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES VALUES (?, ?, ?, ?)",
                (max_obs_val_id, max_obs_id, "Systolic BP", str(sys_val)))
    # Diastolic
    max_obs_id += 1; max_obs_val_id += 1
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS VALUES (?, ?, ?)",
                (max_obs_id, pid, vid))
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES VALUES (?, ?, ?, ?)",
                (max_obs_val_id, max_obs_id, "Diastolic BP", str(dia_val)))

# ===========================================================================
# HELPER: Add a BMI observation
# ===========================================================================
def add_bmi(pid, month, bmi_val):
    global max_obs_id, max_obs_val_id
    vid = visits_map.get((pid, month))
    if vid is None:
        return
    max_obs_id += 1; max_obs_val_id += 1
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS VALUES (?, ?, ?)",
                (max_obs_id, pid, vid))
    con.execute("INSERT INTO NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES VALUES (?, ?, ?, ?)",
                (max_obs_val_id, max_obs_id, "BMI", str(bmi_val)))

# ===========================================================================
# HELPER: Add lipid labs (HDL, LDL, Cholesterol, Triglyceride)
# ===========================================================================
def add_lipids(pid, month, hdl, ldl, chol, trig):
    global max_lab_id, max_lab_val_id
    vid = visits_map.get((pid, month))
    if vid is None:
        return
    for name, val in [("Cholesterol.in HDL", hdl), ("Cholesterol.in LDL", ldl),
                       ("Cholesterol in Serum or Plasma", chol), ("Triglyceride", trig)]:
        max_lab_id += 1; max_lab_val_id += 1
        con.execute("INSERT INTO NMR.LEANHIS_LABRESULTS VALUES (?, ?, ?)",
                    (max_lab_id, pid, vid))
        con.execute("INSERT INTO NMR.LEANHIS_LABRESULTS_RESULTVALUES VALUES (?, ?, ?, ?)",
                    (max_lab_val_id, max_lab_id, name, str(val)))

# ===========================================================================
# HELPER: Add diagnosis
# ===========================================================================
def add_dx(pid, dx_date, code, desc):
    global max_dx_id
    max_dx_id += 1
    con.execute("INSERT INTO NMR.LEANHIS_DIAGNOSIS_CODES VALUES (?, ?, ?, ?, ?)",
                (max_dx_id, pid, dx_date, code, desc))


# ===========================================================================
# HYPERTENSION (HTN) — Blood Pressure readings
# ===========================================================================
# Scenarios:
#   P01: SYS 115/DIA 75 every even month → normal, screened
#   P02: SYS 125/DIA 82 in Mar → elevated
#   P03: SYS 140/DIA 95 from Jun onward → abnormal (same time as DM incident)
#   P06: SYS 118/DIA 72 every visit → normal, screened
#   P10: SYS 132/DIA 86 from Feb → abnormal (same time as DM incident)
#   P12: SYS 122/DIA 78 bimonthly → elevated
#   P15: progression: Jan normal → Jun elevated → Dec abnormal
#   P17: visits but NO BP → never screened
#   P18: SYS 145/DIA 98 every 3 months → abnormal, no HTN dx (edge case)
#   P20: SYS 135/DIA 92 from Mar → abnormal (same time as DM incident)
#   HTN diagnoses: I10 for P03 (Jun), P10 (Feb), P20 (Mar)
#   Pre-existing: I10 for P04 (2023)

print("Adding HTN (BP) data...")
for month in range(1, 13):
    # P01: normal BP, even months only
    if month % 2 == 0:
        add_bp("P01", month, 115, 75)
    # P02: elevated in Mar
    if month == 3:
        add_bp("P02", month, 125, 82)
    # P03: normal Jan-May, abnormal Jun-Dec
    if month <= 5:
        add_bp("P03", month, 118, 78)
    else:
        add_bp("P03", month, 140, 95)
    # P06: normal every month (screened)
    add_bp("P06", month, 118, 72)
    # P10: normal Jan, abnormal Feb-Dec
    if month == 1:
        add_bp("P10", month, 115, 75)
    elif month >= 2:
        add_bp("P10", month, 132, 86)
    # P12: elevated bimonthly
    if month % 2 == 0:
        add_bp("P12", month, 122, 78)
    # P15: progression
    if month == 1:
        add_bp("P15", month, 115, 70)
    elif month == 6:
        add_bp("P15", month, 128, 82)
    elif month == 12:
        add_bp("P15", month, 135, 90)
    # P18: abnormal, no HTN dx
    if month % 3 == 0:
        add_bp("P18", month, 145, 98)
    # P20: normal Jan-Feb, abnormal Mar-Dec
    if month <= 2:
        add_bp("P20", month, 116, 76)
    else:
        add_bp("P20", month, 135, 92)

# HTN Diagnoses (ICD-10 I10)
add_dx("P03", "2025-06-20", "I10", "Essential hypertension")       # incident Jun
add_dx("P04", "2023-06-01", "I10", "Essential hypertension")       # pre-existing
add_dx("P10", "2025-02-18", "I10", "Essential hypertension")       # incident Feb
add_dx("P20", "2025-03-05", "I10", "Essential hypertension")       # incident Mar

# ===========================================================================
# DYSLIPIDEMIA (DLP) — Lipid panel
# ===========================================================================
# Adding: HDL, LDL, Cholesterol, Triglyceride
# P01: normal panel every even month
#   HDL 55 (M: normal≥40), LDL 110 (normal<130), Chol 175 (normal<200), Trig 120 (normal<150)
# P02: elevated in Mar: HDL 38 (M: abnormal?), LDL 145, Chol 215, Trig 180
#   Wait, P02 is Female. HDL threshold: F ≥50 normal. So HDL 38 → abnormal for female
# P03: abnormal from Jun: HDL 35 (F? P03 is Male, ≥40 normal. 35→abnormal), LDL 170, Chol 250, Trig 220
#   P03 is Male. HDL 35 < 40 → abnormal. LDL 170 → abnormal (>160). Chol 250 → abnormal (>240). Trig 220 → abnormal (>200)
# P06: normal panel every month
# P10: abnormal from Feb (same as DM/HTN incident)
# P12: elevated bimonthly
# P15: progression: normal → elevated → abnormal
# DLP Dx: P03(Jun), P10(Feb) — incident. P04(2023) — pre-existing.

print("Adding DLP (Lipid) data...")
for month in range(1, 13):
    # P01: normal every even month (Male)
    if month % 2 == 0:
        add_lipids("P01", month, 55, 110, 175, 120)
    # P02: elevated in Mar (Female)
    if month == 3:
        add_lipids("P02", month, 38, 145, 215, 180)
    # P03: normal Jan-May, abnormal Jun-Dec (Male)
    if month <= 5:
        add_lipids("P03", month, 50, 120, 185, 130)
    else:
        add_lipids("P03", month, 35, 170, 250, 220)
    # P06: normal every month (Male)
    add_lipids("P06", month, 48, 115, 180, 125)
    # P10: normal Jan, abnormal Feb-Dec (Female)
    if month == 1:
        add_lipids("P10", month, 55, 118, 185, 130)
    elif month >= 2:
        add_lipids("P10", month, 42, 155, 230, 195)
    # P12: elevated bimonthly (Male)
    if month % 2 == 0:
        add_lipids("P12", month, 42, 140, 210, 165)
    # P15: progression (Female)
    if month == 1:
        add_lipids("P15", month, 58, 105, 170, 115)
    elif month == 6:
        add_lipids("P15", month, 48, 135, 215, 168)
    elif month == 12:
        add_lipids("P15", month, 42, 160, 245, 210)
    # P20: normal Jan-Feb, abnormal Mar-Dec (Male)
    if month <= 2:
        add_lipids("P20", month, 52, 118, 180, 125)
    else:
        add_lipids("P20", month, 36, 165, 248, 215)

# DLP Diagnoses (ICD-10 E78)
add_dx("P03", "2025-06-20", "E78", "Disorders of lipoprotein metabolism")  # incident Jun
add_dx("P04", "2023-09-15", "E78", "Disorders of lipoprotein metabolism")  # pre-existing
add_dx("P10", "2025-02-18", "E78", "Disorders of lipoprotein metabolism")  # incident Feb

# ===========================================================================
# OBESITY — BMI measurements
# ===========================================================================
# P01: BMI 23 (normal)
# P02: BMI 31 (obese)
# P03: BMI 35 (obese) — pre-existing
# P06: BMI 28 (overweight)
# P10: BMI 27 (overweight)
# P11: BMI 24 (normal) — GDM patient
# P12: BMI 32 (obese) — prediabetes
# P13: BMI 21 (normal)
# P14: BMI 25 (overweight)
# P15: BMI 29 → 31 → 34 (progression overweight → obese → obese)
# P17: no BMI (never screened for obesity)
# P19: BMI 22 (normal)
# P20: BMI 33 (obese)
# Obesity Dx: P03 (2024) — pre-existing. P10 (Feb 2025) — incident.
#   But wait, the incidence for obesity is about NEW E66 diagnoses, not lab thresholds.
#   BMI is the screening tool. The diagnosis is ICD-10 E66.

print("Adding Obesity (BMI) data...")
for month in range(1, 13):
    if month % 3 == 0:  # quarterly BMI checks for most patients
        add_bmi("P01", month, 23.0)
        add_bmi("P02", month, 31.0)
        add_bmi("P03", month, 35.0)
        add_bmi("P06", month, 28.0)
        add_bmi("P10", month, 27.0)
        add_bmi("P11", month, 24.0)
        add_bmi("P12", month, 32.0)
        add_bmi("P13", month, 21.0)
        add_bmi("P14", month, 25.0)
        add_bmi("P16", month, 26.0)
        add_bmi("P19", month, 22.0)
        add_bmi("P20", month, 33.0)
    # P15: progression across year
    if month == 3:
        add_bmi("P15", month, 29.0)
    elif month == 6:
        add_bmi("P15", month, 31.0)
    elif month == 9:
        add_bmi("P15", month, 32.0)
    elif month == 12:
        add_bmi("P15", month, 34.0)
    # P04 (prevalent DM) quarterly
    if month % 3 == 0:
        add_bmi("P04", month, 30.5)

# Obesity Diagnoses (ICD-10 E66)
add_dx("P03", "2024-08-01", "E66", "Obesity")    # pre-existing
add_dx("P10", "2025-02-18", "E66", "Obesity")    # incident Feb
add_dx("P12", "2024-10-01", "E66", "Obesity")    # pre-existing

# ===========================================================================
# VERIFY
# ===========================================================================
print()
for label, q in [
    ("BP readings (Systolic)", "SELECT COUNT(*) FROM NMR.LEANHIS_OBSERVATIONS o JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID=ov.OBSERVATIONS_ID WHERE ov.NAME='Systolic BP'"),
    ("BP readings (Diastolic)", "SELECT COUNT(*) FROM NMR.LEANHIS_OBSERVATIONS o JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID=ov.OBSERVATIONS_ID WHERE ov.NAME='Diastolic BP'"),
    ("BMI readings", "SELECT COUNT(*) FROM NMR.LEANHIS_OBSERVATIONS o JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID=ov.OBSERVATIONS_ID WHERE ov.NAME='BMI'"),
    ("Lipid labs (total)", "SELECT COUNT(*) FROM NMR.LEANHIS_LABRESULTS_RESULTVALUES WHERE NAME LIKE 'Cholesterol%' OR NAME='Triglyceride'"),
    ("New diagnoses added", "SELECT COUNT(*) FROM NMR.LEANHIS_DIAGNOSIS_CODES"),
]:
    count = con.execute(q).fetchone()[0]
    print(f"  {label:<30s} {count:>4}")

con.close()
print(f"\nDatabase updated: {DB_PATH}")
print("Done.")
