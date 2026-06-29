"""
create_views_in_duckdb.py
=========================
Creates CHI_REPORTING views in chi_sim.db matching the Snowflake views.
Each view is independently queryable for debugging.
Run: uv run python scripts/create_views_in_duckdb.py
"""
import duckdb
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

DB = os.path.join(os.path.dirname(__file__), "..", "data", "chi_sim.db")
con = duckdb.connect(DB)

# Reset
con.execute("DROP SCHEMA IF EXISTS CHI_REPORTING CASCADE")
con.execute("CREATE SCHEMA CHI_REPORTING")
con.execute("""
CREATE TABLE CHI_REPORTING.chi_config AS
SELECT 2025 AS report_year, '2025-01-01'::DATE AS report_start, '2026-01-01'::DATE AS report_end
""")

# --- Compliance Config Tables ---
con.execute("""
CREATE TABLE CHI_REPORTING.chi_control_thresholds (
    condition VARCHAR, marker VARCHAR, gender VARCHAR, control_level VARCHAR,
    min_value DECIMAL(10,2), max_value DECIMAL(10,2),
    level_order INTEGER, label VARCHAR
)
""")

thresholds = [
    # DM — A1C only
    ('dm','a1c','All','controlled',0.0,7.0,0,'Controlled (A1C < 7.0%)'),
    ('dm','a1c','All','uncontrolled',7.0,8.0,1,'Uncontrolled (A1C 7.0–7.9%)'),
    ('dm','a1c','All','uncontrolled',8.0,9.0,2,'Uncontrolled (A1C 8.0–8.9%)'),
    ('dm','a1c','All','uncontrolled',9.0,None,3,'Uncontrolled (A1C ≥ 9.0%)'),
    # HTN — SYS + DIA
    ('htn','sys','All','controlled',0.0,130.0,0,'Controlled (SYS < 130)'),
    ('htn','sys','All','uncontrolled',130.0,140.0,1,'Uncontrolled (SYS 130–139)'),
    ('htn','sys','All','uncontrolled',140.0,160.0,2,'Uncontrolled (SYS 140–159)'),
    ('htn','sys','All','uncontrolled',160.0,None,3,'Uncontrolled (SYS ≥ 160)'),
    ('htn','dia','All','controlled',0.0,80.0,0,'Controlled (DIA < 80)'),
    ('htn','dia','All','uncontrolled',80.0,90.0,1,'Uncontrolled (DIA 80–89)'),
    ('htn','dia','All','uncontrolled',90.0,100.0,2,'Uncontrolled (DIA 90–99)'),
    ('htn','dia','All','uncontrolled',100.0,None,3,'Uncontrolled (DIA ≥ 100)'),
    # DLP — 4 markers (HDL gender-specific)
    ('dlp','ldl','All','controlled',0.0,100.0,0,'Controlled (LDL < 100)'),
    ('dlp','ldl','All','uncontrolled',100.0,130.0,1,'Uncontrolled (LDL 100–129)'),
    ('dlp','ldl','All','uncontrolled',130.0,160.0,2,'Uncontrolled (LDL 130–159)'),
    ('dlp','ldl','All','uncontrolled',160.0,None,3,'Uncontrolled (LDL ≥ 160)'),
    ('dlp','chol','All','controlled',0.0,200.0,0,'Controlled (Chol < 200)'),
    ('dlp','chol','All','uncontrolled',200.0,240.0,1,'Uncontrolled (Chol 200–239)'),
    ('dlp','chol','All','uncontrolled',240.0,280.0,2,'Uncontrolled (Chol 240–279)'),
    ('dlp','chol','All','uncontrolled',280.0,None,3,'Uncontrolled (Chol ≥ 280)'),
    ('dlp','trig','All','controlled',0.0,150.0,0,'Controlled (Trig < 150)'),
    ('dlp','trig','All','uncontrolled',150.0,200.0,1,'Uncontrolled (Trig 150–199)'),
    ('dlp','trig','All','uncontrolled',200.0,500.0,2,'Uncontrolled (Trig 200–499)'),
    ('dlp','trig','All','uncontrolled',500.0,None,3,'Uncontrolled (Trig ≥ 500)'),
    ('dlp','hdl','Male','controlled',40.0,None,0,'Controlled (HDL ≥ 40)'),
    ('dlp','hdl','Male','uncontrolled',0.0,40.0,1,'Uncontrolled (HDL < 40)'),
    ('dlp','hdl','Female','controlled',50.0,None,0,'Controlled (HDL ≥ 50)'),
    ('dlp','hdl','Female','uncontrolled',0.0,50.0,1,'Uncontrolled (HDL < 50)'),
    # OB — BMI only
    ('ob','bmi','All','controlled',18.5,25.0,0,'Controlled (BMI 18.5–24.9)'),
    ('ob','bmi','All','uncontrolled',25.0,30.0,1,'Uncontrolled (BMI 25.0–29.9)'),
    ('ob','bmi','All','uncontrolled',30.0,35.0,2,'Uncontrolled (BMI 30.0–34.9)'),
    ('ob','bmi','All','uncontrolled',35.0,None,3,'Uncontrolled (BMI ≥ 35.0)'),
]
con.executemany("INSERT INTO CHI_REPORTING.chi_control_thresholds VALUES (?,?,?,?,?,?,?,?)", thresholds)

con.execute("""
CREATE TABLE CHI_REPORTING.chi_care_gap_config AS
SELECT 3 AS target_quarters_completed, 2025 AS report_year
""")

con.execute("""
CREATE TABLE CHI_REPORTING.chi_high_risk_factors (
    condition VARCHAR, factor_code VARCHAR, factor_label VARCHAR,
    source_view VARCHAR, source_column VARCHAR,
    value_min DECIMAL(10,2), weight INTEGER, requires_value BOOLEAN, level_order INTEGER
)
""")
high_risk_factors = [
    # PREDIAB — first condition, all 6 risk factors
    ('prediab', 'bmi_ge_25',               'BMI >= 25 (latest 2025)',         'CHI_REPORTING.stg_prediab_cohort', 'has_bmi_ge_25',     None, 1, False, 1),
    ('prediab', 'htn_dx',                  'Hypertension diagnosis',          'CHI_REPORTING.stg_prediab_cohort', 'has_htn_dx',        None, 1, False, 2),
    ('prediab', 'dlp_dx',                  'Dyslipidemia diagnosis',          'CHI_REPORTING.stg_prediab_cohort', 'has_dlp_dx',        None, 1, False, 3),
    ('prediab', 'family_history_diabetes', 'First-degree family hx of DM',   'chi_high_risk_factors',           'always_false',      None, 1, False, 4),
    ('prediab', 'gdm_history',             'Gestational DM history',          'CHI_REPORTING.stg_prediab_cohort', 'has_gdm_history',   None, 1, False, 5),
    ('prediab', 'pcos_e28_2',              'PCOS / PMOS proxy (E28.2)',      'CHI_REPORTING.stg_prediab_cohort', 'has_pcos',          None, 1, False, 6),
]
con.executemany("INSERT INTO CHI_REPORTING.chi_high_risk_factors VALUES (?,?,?,?,?,?,?,?,?)", high_risk_factors)
print(f"  chi_control_thresholds:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.chi_control_thresholds').fetchone()[0]} rows")
print(f"  chi_care_gap_config:        {con.execute('SELECT target_quarters_completed FROM CHI_REPORTING.chi_care_gap_config').fetchone()[0]} target quarters")
print(f"  chi_high_risk_factors:      {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.chi_high_risk_factors').fetchone()[0]} risk factors")

print("=== Creating CHI_REPORTING views in chi_sim.db ===\n")

# =====================================================================
# DM — STAGING
# =====================================================================
print("--- DM Staging ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_cohort AS
WITH pop AS (
    SELECT _ID AS patient_key, GENDERUID AS gender, DATEOFBIRTH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
dx AS (
    SELECT PATIENTUID AS patient_key,
           MIN(DIAGNOSIS_DATE) AS first_any_dm_date,
           MIN(CASE WHEN TRIM(UPPER(ICD10_CODE))='E11' THEN DIAGNOSIS_DATE END) AS first_e11_date,
           MIN(CASE WHEN TRIM(UPPER(ICD10_CODE))='E10' THEN DIAGNOSIS_DATE END) AS first_e10_date,
           MIN(CASE WHEN TRIM(UPPER(ICD10_CODE))='O24' THEN DIAGNOSIS_DATE END) AS first_gdm_date,
           bool_or(TRIM(UPPER(ICD10_CODE))='E10') AS has_type1,
           bool_or(TRIM(UPPER(ICD10_CODE))='E11') AS has_e11,
           bool_or(TRIM(UPPER(ICD10_CODE)) IN ('E13','E14')) AS has_other_dm,
           bool_or(TRIM(UPPER(ICD10_CODE))='O24') AS has_gdm
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ('E10','E11','E13','E14','O24')
    GROUP BY PATIENTUID
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
)
SELECT pop.*,
       COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
       dx.first_any_dm_date, dx.first_e11_date, dx.first_e10_date, dx.first_gdm_date,
       COALESCE(dx.has_type1,FALSE) AS has_dm_type1,
       COALESCE(dx.has_e11,FALSE) AS has_dm_type2,
       COALESCE(dx.has_other_dm,FALSE) AS has_dm_other,
       COALESCE(dx.has_gdm,FALSE) AS has_gdm,
       (COALESCE(dx.has_type1,FALSE) OR COALESCE(dx.has_e11,FALSE)
     OR COALESCE(dx.has_other_dm,FALSE) OR COALESCE(dx.has_gdm,FALSE)) AS has_any_dm_diagnosis,
       CASE WHEN pop.is_in_total_population AND NOT (COALESCE(dx.has_type1,FALSE) OR COALESCE(dx.has_e11,FALSE)
          OR COALESCE(dx.has_other_dm,FALSE) OR COALESCE(dx.has_gdm,FALSE)) THEN TRUE ELSE FALSE END AS is_in_at_risk,
       CASE WHEN pop.is_in_total_population AND (COALESCE(dx.has_type1,FALSE) OR COALESCE(dx.has_e11,FALSE)
          OR COALESCE(dx.has_other_dm,FALSE) OR COALESCE(dx.has_gdm,FALSE)) THEN TRUE ELSE FALSE END AS is_dm_prevalent
FROM pop LEFT JOIN dx USING (patient_key) LEFT JOIN phc USING (patient_key)
""")
print(f"  stg_dm_cohort:              {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dm_cohort').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_labs AS
SELECT lr.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       CASE
           WHEN lrv.NAME IN ('Fasting glucose','Fasting glucose [Mass or Moles/volume] in Serum or Plasma','GLUCOSE FASTING') THEN 'FBS'
           WHEN lrv.NAME = 'Hemoglobin A1c.' THEN 'A1C'
       END AS result_name,
       NULLIF(TRY_CAST(regexp_extract(lrv.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'LABRESULTS' AS source_table
FROM NMR.LEANHIS_LABRESULTS lr
JOIN NMR.LEANHIS_LABRESULTS_RESULTVALUES lrv ON lr._ID = lrv.LABRESULTS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON lr.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND lrv.NAME IN ('Fasting glucose','Fasting glucose [Mass or Moles/volume] in Serum or Plasma','GLUCOSE FASTING','Hemoglobin A1c.')
UNION ALL
SELECT o.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       CASE
           WHEN ov.NAME IN ('Fasting glucose','Fasting glucose [Mass or Moles/volume] in Serum or Plasma','GLUCOSE FASTING') THEN 'FBS'
           WHEN ov.NAME = 'Hemoglobin A1c.' THEN 'A1C'
       END AS result_name,
       NULLIF(TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'OBSERVATIONS' AS source_table
FROM NMR.LEANHIS_OBSERVATIONS o
JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND ov.NAME IN ('Fasting glucose','Hemoglobin A1c.')
""")
print(f"  stg_dm_labs:                {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dm_labs').fetchone()[0]} rows")

# =====================================================================
# DM — ANALYTICAL
# =====================================================================
print("--- DM Analytical ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_patient_month AS
WITH visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
monthly_labs AS (
    SELECT patient_key, year_month_key,
           MAX(CASE WHEN result_name='FBS' THEN result_value END) AS last_fbs_value,
           MAX(CASE WHEN result_name='A1C' THEN result_value END) AS last_a1c_value,
           bool_or(result_name='FBS') AS had_fbs,
           bool_or(result_name='A1C') AS had_a1c
    FROM CHI_REPORTING.stg_dm_labs
    WHERE result_value IS NOT NULL
    GROUP BY patient_key, year_month_key
),
spine AS (
    SELECT bc.*, m.year_month_key, m.report_month,
           CASE WHEN bc.first_any_dm_date IS NOT NULL
                 AND bc.first_any_dm_date < strptime(m.year_month_key::VARCHAR, '%Y%m')
                THEN TRUE ELSE FALSE END AS has_any_dm_before,
           CASE WHEN bc.first_e11_date IS NOT NULL
                 AND bc.first_e11_date < strptime(m.year_month_key::VARCHAR, '%Y%m')
                THEN TRUE ELSE FALSE END AS has_e11_before,
           CASE WHEN NOT (bc.first_any_dm_date IS NOT NULL
                 AND bc.first_any_dm_date < strptime(m.year_month_key::VARCHAR, '%Y%m'))
                THEN TRUE ELSE FALSE END AS is_at_risk_start
    FROM CHI_REPORTING.stg_dm_cohort bc
    CROSS JOIN (
        SELECT seq AS report_month, 2025*100+seq AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
)
SELECT pms.*,
       CASE WHEN v.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
       COALESCE(ml.had_fbs,FALSE) AS had_fbs,
       COALESCE(ml.had_a1c,FALSE) AS had_a1c,
       ml.last_fbs_value, ml.last_a1c_value,
       CASE WHEN pms.is_at_risk_start AND (COALESCE(ml.had_fbs,FALSE) OR COALESCE(ml.had_a1c,FALSE))
            THEN TRUE ELSE FALSE END AS is_screened,
       -- FBS category (dual-unit: mmol/L if <30, mg/dL if >=30)
       CASE WHEN ml.last_fbs_value IS NULL THEN NULL
            WHEN ml.last_fbs_value < 30 THEN
                CASE WHEN ml.last_fbs_value <= 5.5 THEN 'normal'
                     WHEN ml.last_fbs_value <= 6.9 THEN 'elevated'
                     ELSE 'abnormal' END
            ELSE
                CASE WHEN ml.last_fbs_value <= 99 THEN 'normal'
                     WHEN ml.last_fbs_value <= 125 THEN 'elevated'
                     ELSE 'abnormal' END
       END AS fbs_category,
       -- A1C category
       CASE WHEN ml.last_a1c_value IS NULL THEN NULL
            WHEN ml.last_a1c_value < 5.7 THEN 'normal'
            WHEN ml.last_a1c_value <= 6.4 THEN 'elevated'
            ELSE 'abnormal' END AS a1c_category,
       -- Overall: GREATEST (worst) of FBS and A1C
       CASE GREATEST(
           COALESCE(CASE WHEN a1c_category IS NULL THEN 0
                         WHEN a1c_category='normal' THEN 1
                         WHEN a1c_category='elevated' THEN 2 ELSE 3 END, 0),
           COALESCE(CASE WHEN fbs_category IS NULL THEN 0
                         WHEN fbs_category='normal' THEN 1
                         WHEN fbs_category='elevated' THEN 2 ELSE 3 END, 0)
       ) WHEN 3 THEN 'abnormal' WHEN 2 THEN 'elevated' WHEN 1 THEN 'normal' END AS screening_category,
       -- Incidence: first-ever E11 this month while at-risk
       CASE WHEN pms.first_e11_date IS NOT NULL
             AND pms.first_e11_date >= strptime(pms.year_month_key::VARCHAR, '%Y%m')
             AND pms.first_e11_date < strptime(pms.year_month_key::VARCHAR, '%Y%m') + INTERVAL 1 MONTH
             AND pms.is_at_risk_start
            THEN TRUE ELSE FALSE END AS is_incident_case
FROM spine pms
LEFT JOIN visits v ON pms.patient_key=v.patient_key AND pms.year_month_key=v.year_month_key
LEFT JOIN monthly_labs ml ON pms.patient_key=ml.patient_key AND pms.year_month_key=ml.year_month_key
""")
print(f"  stg_dm_patient_month:      {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dm_patient_month').fetchone()[0]} rows")

# =====================================================================
# DM — REPORTS
# =====================================================================
print("--- DM Reports ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_screening_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_screened THEN patient_key END) AS screened,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='normal' THEN patient_key END) AS normal_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='elevated' THEN patient_key END) AS elevated_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='abnormal' THEN patient_key END) AS case_n,
           ROUND(screened*100.0/NULLIF(at_risk,0),2) AS scr_rate,
           ROUND(case_n*100.0/NULLIF(screened,0),2) AS case_rate
    FROM CHI_REPORTING.stg_dm_patient_month
    GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, screened, normal_n, elevated_n, case_n, scr_rate, case_rate,
       year_month_key AS sort_key, 0 AS sort_order
FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2),
       99999, 1
FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2),
       99999, 2
FROM m ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_dm_screening_monthly:  {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_dm_screening_monthly').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_prevalence_annual AS
WITH snap AS (
    SELECT patient_key,
           CASE WHEN first_e11_date IS NOT NULL AND first_e11_date < '2026-01-01' THEN TRUE ELSE FALSE END AS has_e11,
           CASE WHEN first_e11_date >= '2025-01-01' AND first_e11_date < '2026-01-01' THEN TRUE ELSE FALSE END AS incident_yr,
           CASE WHEN first_e11_date < '2025-01-01' THEN TRUE ELSE FALSE END AS pre_existing
    FROM CHI_REPORTING.stg_dm_cohort
)
SELECT 2025 AS year, bc.health_cluster,
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END) AS total_pop,
       COUNT(DISTINCT CASE WHEN s.has_e11 THEN bc.patient_key END) AS prevalent,
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END) AS incident_during_year,
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e11 THEN bc.patient_key END) AS pre_existing_count,
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e11 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2) AS prev_rate,
       bc.health_cluster AS period_label, 0 AS sort_order
FROM CHI_REPORTING.stg_dm_cohort bc
LEFT JOIN snap s USING (patient_key)
GROUP BY bc.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.has_e11 THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e11 THEN bc.patient_key END),
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e11 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2),
       '── 2025 ALL CLUSTERS ──', 2
FROM CHI_REPORTING.stg_dm_cohort bc
LEFT JOIN snap s USING (patient_key)
ORDER BY health_cluster, sort_order
""")
print(f"  rpt_dm_prevalence_annual:  {con.execute('SELECT * FROM CHI_REPORTING.rpt_dm_prevalence_annual WHERE sort_order=2').fetchone()}")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_incidence_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_incident_case THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0),2) AS rate
    FROM CHI_REPORTING.stg_dm_patient_month
    GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate, year_month_key AS sort_key, 0 AS sort_order
FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 1
FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 2
FROM m ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_dm_incidence_monthly:  {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_dm_incidence_monthly').fetchone()[0]} rows")

# =====================================================================
# DM — MONITORING (COMPLIANCE & CARE GAP)
# =====================================================================
print("--- DM Monitoring ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_control_patient AS
WITH most_recent_a1c AS (
    SELECT pm.patient_key, pm.health_cluster, pm.gender,
           arg_max(pm.last_a1c_value,
               CASE WHEN pm.last_a1c_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS year_end_a1c,
           bool_or(pm.had_a1c) AS had_any_a1c
    FROM CHI_REPORTING.stg_dm_patient_month pm
    WHERE pm.is_dm_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, pm.gender
),
classified AS (
    SELECT mr.*, t.level_order, t.label AS control_level_label
    FROM most_recent_a1c mr
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition = 'dm' AND t.marker = 'a1c'
        AND (t.gender = 'All' OR t.gender = mr.gender)
        AND (t.min_value IS NULL OR mr.year_end_a1c >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_a1c < t.max_value)
)
SELECT patient_key, health_cluster, gender, year_end_a1c, had_any_a1c,
       COALESCE(control_level_label, 'Not Monitored') AS control_level,
       COALESCE(level_order, -1) AS control_level_order
FROM classified
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dm_care_gap_quarterly AS
WITH quarterly_followup AS (
    SELECT pm.patient_key, pm.health_cluster,
           CASE WHEN pm.report_month BETWEEN 1 AND 3 THEN 1
                WHEN pm.report_month BETWEEN 4 AND 6 THEN 2
                WHEN pm.report_month BETWEEN 7 AND 9 THEN 3
                ELSE 4 END AS quarter,
           bool_or(pm.had_a1c) AS quarter_completed
    FROM CHI_REPORTING.stg_dm_patient_month pm
    WHERE pm.is_dm_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, quarter
)
SELECT patient_key, health_cluster, 2025 AS report_year,
       SUM(CASE WHEN quarter_completed THEN 1 ELSE 0 END) AS quarters_completed,
       MAX(CASE WHEN quarter=1 AND quarter_completed THEN 1 ELSE 0 END) AS q1_completed,
       MAX(CASE WHEN quarter=2 AND quarter_completed THEN 1 ELSE 0 END) AS q2_completed,
       MAX(CASE WHEN quarter=3 AND quarter_completed THEN 1 ELSE 0 END) AS q3_completed,
       MAX(CASE WHEN quarter=4 AND quarter_completed THEN 1 ELSE 0 END) AS q4_completed
FROM quarterly_followup GROUP BY patient_key, health_cluster
""")

# rpt_dm_control
con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_control AS
WITH control_metrics AS (
    SELECT health_cluster, control_level, control_level_order, COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_dm_control_patient GROUP BY health_cluster, control_level, control_level_order
),
prevalent_counts AS (
    SELECT health_cluster, COUNT(*) AS prevalent_total
    FROM CHI_REPORTING.stg_dm_control_patient GROUP BY health_cluster
)
SELECT 2025 AS year, cm.health_cluster, cm.control_level, cm.control_level_order AS control_level_order_int,
       cm.patient_count,
       ROUND(cm.patient_count * 100.0 / NULLIF(pc.prevalent_total, 0), 2) AS pct_of_prevalent,
       0 AS sort_order
FROM control_metrics cm JOIN prevalent_counts pc USING (health_cluster)
UNION ALL
SELECT 2025, cm.health_cluster, '── ' || cm.health_cluster || ' TOTAL ──', 99,
       SUM(cm.patient_count), 100.0, 1
FROM control_metrics cm GROUP BY cm.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', 99,
       SUM(cm.patient_count), 100.0, 2
FROM control_metrics cm ORDER BY health_cluster, sort_order, control_level_order_int
""")

# rpt_dm_care_gap_quarterly
con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_care_gap_quarterly AS
WITH quarterly_metrics AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prevalent_count,
           SUM(cg.q1_completed) AS completed_count,
           COUNT(*) - SUM(cg.q1_completed) AS gap_count,
           ROUND(SUM(cg.q1_completed) * 100.0 / NULLIF(COUNT(*), 0), 2) AS completion_rate_pct
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed),
           COUNT(*) - SUM(cg.q2_completed),
           ROUND(SUM(cg.q2_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed),
           COUNT(*) - SUM(cg.q3_completed),
           ROUND(SUM(cg.q3_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL
    SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed),
           COUNT(*) - SUM(cg.q4_completed),
           ROUND(SUM(cg.q4_completed) * 100.0 / NULLIF(COUNT(*), 0), 2)
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg GROUP BY cg.health_cluster
)
SELECT 2025 AS year, qm.health_cluster, qm.quarter,
       qm.prevalent_count, qm.completed_count, qm.gap_count,
       qm.completion_rate_pct, qm.quarter AS sort_key, 0 AS sort_order
FROM quarterly_metrics qm
UNION ALL
SELECT 2025, qm.health_cluster, NULL,
       MAX(qm.prevalent_count), SUM(qm.completed_count), SUM(qm.gap_count),
       ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2),
       99, 1
FROM quarterly_metrics qm GROUP BY qm.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──', NULL,
       MAX(qm.prevalent_count), SUM(qm.completed_count), SUM(qm.gap_count),
       ROUND(SUM(qm.completed_count) * 100.0 / NULLIF(SUM(qm.prevalent_count), 0), 2),
       99, 2
FROM quarterly_metrics qm ORDER BY health_cluster, sort_order, sort_key
""")

# rpt_dm_care_gap_annual
con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dm_care_gap_annual AS
WITH patient_summary AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= 3 AS meets_target
    FROM CHI_REPORTING.stg_dm_care_gap_quarterly cg
),
annual_metrics AS (
    SELECT health_cluster, quarters_completed, COUNT(*) AS patient_count,
           ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY health_cluster), 0), 2) AS pct_of_prevalent
    FROM patient_summary GROUP BY health_cluster, quarters_completed
)
SELECT 2025 AS year, am.health_cluster, am.quarters_completed,
       am.patient_count, am.pct_of_prevalent, am.quarters_completed AS sort_key, 0 AS sort_order
FROM annual_metrics am
UNION ALL
SELECT 2025, ps.health_cluster, '≥ Target',
       SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2),
       99, 1
FROM patient_summary ps GROUP BY ps.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──',
       SUM(am.patient_count), 100.0, 100, 2
FROM annual_metrics am ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  stg_dm_control_patient:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dm_control_patient').fetchone()[0]} rows")
print(f"  stg_dm_care_gap_quarterly:  {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dm_care_gap_quarterly').fetchone()[0]} rows")
print(f"  rpt_dm_control:             {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_dm_control').fetchone()[0]} rows")
print(f"  rpt_dm_care_gap_quarterly:  {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_dm_care_gap_quarterly').fetchone()[0]} rows")
print(f"  rpt_dm_care_gap_annual:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_dm_care_gap_annual').fetchone()[0]} rows")

# =====================================================================
# HTN — STAGING
# =====================================================================
print("\n--- HTN Staging ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_cohort AS
WITH pop AS (
    SELECT _ID AS patient_key, GENDERUID AS gender, DATEOFBIRTH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
dx AS (
    SELECT PATIENTUID AS patient_key,
           MIN(DIAGNOSIS_DATE) AS first_any_htn_date,
           MIN(CASE WHEN TRIM(UPPER(ICD10_CODE))='I10' THEN DIAGNOSIS_DATE END) AS first_i10_date,
           bool_or(TRIM(UPPER(ICD10_CODE))='I10') AS has_i10,
           bool_or(TRIM(UPPER(ICD10_CODE)) IN ('I11','I12','I13','I15')) AS has_other_htn
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ('I10','I11','I12','I13','I15')
    GROUP BY PATIENTUID
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
)
SELECT pop.*,
       COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
       dx.first_any_htn_date, dx.first_i10_date,
       COALESCE(dx.has_i10,FALSE) AS has_i10,
       COALESCE(dx.has_other_htn,FALSE) AS has_other_htn,
       (COALESCE(dx.has_i10,FALSE) OR COALESCE(dx.has_other_htn,FALSE)) AS has_any_htn_diagnosis,
       CASE WHEN pop.is_in_total_population AND NOT (COALESCE(dx.has_i10,FALSE) OR COALESCE(dx.has_other_htn,FALSE))
            THEN TRUE ELSE FALSE END AS is_in_at_risk,
       CASE WHEN pop.is_in_total_population AND (COALESCE(dx.has_i10,FALSE) OR COALESCE(dx.has_other_htn,FALSE))
            THEN TRUE ELSE FALSE END AS is_htn_prevalent
FROM pop LEFT JOIN dx USING (patient_key) LEFT JOIN phc USING (patient_key)
""")
print(f"  stg_htn_cohort:             {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_htn_cohort').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_labs AS
SELECT o.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       CASE WHEN ov.NAME='Systolic BP' THEN 'SYS' WHEN ov.NAME='Diastolic BP' THEN 'DIA' END AS result_name,
       NULLIF(TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'OBSERVATIONS' AS source_table
FROM NMR.LEANHIS_OBSERVATIONS o
JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND ov.NAME IN ('Systolic BP','Diastolic BP') AND ov.RESULTVALUE IS NOT NULL
""")
print(f"  stg_htn_labs:               {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_htn_labs').fetchone()[0]} rows")

# =====================================================================
# HTN — ANALYTICAL
# =====================================================================
print("--- HTN Analytical ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_patient_month AS
WITH visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
bp_visit AS (
    SELECT patient_key, visit_date, year_month_key,
           MAX(CASE WHEN result_name='SYS' THEN result_value END) AS sys_value,
           MAX(CASE WHEN result_name='DIA' THEN result_value END) AS dia_value
    FROM CHI_REPORTING.stg_htn_labs
    WHERE result_value IS NOT NULL
    GROUP BY patient_key, visit_date, year_month_key
    HAVING sys_value IS NOT NULL AND dia_value IS NOT NULL
),
monthly_bp AS (
    SELECT patient_key, year_month_key,
           arg_max(sys_value, visit_date) AS last_sys,
           arg_max(dia_value, visit_date) AS last_dia,
           bool_or(TRUE) AS had_bp
    FROM bp_visit GROUP BY patient_key, year_month_key
),
spine AS (
    SELECT bc.*, m.year_month_key, m.report_month,
           CASE WHEN bc.first_any_htn_date IS NOT NULL
                 AND bc.first_any_htn_date < strptime(m.year_month_key::VARCHAR,'%Y%m')
                THEN TRUE ELSE FALSE END AS has_htn_before,
           CASE WHEN NOT (bc.first_any_htn_date IS NOT NULL
                 AND bc.first_any_htn_date < strptime(m.year_month_key::VARCHAR,'%Y%m'))
                THEN TRUE ELSE FALSE END AS is_at_risk_start
    FROM CHI_REPORTING.stg_htn_cohort bc
    CROSS JOIN (
        SELECT seq AS report_month, 2025*100+seq AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
)
SELECT pms.*,
       CASE WHEN v.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
       COALESCE(mb.had_bp,FALSE) AS had_bp,
       mb.last_sys AS last_sys_value, mb.last_dia AS last_dia_value,
       CASE WHEN pms.is_at_risk_start AND COALESCE(mb.had_bp,FALSE) THEN TRUE ELSE FALSE END AS is_screened,
       CASE WHEN mb.last_sys IS NULL OR mb.last_dia IS NULL THEN NULL
            WHEN mb.last_sys >= 130 OR mb.last_dia >= 90 THEN 'abnormal'
            WHEN (mb.last_sys BETWEEN 120 AND 129) OR (mb.last_dia BETWEEN 80 AND 89) THEN 'elevated'
            ELSE 'normal' END AS screening_category,
       CASE WHEN pms.first_i10_date IS NOT NULL
             AND pms.first_i10_date >= strptime(pms.year_month_key::VARCHAR,'%Y%m')
             AND pms.first_i10_date < strptime(pms.year_month_key::VARCHAR,'%Y%m') + INTERVAL 1 MONTH
             AND pms.is_at_risk_start
            THEN TRUE ELSE FALSE END AS is_incident_case
FROM spine pms
LEFT JOIN visits v ON pms.patient_key=v.patient_key AND pms.year_month_key=v.year_month_key
LEFT JOIN monthly_bp mb ON pms.patient_key=mb.patient_key AND pms.year_month_key=mb.year_month_key
""")
print(f"  stg_htn_patient_month:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_htn_patient_month').fetchone()[0]} rows")

# =====================================================================
# HTN — REPORTS
# =====================================================================
print("--- HTN Reports ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_screening_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_screened THEN patient_key END) AS screened,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='normal' THEN patient_key END) AS normal_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='elevated' THEN patient_key END) AS elevated_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='abnormal' THEN patient_key END) AS case_n,
           ROUND(screened*100.0/NULLIF(at_risk,0),2) AS scr_rate,
           ROUND(case_n*100.0/NULLIF(screened,0),2) AS case_rate
    FROM CHI_REPORTING.stg_htn_patient_month
    GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, screened, normal_n, elevated_n, case_n, scr_rate, case_rate,
       year_month_key AS sort_key, 0 AS sort_order
FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2),
       99999, 1
FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2),
       99999, 2
FROM m ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_prevalence_annual AS
WITH snap AS (
    SELECT patient_key,
           CASE WHEN first_i10_date IS NOT NULL AND first_i10_date < '2026-01-01' THEN TRUE ELSE FALSE END AS has_i10,
           CASE WHEN first_i10_date >= '2025-01-01' AND first_i10_date < '2026-01-01' THEN TRUE ELSE FALSE END AS incident_yr,
           CASE WHEN first_i10_date < '2025-01-01' THEN TRUE ELSE FALSE END AS pre_existing
    FROM CHI_REPORTING.stg_htn_cohort
)
SELECT 2025 AS year, bc.health_cluster,
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END) AS total_pop,
       COUNT(DISTINCT CASE WHEN s.has_i10 THEN bc.patient_key END) AS prevalent,
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END) AS incident_during_year,
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_i10 THEN bc.patient_key END) AS pre_existing_count,
       ROUND(prevalent*100.0/NULLIF(total_pop,0),2) AS prev_rate,
       bc.health_cluster AS period_label, 0 AS sort_order
FROM CHI_REPORTING.stg_htn_cohort bc LEFT JOIN snap s USING (patient_key)
GROUP BY bc.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.has_i10 THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_i10 THEN bc.patient_key END),
       ROUND(COUNT(DISTINCT CASE WHEN s.has_i10 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2),
       '── 2025 ALL CLUSTERS ──', 2
FROM CHI_REPORTING.stg_htn_cohort bc LEFT JOIN snap s USING (patient_key)
ORDER BY health_cluster, sort_order
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_incidence_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_incident_case THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0),2) AS rate
    FROM CHI_REPORTING.stg_htn_patient_month GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate, year_month_key AS sort_key, 0 AS sort_order
FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 1
FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 2
FROM m ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_htn_prevalence_annual: {con.execute('SELECT * FROM CHI_REPORTING.rpt_htn_prevalence_annual WHERE sort_order=2').fetchone()}")

# =====================================================================
# HTN — MONITORING (COMPLIANCE & CARE GAP)
# =====================================================================
print("--- HTN Monitoring ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_control_patient AS
WITH most_recent_bp AS (
    SELECT pm.patient_key, pm.health_cluster,
           arg_max(pm.last_sys_value,
               CASE WHEN pm.last_sys_value IS NOT NULL AND pm.last_dia_value IS NOT NULL
                    THEN pm.year_month_key ELSE 0 END) AS year_end_sys,
           arg_max(pm.last_dia_value,
               CASE WHEN pm.last_sys_value IS NOT NULL AND pm.last_dia_value IS NOT NULL
                    THEN pm.year_month_key ELSE 0 END) AS year_end_dia,
           bool_or(pm.had_bp) AS had_any_bp
    FROM CHI_REPORTING.stg_htn_patient_month pm
    WHERE pm.is_htn_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster
),
c_sys AS (
    SELECT mr.*, t.level_order AS sys_level, t.label AS sys_label
    FROM most_recent_bp mr
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='htn' AND t.marker='sys'
        AND (t.min_value IS NULL OR mr.year_end_sys >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_sys < t.max_value)
),
c_dia AS (
    SELECT cs.*, t.level_order AS dia_level, t.label AS dia_label
    FROM c_sys cs
    LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='htn' AND t.marker='dia'
        AND (t.min_value IS NULL OR cs.year_end_dia >= t.min_value)
        AND (t.max_value IS NULL OR cs.year_end_dia < t.max_value)
)
SELECT patient_key, health_cluster, year_end_sys, year_end_dia, had_any_bp,
       sys_label, dia_label,
       COALESCE(sys_level, -1) AS sys_level_order,
       COALESCE(dia_level, -1) AS dia_level_order,
       GREATEST(COALESCE(sys_level, -1), COALESCE(dia_level, -1)) AS overall_level_order,
       CASE GREATEST(COALESCE(sys_level, -1), COALESCE(dia_level, -1))
           WHEN -1 THEN 'Not Monitored'
           WHEN 0 THEN CASE WHEN COALESCE(sys_level,-1) > COALESCE(dia_level,-1) THEN sys_label ELSE dia_label END
           ELSE CASE WHEN COALESCE(sys_level,-1) >= COALESCE(dia_level,-1) THEN sys_label ELSE dia_label END
       END AS control_level
FROM c_dia
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_htn_care_gap_quarterly AS
WITH qf AS (
    SELECT pm.patient_key, pm.health_cluster,
           CASE WHEN pm.report_month BETWEEN 1 AND 3 THEN 1
                WHEN pm.report_month BETWEEN 4 AND 6 THEN 2
                WHEN pm.report_month BETWEEN 7 AND 9 THEN 3 ELSE 4 END AS quarter,
           bool_or(pm.had_bp) AS quarter_completed
    FROM CHI_REPORTING.stg_htn_patient_month pm
    WHERE pm.is_htn_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, quarter
)
SELECT patient_key, health_cluster, 2025 AS report_year,
       SUM(CASE WHEN quarter_completed THEN 1 ELSE 0 END) AS quarters_completed,
       MAX(CASE WHEN quarter=1 AND quarter_completed THEN 1 ELSE 0 END) AS q1_completed,
       MAX(CASE WHEN quarter=2 AND quarter_completed THEN 1 ELSE 0 END) AS q2_completed,
       MAX(CASE WHEN quarter=3 AND quarter_completed THEN 1 ELSE 0 END) AS q3_completed,
       MAX(CASE WHEN quarter=4 AND quarter_completed THEN 1 ELSE 0 END) AS q4_completed
FROM qf GROUP BY patient_key, health_cluster
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_control AS
WITH cm AS (
    SELECT health_cluster, control_level, overall_level_order, COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_htn_control_patient GROUP BY health_cluster, control_level, overall_level_order
),
pc AS (SELECT health_cluster, COUNT(*) AS tot FROM CHI_REPORTING.stg_htn_control_patient GROUP BY health_cluster)
SELECT 2025 AS year, cm.health_cluster, cm.control_level, cm.overall_level_order AS control_level_order_int,
       cm.patient_count, ROUND(cm.patient_count*100.0/NULLIF(pc.tot,0),2) AS pct_of_prevalent, 0 AS sort_order
FROM cm JOIN pc USING (health_cluster)
UNION ALL SELECT 2025, cm.health_cluster, '── '||cm.health_cluster||' TOTAL ──', 99, SUM(cm.patient_count), 100.0, 1 FROM cm GROUP BY cm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', 99, SUM(cm.patient_count), 100.0, 2 FROM cm
ORDER BY health_cluster, sort_order, control_level_order_int
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_care_gap_quarterly AS
WITH qm AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prev, SUM(cg.q1_completed) AS comp,
           COUNT(*)-SUM(cg.q1_completed) AS gap,
           ROUND(SUM(cg.q1_completed)*100.0/NULLIF(COUNT(*),0),2) AS rate
    FROM CHI_REPORTING.stg_htn_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed), COUNT(*)-SUM(cg.q2_completed), ROUND(SUM(cg.q2_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_htn_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed), COUNT(*)-SUM(cg.q3_completed), ROUND(SUM(cg.q3_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_htn_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed), COUNT(*)-SUM(cg.q4_completed), ROUND(SUM(cg.q4_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_htn_care_gap_quarterly cg GROUP BY cg.health_cluster
)
SELECT 2025 AS year, qm.health_cluster, qm.quarter, qm.prev, qm.comp, qm.gap, qm.rate, qm.quarter AS sort_key, 0 AS sort_order FROM qm
UNION ALL SELECT 2025, qm.health_cluster, NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 1 FROM qm GROUP BY qm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 2 FROM qm ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_htn_care_gap_annual AS
WITH ps AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= 3 AS meets_target
    FROM CHI_REPORTING.stg_htn_care_gap_quarterly cg
),
am AS (
    SELECT health_cluster, quarters_completed, COUNT(*) AS patient_count,
           ROUND(COUNT(*)*100.0/NULLIF(SUM(COUNT(*)) OVER (PARTITION BY health_cluster),0),2) AS pct_of_prevalent
    FROM ps GROUP BY health_cluster, quarters_completed
)
SELECT 2025 AS year, am.health_cluster, am.quarters_completed, am.patient_count, am.pct_of_prevalent, am.quarters_completed AS sort_key, 0 AS sort_order FROM am
UNION ALL SELECT 2025, ps.health_cluster, '≥ Target', SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END), ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),2), 99, 1 FROM ps GROUP BY ps.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', SUM(am.patient_count), 100.0, 100, 2 FROM am ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  stg_htn_control_patient:    {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_htn_control_patient').fetchone()[0]} rows")
print(f"  stg_htn_care_gap_quarterly: {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_htn_care_gap_quarterly').fetchone()[0]} rows")

# =====================================================================
# DLP — STAGING
# =====================================================================
print("\n--- DLP Staging ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_cohort AS
WITH pop AS (
    SELECT _ID AS patient_key, GENDERUID AS gender, DATEOFBIRTH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_e78_date,
           MIN(DIAGNOSIS_DATE) AS first_any_dlp_date, TRUE AS has_e78
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E78' GROUP BY PATIENTUID
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
)
SELECT pop.*,
       COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
       dx.first_any_dlp_date, dx.first_e78_date,
       COALESCE(dx.has_e78,FALSE) AS has_e78,
       COALESCE(dx.has_e78,FALSE) AS has_any_dlp_diagnosis,
       CASE WHEN pop.is_in_total_population AND NOT COALESCE(dx.has_e78,FALSE) THEN TRUE ELSE FALSE END AS is_in_at_risk,
       CASE WHEN pop.is_in_total_population AND COALESCE(dx.has_e78,FALSE) THEN TRUE ELSE FALSE END AS is_dlp_prevalent
FROM pop LEFT JOIN dx USING (patient_key) LEFT JOIN phc USING (patient_key)
""")
print(f"  stg_dlp_cohort:             {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dlp_cohort').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_labs AS
SELECT lr.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       CASE
           WHEN lrv.NAME IN ('Cholesterol.in HDL','Cholesterol in HDL') THEN 'HDL'
           WHEN lrv.NAME IN ('Cholesterol.in LDL','Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay') THEN 'LDL'
           WHEN lrv.NAME = 'Cholesterol in Serum or Plasma' THEN 'CHOL'
           WHEN lrv.NAME = 'Triglyceride' THEN 'TRIG'
       END AS result_name,
       NULLIF(TRY_CAST(regexp_extract(lrv.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'LABRESULTS' AS source_table
FROM NMR.LEANHIS_LABRESULTS lr
JOIN NMR.LEANHIS_LABRESULTS_RESULTVALUES lrv ON lr._ID = lrv.LABRESULTS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON lr.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND lrv.NAME IN ('Cholesterol.in HDL','Cholesterol in HDL','Cholesterol.in LDL',
       'Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay',
       'Cholesterol in Serum or Plasma','Triglyceride')
UNION ALL
SELECT o.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       CASE
           WHEN ov.NAME IN ('Cholesterol.in HDL','Cholesterol in HDL') THEN 'HDL'
           WHEN ov.NAME = 'Triglyceride' THEN 'TRIG'
       END AS result_name,
       NULLIF(TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'OBSERVATIONS' AS source_table
FROM NMR.LEANHIS_OBSERVATIONS o
JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND ov.NAME IN ('Cholesterol.in HDL','Cholesterol in HDL','Triglyceride')
""")
print(f"  stg_dlp_labs:               {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dlp_labs').fetchone()[0]} rows")

# =====================================================================
# DLP — ANALYTICAL
# =====================================================================
print("--- DLP Analytical ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_patient_month AS
WITH visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
monthly_lipids AS (
    SELECT patient_key, year_month_key,
           MAX(CASE WHEN result_name='HDL' THEN result_value END) AS last_hdl_value,
           MAX(CASE WHEN result_name='LDL' THEN result_value END) AS last_ldl_value,
           MAX(CASE WHEN result_name='CHOL' THEN result_value END) AS last_chol_value,
           MAX(CASE WHEN result_name='TRIG' THEN result_value END) AS last_trig_value,
           bool_or(result_name='HDL') AS had_hdl, bool_or(result_name='LDL') AS had_ldl,
           bool_or(result_name='CHOL') AS had_chol, bool_or(result_name='TRIG') AS had_trig
    FROM CHI_REPORTING.stg_dlp_labs WHERE result_value IS NOT NULL
    GROUP BY patient_key, year_month_key
),
spine AS (
    SELECT bc.*, m.year_month_key, m.report_month,
           CASE WHEN bc.first_any_dlp_date IS NOT NULL
                 AND bc.first_any_dlp_date < strptime(m.year_month_key::VARCHAR,'%Y%m')
                THEN TRUE ELSE FALSE END AS has_dlp_before,
           CASE WHEN NOT (bc.first_any_dlp_date IS NOT NULL
                 AND bc.first_any_dlp_date < strptime(m.year_month_key::VARCHAR,'%Y%m'))
                THEN TRUE ELSE FALSE END AS is_at_risk_start
    FROM CHI_REPORTING.stg_dlp_cohort bc
    CROSS JOIN (
        SELECT seq AS report_month, 2025*100+seq AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
)
SELECT pms.*,
       CASE WHEN v.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
       COALESCE(ml.had_hdl,FALSE) AS had_hdl, COALESCE(ml.had_ldl,FALSE) AS had_ldl,
       COALESCE(ml.had_chol,FALSE) AS had_chol, COALESCE(ml.had_trig,FALSE) AS had_trig,
       ml.last_hdl_value, ml.last_ldl_value, ml.last_chol_value, ml.last_trig_value,
       CASE WHEN pms.is_at_risk_start AND (COALESCE(ml.had_hdl,FALSE) OR COALESCE(ml.had_ldl,FALSE))
            THEN TRUE ELSE FALSE END AS is_screened,
       CASE GREATEST(
           COALESCE(CASE WHEN ml.last_hdl_value IS NULL THEN 0
                         WHEN pms.gender='Male' AND ml.last_hdl_value >= 40 THEN 1
                         WHEN pms.gender='Female' AND ml.last_hdl_value >= 50 THEN 1
                         ELSE 3 END, 0),
           COALESCE(CASE WHEN ml.last_trig_value IS NULL THEN 0
                         WHEN ml.last_trig_value < 150 THEN 1
                         WHEN ml.last_trig_value <= 199 THEN 2 ELSE 3 END, 0),
           COALESCE(CASE WHEN ml.last_chol_value IS NULL THEN 0
                         WHEN ml.last_chol_value < 200 THEN 1
                         WHEN ml.last_chol_value <= 239 THEN 2 ELSE 3 END, 0),
           COALESCE(CASE WHEN ml.last_ldl_value IS NULL THEN 0
                         WHEN ml.last_ldl_value < 130 THEN 1
                         WHEN ml.last_ldl_value <= 159 THEN 2 ELSE 3 END, 0)
       ) WHEN 3 THEN 'abnormal' WHEN 2 THEN 'elevated' WHEN 1 THEN 'normal' END AS screening_category,
       CASE WHEN pms.first_e78_date IS NOT NULL
             AND pms.first_e78_date >= strptime(pms.year_month_key::VARCHAR,'%Y%m')
             AND pms.first_e78_date < strptime(pms.year_month_key::VARCHAR,'%Y%m') + INTERVAL 1 MONTH
             AND pms.is_at_risk_start
            THEN TRUE ELSE FALSE END AS is_incident_case
FROM spine pms
LEFT JOIN visits v ON pms.patient_key=v.patient_key AND pms.year_month_key=v.year_month_key
LEFT JOIN monthly_lipids ml ON pms.patient_key=ml.patient_key AND pms.year_month_key=ml.year_month_key
""")
print(f"  stg_dlp_patient_month:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dlp_patient_month').fetchone()[0]} rows")

# =====================================================================
# DLP — REPORTS
# =====================================================================
print("--- DLP Reports ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_screening_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_screened THEN patient_key END) AS screened,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='normal' THEN patient_key END) AS normal_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='elevated' THEN patient_key END) AS elevated_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='abnormal' THEN patient_key END) AS case_n,
           ROUND(screened*100.0/NULLIF(at_risk,0),2) AS scr_rate,
           ROUND(case_n*100.0/NULLIF(screened,0),2) AS case_rate
    FROM CHI_REPORTING.stg_dlp_patient_month GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, screened, normal_n, elevated_n, case_n, scr_rate, case_rate,
       year_month_key AS sort_key, 0 AS sort_order FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2), 99999, 1 FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       SUM(at_risk), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2), 99999, 2 FROM m ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_prevalence_annual AS
WITH snap AS (
    SELECT patient_key,
           CASE WHEN first_e78_date IS NOT NULL AND first_e78_date < '2026-01-01' THEN TRUE ELSE FALSE END AS has_e78,
           CASE WHEN first_e78_date >= '2025-01-01' AND first_e78_date < '2026-01-01' THEN TRUE ELSE FALSE END AS incident_yr,
           CASE WHEN first_e78_date < '2025-01-01' THEN TRUE ELSE FALSE END AS pre_existing
    FROM CHI_REPORTING.stg_dlp_cohort
)
SELECT 2025 AS year, bc.health_cluster,
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END) AS total_pop,
       COUNT(DISTINCT CASE WHEN s.has_e78 THEN bc.patient_key END) AS prevalent,
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END) AS incident_during_year,
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e78 THEN bc.patient_key END) AS pre_existing_count,
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e78 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2) AS prev_rate,
       bc.health_cluster AS period_label, 0 AS sort_order
FROM CHI_REPORTING.stg_dlp_cohort bc LEFT JOIN snap s USING (patient_key)
GROUP BY bc.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.has_e78 THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e78 THEN bc.patient_key END),
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e78 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2),
       '── 2025 ALL CLUSTERS ──', 2
FROM CHI_REPORTING.stg_dlp_cohort bc LEFT JOIN snap s USING (patient_key)
ORDER BY health_cluster, sort_order
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_incidence_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_incident_case THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0),2) AS rate
    FROM CHI_REPORTING.stg_dlp_patient_month GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate, year_month_key AS sort_key, 0 AS sort_order FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 1 FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 2 FROM m ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_dlp_prevalence_annual: {con.execute('SELECT * FROM CHI_REPORTING.rpt_dlp_prevalence_annual WHERE sort_order=2').fetchone()}")

# =====================================================================
# DLP — MONITORING (COMPLIANCE & CARE GAP)
# =====================================================================
print("--- DLP Monitoring ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_control_patient AS
WITH mr AS (
    SELECT pm.patient_key, pm.health_cluster, pm.gender,
           arg_max(pm.last_hdl_value,
               CASE WHEN pm.last_hdl_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS y_hdl,
           arg_max(pm.last_ldl_value,
               CASE WHEN pm.last_ldl_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS y_ldl,
           arg_max(pm.last_chol_value,
               CASE WHEN pm.last_chol_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS y_chol,
           arg_max(pm.last_trig_value,
               CASE WHEN pm.last_trig_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS y_trig,
           bool_or(pm.had_hdl) AS h_hdl, bool_or(pm.had_ldl) AS h_ldl,
           bool_or(pm.had_chol) AS h_chol, bool_or(pm.had_trig) AS h_trig
    FROM CHI_REPORTING.stg_dlp_patient_month pm
    WHERE pm.is_dlp_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, pm.gender
),
c_hdl AS (
    SELECT mr.*, t.level_order AS hdl_lv, t.label AS hdl_lbl
    FROM mr LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='dlp' AND t.marker='hdl' AND (t.gender=mr.gender OR t.gender='All')
        AND (t.min_value IS NULL OR mr.y_hdl >= t.min_value)
        AND (t.max_value IS NULL OR mr.y_hdl < t.max_value)
),
c_ldl AS (
    SELECT ch.*, t.level_order AS ldl_lv, t.label AS ldl_lbl
    FROM c_hdl ch LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='dlp' AND t.marker='ldl' AND t.gender='All'
        AND (t.min_value IS NULL OR ch.y_ldl >= t.min_value)
        AND (t.max_value IS NULL OR ch.y_ldl < t.max_value)
),
c_chol AS (
    SELECT cl.*, t.level_order AS chol_lv, t.label AS chol_lbl
    FROM c_ldl cl LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='dlp' AND t.marker='chol' AND t.gender='All'
        AND (t.min_value IS NULL OR cl.y_chol >= t.min_value)
        AND (t.max_value IS NULL OR cl.y_chol < t.max_value)
),
c_trig AS (
    SELECT cc.*, t.level_order AS trig_lv, t.label AS trig_lbl
    FROM c_chol cc LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='dlp' AND t.marker='trig' AND t.gender='All'
        AND (t.min_value IS NULL OR cc.y_trig >= t.min_value)
        AND (t.max_value IS NULL OR cc.y_trig < t.max_value)
)
SELECT patient_key, health_cluster, gender,
       y_hdl, y_ldl, y_chol, y_trig,
       h_hdl OR h_ldl OR h_chol OR h_trig AS had_any_lipid,
       hdl_lbl, COALESCE(hdl_lv,-1) AS hdl_lv_o,
       ldl_lbl, COALESCE(ldl_lv,-1) AS ldl_lv_o,
       chol_lbl, COALESCE(chol_lv,-1) AS chol_lv_o,
       trig_lbl, COALESCE(trig_lv,-1) AS trig_lv_o,
       GREATEST(COALESCE(hdl_lv,-1),COALESCE(ldl_lv,-1),COALESCE(chol_lv,-1),COALESCE(trig_lv,-1)) AS overall_level_order,
       CASE GREATEST(COALESCE(hdl_lv,-1),COALESCE(ldl_lv,-1),COALESCE(chol_lv,-1),COALESCE(trig_lv,-1))
           WHEN -1 THEN 'Not Monitored'
           ELSE CASE
               WHEN COALESCE(ldl_lv,-1)>=COALESCE(hdl_lv,-1) AND COALESCE(ldl_lv,-1)>=COALESCE(chol_lv,-1) AND COALESCE(ldl_lv,-1)>=COALESCE(trig_lv,-1) THEN ldl_lbl
               WHEN COALESCE(chol_lv,-1)>=COALESCE(hdl_lv,-1) AND COALESCE(chol_lv,-1)>=COALESCE(ldl_lv,-1) AND COALESCE(chol_lv,-1)>=COALESCE(trig_lv,-1) THEN chol_lbl
               WHEN COALESCE(trig_lv,-1)>=COALESCE(hdl_lv,-1) AND COALESCE(trig_lv,-1)>=COALESCE(ldl_lv,-1) AND COALESCE(trig_lv,-1)>=COALESCE(chol_lv,-1) THEN trig_lbl
               ELSE hdl_lbl END
       END AS control_level
FROM c_trig
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_dlp_care_gap_quarterly AS
WITH qf AS (
    SELECT pm.patient_key, pm.health_cluster,
           CASE WHEN pm.report_month BETWEEN 1 AND 3 THEN 1
                WHEN pm.report_month BETWEEN 4 AND 6 THEN 2
                WHEN pm.report_month BETWEEN 7 AND 9 THEN 3 ELSE 4 END AS quarter,
           bool_or(pm.had_hdl OR pm.had_ldl OR pm.had_chol OR pm.had_trig) AS quarter_completed
    FROM CHI_REPORTING.stg_dlp_patient_month pm
    WHERE pm.is_dlp_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, quarter
)
SELECT patient_key, health_cluster, 2025 AS report_year,
       SUM(CASE WHEN quarter_completed THEN 1 ELSE 0 END) AS quarters_completed,
       MAX(CASE WHEN quarter=1 AND quarter_completed THEN 1 ELSE 0 END) AS q1_completed,
       MAX(CASE WHEN quarter=2 AND quarter_completed THEN 1 ELSE 0 END) AS q2_completed,
       MAX(CASE WHEN quarter=3 AND quarter_completed THEN 1 ELSE 0 END) AS q3_completed,
       MAX(CASE WHEN quarter=4 AND quarter_completed THEN 1 ELSE 0 END) AS q4_completed
FROM qf GROUP BY patient_key, health_cluster
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_control AS
WITH cm AS (
    SELECT health_cluster, control_level, overall_level_order, COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_dlp_control_patient GROUP BY health_cluster, control_level, overall_level_order
),
pc AS (SELECT health_cluster, COUNT(*) AS tot FROM CHI_REPORTING.stg_dlp_control_patient GROUP BY health_cluster)
SELECT 2025 AS year, cm.health_cluster, cm.control_level, cm.overall_level_order AS control_level_order_int,
       cm.patient_count, ROUND(cm.patient_count*100.0/NULLIF(pc.tot,0),2) AS pct_of_prevalent, 0 AS sort_order
FROM cm JOIN pc USING (health_cluster)
UNION ALL SELECT 2025, cm.health_cluster, '── '||cm.health_cluster||' TOTAL ──', 99, SUM(cm.patient_count), 100.0, 1 FROM cm GROUP BY cm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', 99, SUM(cm.patient_count), 100.0, 2 FROM cm
ORDER BY health_cluster, sort_order, control_level_order_int
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_care_gap_quarterly AS
WITH qm AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prev, SUM(cg.q1_completed) AS comp,
           COUNT(*)-SUM(cg.q1_completed) AS gap,
           ROUND(SUM(cg.q1_completed)*100.0/NULLIF(COUNT(*),0),2) AS rate
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed), COUNT(*)-SUM(cg.q2_completed), ROUND(SUM(cg.q2_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed), COUNT(*)-SUM(cg.q3_completed), ROUND(SUM(cg.q3_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed), COUNT(*)-SUM(cg.q4_completed), ROUND(SUM(cg.q4_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg GROUP BY cg.health_cluster
)
SELECT 2025 AS year, qm.health_cluster, qm.quarter, qm.prev, qm.comp, qm.gap, qm.rate, qm.quarter AS sort_key, 0 AS sort_order FROM qm
UNION ALL SELECT 2025, qm.health_cluster, NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 1 FROM qm GROUP BY qm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 2 FROM qm ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_dlp_care_gap_annual AS
WITH ps AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= 3 AS meets_target
    FROM CHI_REPORTING.stg_dlp_care_gap_quarterly cg
),
am AS (
    SELECT health_cluster, quarters_completed, COUNT(*) AS patient_count,
           ROUND(COUNT(*)*100.0/NULLIF(SUM(COUNT(*)) OVER (PARTITION BY health_cluster),0),2) AS pct_of_prevalent
    FROM ps GROUP BY health_cluster, quarters_completed
)
SELECT 2025 AS year, am.health_cluster, am.quarters_completed, am.patient_count, am.pct_of_prevalent, am.quarters_completed AS sort_key, 0 AS sort_order FROM am
UNION ALL SELECT 2025, ps.health_cluster, '≥ Target', SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END), ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),2), 99, 1 FROM ps GROUP BY ps.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', SUM(am.patient_count), 100.0, 100, 2 FROM am ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  stg_dlp_control_patient:    {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dlp_control_patient').fetchone()[0]} rows")
print(f"  stg_dlp_care_gap_quarterly: {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_dlp_care_gap_quarterly').fetchone()[0]} rows")

# =====================================================================
# OB — STAGING
# =====================================================================
print("\n--- OB Staging ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_cohort AS
WITH pop AS (
    SELECT _ID AS patient_key, GENDERUID AS gender, DATEOFBIRTH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_e66_date,
           MIN(DIAGNOSIS_DATE) AS first_any_ob_date, TRUE AS has_e66
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E66' GROUP BY PATIENTUID
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
)
SELECT pop.*,
       COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
       dx.first_any_ob_date, dx.first_e66_date,
       COALESCE(dx.has_e66,FALSE) AS has_e66,
       COALESCE(dx.has_e66,FALSE) AS has_any_ob_diagnosis,
       CASE WHEN pop.is_in_total_population AND NOT COALESCE(dx.has_e66,FALSE) THEN TRUE ELSE FALSE END AS is_in_at_risk,
       CASE WHEN pop.is_in_total_population AND COALESCE(dx.has_e66,FALSE) THEN TRUE ELSE FALSE END AS is_ob_prevalent
FROM pop LEFT JOIN dx USING (patient_key) LEFT JOIN phc USING (patient_key)
""")
print(f"  stg_ob_cohort:              {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_ob_cohort').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_labs AS
SELECT o.PATIENTUID AS patient_key, pv.STARTDATE AS visit_date,
       EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
       'BMI' AS result_name,
       NULLIF(TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)), 0) AS result_value,
       'OBSERVATIONS' AS source_table
FROM NMR.LEANHIS_OBSERVATIONS o
JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
  AND ov.NAME = 'BMI' AND ov.RESULTVALUE IS NOT NULL
  AND TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)) BETWEEN 10 AND 80
""")
print(f"  stg_ob_labs:                {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_ob_labs').fetchone()[0]} rows")

# =====================================================================
# OB — ANALYTICAL
# =====================================================================
print("--- OB Analytical ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_patient_month AS
WITH visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
monthly_bmi AS (
    SELECT patient_key, year_month_key,
           MAX(result_value) AS last_bmi_value,
           bool_or(TRUE) AS had_bmi
    FROM CHI_REPORTING.stg_ob_labs WHERE result_value IS NOT NULL
    GROUP BY patient_key, year_month_key
),
spine AS (
    SELECT bc.*, m.year_month_key, m.report_month,
           CASE WHEN bc.first_any_ob_date IS NOT NULL
                 AND bc.first_any_ob_date < strptime(m.year_month_key::VARCHAR,'%Y%m')
                THEN TRUE ELSE FALSE END AS has_ob_before,
           CASE WHEN NOT (bc.first_any_ob_date IS NOT NULL
                 AND bc.first_any_ob_date < strptime(m.year_month_key::VARCHAR,'%Y%m'))
                THEN TRUE ELSE FALSE END AS is_at_risk_start
    FROM CHI_REPORTING.stg_ob_cohort bc
    CROSS JOIN (
        SELECT seq AS report_month, 2025*100+seq AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
)
SELECT pms.*,
       CASE WHEN v.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
       COALESCE(mb.had_bmi,FALSE) AS had_bmi, mb.last_bmi_value,
       CASE WHEN pms.is_at_risk_start AND COALESCE(mb.had_bmi,FALSE) THEN TRUE ELSE FALSE END AS is_screened,
       CASE WHEN mb.last_bmi_value IS NULL THEN NULL
            WHEN mb.last_bmi_value < 18.5 THEN 'underweight'
            WHEN mb.last_bmi_value <= 24.9 THEN 'normal'
            WHEN mb.last_bmi_value <= 29.9 THEN 'elevated'
            ELSE 'abnormal' END AS screening_category,
       CASE WHEN pms.first_e66_date IS NOT NULL
             AND pms.first_e66_date >= strptime(pms.year_month_key::VARCHAR,'%Y%m')
             AND pms.first_e66_date < strptime(pms.year_month_key::VARCHAR,'%Y%m') + INTERVAL 1 MONTH
             AND pms.is_at_risk_start
            THEN TRUE ELSE FALSE END AS is_incident_case
FROM spine pms
LEFT JOIN visits v ON pms.patient_key=v.patient_key AND pms.year_month_key=v.year_month_key
LEFT JOIN monthly_bmi mb ON pms.patient_key=mb.patient_key AND pms.year_month_key=mb.year_month_key
""")
print(f"  stg_ob_patient_month:      {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_ob_patient_month').fetchone()[0]} rows")

# =====================================================================
# OB — REPORTS
# =====================================================================
print("--- OB Reports ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_screening_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_screened THEN patient_key END) AS screened,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='underweight' THEN patient_key END) AS under_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='normal' THEN patient_key END) AS normal_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='elevated' THEN patient_key END) AS elevated_n,
           COUNT(DISTINCT CASE WHEN is_screened AND screening_category='abnormal' THEN patient_key END) AS case_n,
           ROUND(screened*100.0/NULLIF(at_risk,0),2) AS scr_rate,
           ROUND(case_n*100.0/NULLIF(screened,0),2) AS case_rate
    FROM CHI_REPORTING.stg_ob_patient_month GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, screened, under_n, normal_n, elevated_n, case_n, scr_rate, case_rate,
       year_month_key AS sort_key, 0 AS sort_order FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       SUM(at_risk), SUM(screened), SUM(under_n), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2), 99999, 1 FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       SUM(at_risk), SUM(screened), SUM(under_n), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk),0),2),
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0),2), 99999, 2 FROM m ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_prevalence_annual AS
WITH snap AS (
    SELECT patient_key,
           CASE WHEN first_e66_date IS NOT NULL AND first_e66_date < '2026-01-01' THEN TRUE ELSE FALSE END AS has_e66,
           CASE WHEN first_e66_date >= '2025-01-01' AND first_e66_date < '2026-01-01' THEN TRUE ELSE FALSE END AS incident_yr,
           CASE WHEN first_e66_date < '2025-01-01' THEN TRUE ELSE FALSE END AS pre_existing
    FROM CHI_REPORTING.stg_ob_cohort
)
SELECT 2025 AS year, bc.health_cluster,
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END) AS total_pop,
       COUNT(DISTINCT CASE WHEN s.has_e66 THEN bc.patient_key END) AS prevalent,
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END) AS incident_during_year,
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e66 THEN bc.patient_key END) AS pre_existing_count,
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e66 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2) AS prev_rate,
       bc.health_cluster AS period_label, 0 AS sort_order
FROM CHI_REPORTING.stg_ob_cohort bc LEFT JOIN snap s USING (patient_key)
GROUP BY bc.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.has_e66 THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.incident_yr THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.pre_existing AND s.has_e66 THEN bc.patient_key END),
       ROUND(COUNT(DISTINCT CASE WHEN s.has_e66 THEN bc.patient_key END)*100.0/NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),0),2),
       '── 2025 ALL CLUSTERS ──', 2
FROM CHI_REPORTING.stg_ob_cohort bc LEFT JOIN snap s USING (patient_key)
ORDER BY health_cluster, sort_order
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_incidence_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_incident_case THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0),2) AS rate
    FROM CHI_REPORTING.stg_ob_patient_month GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate, year_month_key AS sort_key, 0 AS sort_order FROM m
UNION ALL
SELECT 2025, health_cluster,
       '── ' || health_cluster || ' TOTAL ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 1 FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       '── 2025 ALL CLUSTERS ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0), 2),
       99999, 2 FROM m ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_ob_prevalence_annual:  {con.execute('SELECT * FROM CHI_REPORTING.rpt_ob_prevalence_annual WHERE sort_order=2').fetchone()}")

# =====================================================================
# OB — MONITORING (COMPLIANCE & CARE GAP)
# =====================================================================
print("--- OB Monitoring ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_control_patient AS
WITH mr AS (
    SELECT pm.patient_key, pm.health_cluster,
           arg_max(pm.last_bmi_value,
               CASE WHEN pm.last_bmi_value IS NOT NULL THEN pm.year_month_key ELSE 0 END) AS year_end_bmi,
           bool_or(pm.had_bmi) AS had_any_bmi
    FROM CHI_REPORTING.stg_ob_patient_month pm
    WHERE pm.is_ob_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster
),
classified AS (
    SELECT mr.*, t.level_order, t.label AS control_level_label
    FROM mr LEFT JOIN CHI_REPORTING.chi_control_thresholds t
        ON t.condition='ob' AND t.marker='bmi'
        AND (t.min_value IS NULL OR mr.year_end_bmi >= t.min_value)
        AND (t.max_value IS NULL OR mr.year_end_bmi < t.max_value)
)
SELECT patient_key, health_cluster, year_end_bmi, had_any_bmi,
       COALESCE(control_level_label, 'Not Monitored') AS control_level,
       COALESCE(level_order, -1) AS control_level_order
FROM classified
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_ob_care_gap_quarterly AS
WITH qf AS (
    SELECT pm.patient_key, pm.health_cluster,
           CASE WHEN pm.report_month BETWEEN 1 AND 3 THEN 1
                WHEN pm.report_month BETWEEN 4 AND 6 THEN 2
                WHEN pm.report_month BETWEEN 7 AND 9 THEN 3 ELSE 4 END AS quarter,
           bool_or(pm.had_bmi) AS quarter_completed
    FROM CHI_REPORTING.stg_ob_patient_month pm
    WHERE pm.is_ob_prevalent = TRUE
    GROUP BY pm.patient_key, pm.health_cluster, quarter
)
SELECT patient_key, health_cluster, 2025 AS report_year,
       SUM(CASE WHEN quarter_completed THEN 1 ELSE 0 END) AS quarters_completed,
       MAX(CASE WHEN quarter=1 AND quarter_completed THEN 1 ELSE 0 END) AS q1_completed,
       MAX(CASE WHEN quarter=2 AND quarter_completed THEN 1 ELSE 0 END) AS q2_completed,
       MAX(CASE WHEN quarter=3 AND quarter_completed THEN 1 ELSE 0 END) AS q3_completed,
       MAX(CASE WHEN quarter=4 AND quarter_completed THEN 1 ELSE 0 END) AS q4_completed
FROM qf GROUP BY patient_key, health_cluster
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_control AS
WITH cm AS (
    SELECT health_cluster, control_level, control_level_order, COUNT(*) AS patient_count
    FROM CHI_REPORTING.stg_ob_control_patient GROUP BY health_cluster, control_level, control_level_order
),
pc AS (SELECT health_cluster, COUNT(*) AS tot FROM CHI_REPORTING.stg_ob_control_patient GROUP BY health_cluster)
SELECT 2025 AS year, cm.health_cluster, cm.control_level, cm.control_level_order AS control_level_order_int,
       cm.patient_count, ROUND(cm.patient_count*100.0/NULLIF(pc.tot,0),2) AS pct_of_prevalent, 0 AS sort_order
FROM cm JOIN pc USING (health_cluster)
UNION ALL SELECT 2025, cm.health_cluster, '── '||cm.health_cluster||' TOTAL ──', 99, SUM(cm.patient_count), 100.0, 1 FROM cm GROUP BY cm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', 99, SUM(cm.patient_count), 100.0, 2 FROM cm
ORDER BY health_cluster, sort_order, control_level_order_int
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_care_gap_quarterly AS
WITH qm AS (
    SELECT cg.health_cluster, 1 AS quarter, COUNT(*) AS prev, SUM(cg.q1_completed) AS comp,
           COUNT(*)-SUM(cg.q1_completed) AS gap,
           ROUND(SUM(cg.q1_completed)*100.0/NULLIF(COUNT(*),0),2) AS rate
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 2, COUNT(*), SUM(cg.q2_completed), COUNT(*)-SUM(cg.q2_completed), ROUND(SUM(cg.q2_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 3, COUNT(*), SUM(cg.q3_completed), COUNT(*)-SUM(cg.q3_completed), ROUND(SUM(cg.q3_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
    UNION ALL SELECT cg.health_cluster, 4, COUNT(*), SUM(cg.q4_completed), COUNT(*)-SUM(cg.q4_completed), ROUND(SUM(cg.q4_completed)*100.0/NULLIF(COUNT(*),0),2) FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg GROUP BY cg.health_cluster
)
SELECT 2025 AS year, qm.health_cluster, qm.quarter, qm.prev, qm.comp, qm.gap, qm.rate, qm.quarter AS sort_key, 0 AS sort_order FROM qm
UNION ALL SELECT 2025, qm.health_cluster, NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 1 FROM qm GROUP BY qm.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', NULL, MAX(qm.prev), SUM(qm.comp), SUM(qm.gap), ROUND(SUM(qm.comp)*100.0/NULLIF(SUM(qm.prev),0),2), 99, 2 FROM qm ORDER BY health_cluster, sort_order, sort_key
""")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_ob_care_gap_annual AS
WITH ps AS (
    SELECT cg.health_cluster, cg.patient_key, cg.quarters_completed,
           cg.quarters_completed >= 3 AS meets_target
    FROM CHI_REPORTING.stg_ob_care_gap_quarterly cg
),
am AS (
    SELECT health_cluster, quarters_completed, COUNT(*) AS patient_count,
           ROUND(COUNT(*)*100.0/NULLIF(SUM(COUNT(*)) OVER (PARTITION BY health_cluster),0),2) AS pct_of_prevalent
    FROM ps GROUP BY health_cluster, quarters_completed
)
SELECT 2025 AS year, am.health_cluster, am.quarters_completed, am.patient_count, am.pct_of_prevalent, am.quarters_completed AS sort_key, 0 AS sort_order FROM am
UNION ALL SELECT 2025, ps.health_cluster, '≥ Target', SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END), ROUND(SUM(CASE WHEN ps.meets_target THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0),2), 99, 1 FROM ps GROUP BY ps.health_cluster
UNION ALL SELECT 2025, '── ALL CLUSTERS ──', '── ALL CLUSTERS ──', SUM(am.patient_count), 100.0, 100, 2 FROM am ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  stg_ob_control_patient:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_ob_control_patient').fetchone()[0]} rows")
print(f"  stg_ob_care_gap_quarterly:  {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_ob_care_gap_quarterly').fetchone()[0]} rows")

# =====================================================================
# PREDIABETES (PREDIAB) — STAGING
# =====================================================================
# No stg_prediab_labs — prediabetes has no lab of its own.
# BMI ≥ 25 lookup is inlined in stg_prediab_cohort from OBSERVATIONS.
print("--- PREDIAB Staging ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_cohort AS
WITH pop AS (
    SELECT _ID AS patient_key, GENDERUID AS gender, DATEOFBIRTH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
pdx AS (
    SELECT PATIENTUID AS patient_key,
           MIN(DIAGNOSIS_DATE) AS first_r73_date,
           bool_or(TRIM(UPPER(ICD10_CODE))='R73.03') AS has_r73
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'R73.03'
    GROUP BY PATIENTUID
),
-- Risk factor 1: latest BMI in 2025 ≥ 25
bmi_latest AS (
    SELECT o.PATIENTUID AS patient_key,
           arg_max(
               TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)),
               pv.STARTDATE
           ) AS latest_bmi_value
    FROM NMR.LEANHIS_OBSERVATIONS o
    JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
    JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
    WHERE pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'
      AND ov.NAME = 'BMI'
      AND TRY_CAST(regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?') AS DECIMAL(10,2)) BETWEEN 10 AND 80
    GROUP BY o.PATIENTUID
),
-- Risk factor 2: HTN dx
htn_flag AS (SELECT patient_key, has_any_htn_diagnosis FROM CHI_REPORTING.stg_htn_cohort),
-- Risk factor 3: DLP dx
dlp_flag AS (SELECT patient_key, has_any_dlp_diagnosis FROM CHI_REPORTING.stg_dlp_cohort),
-- Risk factor 4: family history PLACEHOLDER — hardcoded FALSE (TODO: wire to real source)
family_history_flag AS (SELECT DISTINCT patient_key, FALSE AS has_family_history_diabetes
                        FROM CHI_REPORTING.stg_htn_cohort),
-- Risk factor 5: GDM history
gdm_flag AS (SELECT patient_key, has_gdm FROM CHI_REPORTING.stg_dm_cohort),
-- Risk factor 6: PCOS via E28.2
pcos_dx AS (
    SELECT PATIENTUID AS patient_key,
           bool_or(TRIM(UPPER(ICD10_CODE))='E28.2') AS has_pcos
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E28.2'
    GROUP BY PATIENTUID
),
phc AS (SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
        FROM NMR.LEANHIS_PHC_ASSIGNMENT)
SELECT pop.patient_key, pop.gender, pop.age_at_jan1, pop.is_in_total_population,
       COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
       pdx.first_r73_date,
       COALESCE(pdx.has_r73, FALSE) AS has_prediabetes,
       COALESCE(bmi.latest_bmi_value >= 25.0, FALSE) AS has_bmi_ge_25,
       COALESCE(htn.has_any_htn_diagnosis, FALSE) AS has_htn_dx,
       COALESCE(dlp.has_any_dlp_diagnosis, FALSE) AS has_dlp_dx,
       COALESCE(fh.has_family_history_diabetes, FALSE) AS has_family_history_diabetes,
       COALESCE(gdm.has_gdm, FALSE) AS has_gdm_history,
       COALESCE(pcos.has_pcos, FALSE) AS has_pcos,
       (CASE WHEN bmi.latest_bmi_value >= 25.0                       THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(htn.has_any_htn_diagnosis, FALSE)          THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(dlp.has_any_dlp_diagnosis, FALSE)          THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(fh.has_family_history_diabetes, FALSE)     THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(gdm.has_gdm, FALSE)                        THEN 1 ELSE 0 END
      + CASE WHEN COALESCE(pcos.has_pcos, FALSE)                      THEN 1 ELSE 0 END
       ) AS risk_factor_count,
       CASE WHEN (CASE WHEN bmi.latest_bmi_value >= 25.0                       THEN 1 ELSE 0 END
                    + CASE WHEN COALESCE(htn.has_any_htn_diagnosis, FALSE)    THEN 1 ELSE 0 END
                    + CASE WHEN COALESCE(dlp.has_any_dlp_diagnosis, FALSE)    THEN 1 ELSE 0 END
                    + CASE WHEN COALESCE(fh.has_family_history_diabetes, FALSE) THEN 1 ELSE 0 END
                    + CASE WHEN COALESCE(gdm.has_gdm, FALSE)                  THEN 1 ELSE 0 END
                    + CASE WHEN COALESCE(pcos.has_pcos, FALSE)                THEN 1 ELSE 0 END
                   ) >= 2
            THEN TRUE ELSE FALSE END AS is_high_risk_prediab,
       CASE WHEN pop.is_in_total_population AND COALESCE(pdx.has_r73, FALSE)
            THEN TRUE ELSE FALSE END AS is_prediab_prevalent,
       CASE WHEN pop.is_in_total_population AND NOT COALESCE(pdx.has_r73, FALSE)
            THEN TRUE ELSE FALSE END AS is_in_at_risk_prediab
FROM pop
LEFT JOIN phc  USING (patient_key)
LEFT JOIN pdx  USING (patient_key)
LEFT JOIN bmi_latest bmi USING (patient_key)
LEFT JOIN htn_flag htn USING (patient_key)
LEFT JOIN dlp_flag dlp USING (patient_key)
LEFT JOIN family_history_flag fh USING (patient_key)
LEFT JOIN gdm_flag gdm USING (patient_key)
LEFT JOIN pcos_dx pcos USING (patient_key)
""")
print(f"  stg_prediab_cohort:        {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_prediab_cohort').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_diagnosis AS
SELECT PATIENTUID AS patient_key,
       DIAGNOSIS_DATE AS diagnosis_date,
       ICD10_CODE AS icd10_code,
       DIAGNOSIS_DESCRIPTION AS icd10_description,
       ROW_NUMBER() OVER (PARTITION BY PATIENTUID, ICD10_CODE ORDER BY DIAGNOSIS_DATE) AS diagnosis_rank
FROM NMR.LEANHIS_DIAGNOSIS_CODES
WHERE TRIM(UPPER(ICD10_CODE)) = 'R73.03'
""")
print(f"  stg_prediab_diagnosis:     {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_prediab_diagnosis').fetchone()[0]} rows")

# =====================================================================
# PREDIABETES (PREDIAB) — ANALYTICAL
# =====================================================================
print("--- PREDIAB Analytical ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_prediab_patient_month AS
WITH visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
spine AS (
    SELECT bc.*, m.year_month_key, m.report_month,
           CASE WHEN bc.first_r73_date IS NOT NULL
                 AND bc.first_r73_date < strptime(m.year_month_key::VARCHAR, '%Y%m')
                THEN TRUE ELSE FALSE END AS has_r73_before,
           CASE WHEN NOT (bc.first_r73_date IS NOT NULL
                          AND bc.first_r73_date < strptime(m.year_month_key::VARCHAR, '%Y%m'))
                THEN TRUE ELSE FALSE END AS is_prediab_at_risk_start
    FROM CHI_REPORTING.stg_prediab_cohort bc
    CROSS JOIN (
        SELECT seq AS report_month, 2025*100+seq AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
)
SELECT pms.*,
       CASE WHEN v.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
       CASE WHEN pms.first_r73_date IS NOT NULL
             AND pms.first_r73_date >= strptime(pms.year_month_key::VARCHAR, '%Y%m')
             AND pms.first_r73_date <  strptime(pms.year_month_key::VARCHAR, '%Y%m') + INTERVAL 1 MONTH
             AND pms.is_prediab_at_risk_start
            THEN TRUE ELSE FALSE END AS is_prediab_incident_case
FROM spine pms
LEFT JOIN visits v ON pms.patient_key=v.patient_key AND pms.year_month_key=v.year_month_key
""")
print(f"  stg_prediab_patient_month: {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_prediab_patient_month').fetchone()[0]} rows")

# =====================================================================
# PREDIABETES (PREDIAB) — REPORTS
# =====================================================================
print("--- PREDIAB Reports ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_incidence_monthly AS
WITH m AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_prediab_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_prediab_incident_case THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0),2) AS rate
    FROM CHI_REPORTING.stg_prediab_patient_month
    GROUP BY health_cluster, report_month, year_month_key
)
SELECT 2025 AS year, health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate,
       year_month_key AS sort_key, 0 AS sort_order
FROM m
UNION ALL
SELECT 2025, health_cluster, '── ' || health_cluster || ' TOTAL ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0),2),
       99999, 1
FROM m GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──', '── 2025 ALL CLUSTERS ──',
       NULL, SUM(incident),
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0),2),
       99999, 2
FROM m
ORDER BY health_cluster, sort_order, sort_key
""")
print(f"  rpt_prediab_incidence_monthly:        {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_prediab_incidence_monthly').fetchone()[0]} rows")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_prevalence_annual AS
WITH snap AS (
    SELECT patient_key, first_r73_date,
           CASE WHEN first_r73_date IS NOT NULL AND first_r73_date < '2026-01-01' THEN TRUE ELSE FALSE END AS has_r73_at_year_end,
           CASE WHEN first_r73_date >= '2025-01-01' AND first_r73_date < '2026-01-01' THEN TRUE ELSE FALSE END AS is_incident_this_year,
           CASE WHEN first_r73_date < '2025-01-01' THEN TRUE ELSE FALSE END AS is_pre_existing
    FROM CHI_REPORTING.stg_prediab_cohort
)
SELECT 2025 AS year, bc.health_cluster,
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END) AS total_population,
       COUNT(DISTINCT CASE WHEN s.has_r73_at_year_end THEN bc.patient_key END) AS prevalent_prediab_count,
       COUNT(DISTINCT CASE WHEN s.is_incident_this_year THEN bc.patient_key END) AS incident_during_year,
       COUNT(DISTINCT CASE WHEN s.is_pre_existing AND s.has_r73_at_year_end THEN bc.patient_key END) AS pre_existing_prediab_count,
       ROUND(
           COUNT(DISTINCT CASE WHEN s.has_r73_at_year_end THEN bc.patient_key END)*100.0
           / NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END), 0), 4
       ) AS prevalence_rate_pct,
       bc.health_cluster AS period_label, 0 AS sort_order
FROM CHI_REPORTING.stg_prediab_cohort bc
LEFT JOIN snap s USING (patient_key)
GROUP BY bc.health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──',
       COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.has_r73_at_year_end THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.is_incident_this_year THEN bc.patient_key END),
       COUNT(DISTINCT CASE WHEN s.is_pre_existing AND s.has_r73_at_year_end THEN bc.patient_key END),
       ROUND(
           COUNT(DISTINCT CASE WHEN s.has_r73_at_year_end THEN bc.patient_key END)*100.0
           / NULLIF(COUNT(DISTINCT CASE WHEN bc.is_in_total_population THEN bc.patient_key END), 0), 4
       ),
       '── 2025 ALL CLUSTERS ──' AS period_label, 2 AS sort_order
FROM CHI_REPORTING.stg_prediab_cohort bc
LEFT JOIN snap s USING (patient_key)
ORDER BY health_cluster, sort_order
""")
print(f"  rpt_prediab_prevalence_annual:         {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_prediab_prevalence_annual').fetchone()[0]} rows")

# =====================================================================
# HIGH-RISK PATIENTS — GENERIC STAGING (per-condition)
# =====================================================================
# stg_high_risk_patient: one row per (patient, condition), parameterized
# across all 5 conditions via chi_high_risk_factors. Per-condition reports
# are defined in each condition's own folder (see Prediabetes section below).
# For v1 only PREDIAB has factors, so the staging view only emits rows
# for PREDIAB patients.
print("--- High-Risk Patients (Generic staging) ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.stg_high_risk_patient AS
WITH pop AS (
    SELECT _ID AS patient_key,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN age_at_jan1 > 18 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS WHERE DATEOFBIRTH <= '2007-01-01'
),
ppc AS (
    SELECT pop.patient_key, pop.is_in_total_population, 'prediab' AS condition,
           CASE WHEN pc.first_r73_date IS NOT NULL AND pc.first_r73_date < '2026-01-01' THEN TRUE ELSE FALSE END AS is_prevalent_year_end
    FROM pop LEFT JOIN CHI_REPORTING.stg_prediab_cohort pc ON pc.patient_key = pop.patient_key
    UNION ALL
    SELECT pop.patient_key, pop.is_in_total_population, 'dm' AS condition,
           CASE WHEN dc.first_e11_date IS NOT NULL AND dc.first_e11_date < '2026-01-01' THEN TRUE ELSE FALSE END
    FROM pop LEFT JOIN CHI_REPORTING.stg_dm_cohort dc ON dc.patient_key = pop.patient_key
    UNION ALL
    SELECT pop.patient_key, pop.is_in_total_population, 'htn' AS condition,
           CASE WHEN hc.first_i10_date IS NOT NULL AND hc.first_i10_date < '2026-01-01' THEN TRUE ELSE FALSE END
    FROM pop LEFT JOIN CHI_REPORTING.stg_htn_cohort hc ON hc.patient_key = pop.patient_key
    UNION ALL
    SELECT pop.patient_key, pop.is_in_total_population, 'dlp' AS condition,
           CASE WHEN lc.first_e78_date IS NOT NULL AND lc.first_e78_date < '2026-01-01' THEN TRUE ELSE FALSE END
    FROM pop LEFT JOIN CHI_REPORTING.stg_dlp_cohort lc ON lc.patient_key = pop.patient_key
    UNION ALL
    SELECT pop.patient_key, pop.is_in_total_population, 'ob' AS condition,
           CASE WHEN oc.first_e66_date IS NOT NULL AND oc.first_e66_date < '2026-01-01' THEN TRUE ELSE FALSE END
    FROM pop LEFT JOIN CHI_REPORTING.stg_ob_cohort oc ON oc.patient_key = pop.patient_key
),
cond_with_factors AS (SELECT DISTINCT condition FROM CHI_REPORTING.chi_high_risk_factors),
factor_evals AS (
    SELECT ppc.patient_key, ppc.condition, hrf.factor_code, hrf.weight,
           CASE
               WHEN hrf.source_column = 'always_false' THEN FALSE
               WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort' AND hrf.source_column = 'has_bmi_ge_25'
                   THEN COALESCE((SELECT has_bmi_ge_25 FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
               WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort' AND hrf.source_column = 'has_htn_dx'
                   THEN COALESCE((SELECT has_htn_dx FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
               WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort' AND hrf.source_column = 'has_dlp_dx'
                   THEN COALESCE((SELECT has_dlp_dx FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
               WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort' AND hrf.source_column = 'has_gdm_history'
                   THEN COALESCE((SELECT has_gdm_history FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
               WHEN hrf.source_view = 'CHI_REPORTING.stg_prediab_cohort' AND hrf.source_column = 'has_pcos'
                   THEN COALESCE((SELECT has_pcos FROM CHI_REPORTING.stg_prediab_cohort WHERE patient_key = ppc.patient_key), FALSE)
               ELSE FALSE
           END AS has_factor
    FROM ppc INNER JOIN cond_with_factors cwf ON cwf.condition = ppc.condition
    CROSS JOIN CHI_REPORTING.chi_high_risk_factors hrf
    WHERE hrf.condition = ppc.condition AND ppc.is_prevalent_year_end = TRUE
)
SELECT patient_key, condition, 2025 AS report_year,
       SUM(CASE WHEN has_factor THEN weight ELSE 0 END) AS risk_factor_count,
       CASE WHEN SUM(CASE WHEN has_factor THEN weight ELSE 0 END) >= 2 THEN TRUE ELSE FALSE END AS is_high_risk
FROM factor_evals GROUP BY patient_key, condition
""")
print(f"  stg_high_risk_patient:      {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.stg_high_risk_patient').fetchone()[0]} rows")

# =====================================================================
# PREDIABETES HIGH-RISK REPORT (per-condition filter on stg_high_risk_patient)
# =====================================================================
# Prediabetes-specific Module-2 report. Reads the generic stg_high_risk_patient
# and filters to condition='prediab'. v1 emits output only for PREDIAB because
# that is the only condition with factors defined in chi_high_risk_factors.
print("--- Prediabetes High-Risk Report ---")

con.execute("""
CREATE OR REPLACE VIEW CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual AS
WITH snap AS (
    SELECT hr.patient_key,
           COALESCE(pc.health_cluster, 'Unassigned') AS health_cluster,
           hr.is_high_risk
    FROM CHI_REPORTING.stg_high_risk_patient hr
    LEFT JOIN CHI_REPORTING.stg_prediab_cohort pc
            ON pc.patient_key = hr.patient_key
    WHERE hr.condition = 'prediab'
)
SELECT 2025 AS year, health_cluster,
       COUNT(*) AS total_prediab_population,
       SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) AS high_risk_count,
       ROUND(SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0), 2) AS high_risk_pct,
       health_cluster AS sort_key, 0 AS sort_order
FROM snap GROUP BY health_cluster
UNION ALL
SELECT 2025, '── ALL CLUSTERS ──' AS health_cluster,
       COUNT(*),
       SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END)*100.0/NULLIF(COUNT(*),0), 2),
       '── 2025 ALL CLUSTERS ──' AS sort_key, 2 AS sort_order
FROM snap
ORDER BY sort_order, sort_key
""")
print(f"  rpt_prediab_prevalence_high_risk_annual: {con.execute('SELECT COUNT(*) FROM CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual').fetchone()[0]} rows")

# =====================================================================
# FINAL VERIFICATION
# =====================================================================
print("\n" + "=" * 60)
print("VERIFICATION — Compare to run_all_reports.py output")
print("=" * 60)

checks = [
    # DM
    ("DM at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dm_patient_month WHERE year_month_key=202501", 16),
    ("DM at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dm_patient_month WHERE year_month_key=202512", 13),
    ("DM prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_dm_prevalence_annual WHERE sort_order=2", 5),
    ("DM incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_dm_incidence_monthly WHERE sort_order=0", 4),
    # HTN
    ("HTN at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_htn_patient_month WHERE year_month_key=202501", 17),
    ("HTN at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_htn_patient_month WHERE year_month_key=202512", 14),
    ("HTN prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_htn_prevalence_annual WHERE sort_order=2", 6),
    ("HTN incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_htn_incidence_monthly WHERE sort_order=0", 3),
    # DLP
    ("DLP at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dlp_patient_month WHERE year_month_key=202501", 18),
    ("DLP at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dlp_patient_month WHERE year_month_key=202512", 16),
    ("DLP prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_dlp_prevalence_annual WHERE sort_order=2", 4),
    ("DLP incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_dlp_incidence_monthly WHERE sort_order=0", 2),
    # OB
    ("OB at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_ob_patient_month WHERE year_month_key=202501", 18),
    ("OB at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_ob_patient_month WHERE year_month_key=202512", 17),
    ("OB prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_ob_prevalence_annual WHERE sort_order=2", 3),
    ("OB incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_ob_incidence_monthly WHERE sort_order=0", 1),
    # PREDIAB
    ("PREDIAB at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_prediab_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_prediab_patient_month WHERE year_month_key=202501", 16),
    ("PREDIAB at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_prediab_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_prediab_patient_month WHERE year_month_key=202512", 14),
    ("PREDIAB prevalent year-end", "SELECT prevalent_prediab_count FROM CHI_REPORTING.rpt_prediab_prevalence_annual WHERE sort_order=2", 7),
    ("PREDIAB incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_prediab_incidence_monthly WHERE sort_order=0", 3),
    # High-Risk Patients (generic)
    ("HR PREDIAB prevalent", "SELECT total_prediab_population FROM CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual WHERE sort_order=2", 7),
    ("HR PREDIAB high-risk", "SELECT high_risk_count FROM CHI_REPORTING.rpt_prediab_prevalence_high_risk_annual WHERE sort_order=2", 3),
]

all_ok = True
for label, query, expected in checks:
    actual = con.execute(query).fetchone()[0]
    status = "OK" if actual == expected else f"MISMATCH (got {actual})"
    if actual != expected:
        all_ok = False
    print(f"  {label:<25s} expected={expected}  actual={actual}  {status}")

# View counts
view_count = con.execute("SELECT COUNT(*) FROM information_schema.views WHERE table_schema='CHI_REPORTING'").fetchone()[0]
print(f"\n=== Views created: {view_count} ===")

con.close()
print(f"\nDatabase: {os.path.abspath(DB)}")
print("Open in DBeaver and browse CHI_REPORTING schema.")
