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
# FINAL VERIFICATION
# =====================================================================
print("\n" + "=" * 60)
print("VERIFICATION — Compare to run_all_reports.py output")
print("=" * 60)

checks = [
    # DM
    ("DM at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dm_patient_month WHERE year_month_key=202501", 13),
    ("DM at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dm_patient_month WHERE year_month_key=202512", 10),
    ("DM prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_dm_prevalence_annual WHERE sort_order=2", 5),
    ("DM incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_dm_incidence_monthly WHERE sort_order=0", 4),
    # HTN
    ("HTN at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_htn_patient_month WHERE year_month_key=202501", 16),
    ("HTN at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_htn_patient_month WHERE year_month_key=202512", 13),
    ("HTN prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_htn_prevalence_annual WHERE sort_order=2", 4),
    ("HTN incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_htn_incidence_monthly WHERE sort_order=0", 3),
    # DLP
    ("DLP at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dlp_patient_month WHERE year_month_key=202501", 16),
    ("DLP at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_dlp_patient_month WHERE year_month_key=202512", 14),
    ("DLP prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_dlp_prevalence_annual WHERE sort_order=2", 3),
    ("DLP incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_dlp_incidence_monthly WHERE sort_order=0", 2),
    # OB
    ("OB at-risk Jan", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_ob_patient_month WHERE year_month_key=202501", 15),
    ("OB at-risk Dec", "SELECT COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) FROM CHI_REPORTING.stg_ob_patient_month WHERE year_month_key=202512", 14),
    ("OB prevalent", "SELECT prevalent FROM CHI_REPORTING.rpt_ob_prevalence_annual WHERE sort_order=2", 3),
    ("OB incident total", "SELECT COALESCE(SUM(incident),0) FROM CHI_REPORTING.rpt_ob_incidence_monthly WHERE sort_order=0", 1),
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
