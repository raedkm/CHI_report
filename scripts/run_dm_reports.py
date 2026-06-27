"""
run_dm_reports.py
=================
Runs the DM Screening, Prevalence, and Incidence reports against
the DuckDB simulation database (chi_sim.db).

Adapted from dm_reports.sql with DuckDB dialect substitutions:
  Snowflake                  DuckDB
  ─────────                  ──────
  MAX_BY(val, ord)     →    arg_max(val, ord)
  TRY_TO_DECIMAL(s,p,s) →   TRY_CAST(s AS DECIMAL(p,s))
  TO_VARCHAR(d, fmt)    →   strftime(d, fmt)
  REGEXP_SUBSTR(s, p)   →   regexp_extract(s, p)
  BOOLOR_AGG(cond)      →   bool_or(cond)
  ADD_MONTHS(d, n)      →   d + INTERVAL n MONTH
  GREATEST(a,b,c)       →   greatest(a,b,c)  -- same
  IFF(a,b,c)            →   iff(a,b,c)       -- same
  NULLIF(x,0)           →   nullif(x,0)      -- same
"""
import duckdb
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "chi_sim.db")
con = duckdb.connect(DB_PATH)

print("=" * 70)
print("DIABETES MELLITUS (DM) REPORTS - DuckDB Simulation")
print("Report Year: 2025")
print("=" * 70)

# =========================================================================
# Build all CTEs and produce the 3 reports
# =========================================================================

# --- REPORT 1: SCREENING (MONTHLY) ---------------------------------------
print("\n" + "-" * 70)
print("REPORT 1: SCREENING REPORT (MONTHLY)")
print("-" * 70)

screening = con.execute("""
WITH
-- Step 1: Total population cohort
total_population AS (
    SELECT
        _ID                                    AS patient_key,
        NATIONALID                             AS national_id_hash,
        GENDERUID                              AS gender,
        DATEOFBIRTH                            AS date_of_birth,
        DATEOFDEATH                            AS date_of_death,
        DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
        CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
              AND NATIONALID IS NOT NULL
              AND NATIONALID <> ''
              AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
             THEN TRUE ELSE FALSE
        END                                    AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS
),

-- Step 2: DM diagnoses
dm_diagnoses_raw AS (
    SELECT
        PATIENTUID                             AS patient_key,
        DIAGNOSIS_DATE                         AS diagnosis_date,
        TRIM(UPPER(ICD10_CODE))                AS icd10_code,
        DIAGNOSIS_DESCRIPTION                  AS icd10_description
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ('E10','E11','E13','E14','O24')
),

dm_diagnoses AS (
    SELECT
        patient_key,
        diagnosis_date,
        icd10_code,
        icd10_description,
        ROW_NUMBER() OVER (
            PARTITION BY patient_key, icd10_code
            ORDER BY diagnosis_date
        )                                      AS diagnosis_rank
    FROM dm_diagnoses_raw
),

dm_diagnosis_summary AS (
    SELECT
        patient_key,
        MIN(CASE WHEN icd10_code = 'E11' THEN diagnosis_date END) AS first_e11_date,
        MIN(CASE WHEN icd10_code = 'E10' THEN diagnosis_date END) AS first_e10_date,
        MIN(CASE WHEN icd10_code = 'E13' THEN diagnosis_date END) AS first_e13_date,
        MIN(CASE WHEN icd10_code = 'E14' THEN diagnosis_date END) AS first_e14_date,
        MIN(CASE WHEN icd10_code = 'O24' THEN diagnosis_date END) AS first_gdm_date,
        MIN(diagnosis_date)                                       AS first_any_dm_date,
        bool_or(icd10_code = 'E11')                               AS has_e11,
        bool_or(icd10_code = 'E10')                               AS has_type1,
        bool_or(icd10_code IN ('E13','E14'))                      AS has_other_dm,
        bool_or(icd10_code = 'O24')                               AS has_gdm
    FROM dm_diagnoses
    WHERE diagnosis_rank = 1
    GROUP BY patient_key
),

-- Step 3: Base cohort with diagnosis flags
base_cohort AS (
    SELECT
        tp.patient_key,
        tp.gender,
        tp.age_at_jan1,
        tp.is_in_total_population,
        dx.first_any_dm_date,
        dx.first_e11_date,
        dx.first_e10_date,
        dx.first_gdm_date,
        COALESCE(dx.has_type1,    FALSE)  AS has_dm_type1,
        COALESCE(dx.has_e11,      FALSE)  AS has_dm_type2,
        COALESCE(dx.has_other_dm, FALSE)  AS has_dm_other,
        COALESCE(dx.has_gdm,      FALSE)  AS has_gdm,
        (COALESCE(dx.has_type1,   FALSE)
      OR COALESCE(dx.has_e11,     FALSE)
      OR COALESCE(dx.has_other_dm,FALSE)
      OR COALESCE(dx.has_gdm,     FALSE)) AS has_any_dm_diagnosis,
        CASE WHEN tp.is_in_total_population
              AND NOT (COALESCE(dx.has_type1,   FALSE)
                    OR COALESCE(dx.has_e11,     FALSE)
                    OR COALESCE(dx.has_other_dm,FALSE)
                    OR COALESCE(dx.has_gdm,     FALSE))
             THEN TRUE ELSE FALSE
        END                                  AS is_in_at_risk,
        CASE WHEN tp.is_in_total_population
              AND (COALESCE(dx.has_type1,   FALSE)
                OR COALESCE(dx.has_e11,     FALSE)
                OR COALESCE(dx.has_other_dm,FALSE)
                OR COALESCE(dx.has_gdm,     FALSE))
             THEN TRUE ELSE FALSE
        END                                  AS is_dm_prevalent
    FROM total_population tp
    LEFT JOIN dm_diagnosis_summary dx USING (patient_key)
),

-- Step 4: Screening labs
labs_raw AS (
    SELECT
        lr.PATIENTUID                            AS patient_key,
        pv.STARTDATE                              AS visit_date,
        EXTRACT(YEAR FROM pv.STARTDATE) * 100
            + EXTRACT(MONTH FROM pv.STARTDATE)    AS year_month_key,
        CASE
            WHEN lrv.NAME IN (
                'Fasting glucose',
                'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
                'GLUCOSE FASTING'
            ) THEN 'FBS'
            WHEN lrv.NAME = 'Hemoglobin A1c.' THEN 'A1C'
        END                                      AS result_name,
        NULLIF(
            TRY_CAST(
                regexp_extract(lrv.RESULTVALUE, '[0-9]+(\\.[0-9]+)?')
                AS DECIMAL(10,2)
            ), 0
        )                                        AS result_value,
        'LABRESULTS'                             AS source_table
    FROM NMR.LEANHIS_LABRESULTS lr
    JOIN NMR.LEANHIS_LABRESULTS_RESULTVALUES lrv
        ON lr._ID = lrv.LABRESULTS_ID
    JOIN NMR.LEANHIS_PATIENTVISITS pv
        ON lr.PATIENTVISITUID = pv._ID
    WHERE pv.STARTDATE >= '2025-01-01'
      AND pv.STARTDATE <  '2026-01-01'
      AND lrv.NAME IN (
              'Fasting glucose',
              'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
              'GLUCOSE FASTING',
              'Hemoglobin A1c.'
          )

    UNION ALL

    SELECT
        o.PATIENTUID                             AS patient_key,
        pv.STARTDATE                              AS visit_date,
        EXTRACT(YEAR FROM pv.STARTDATE) * 100
            + EXTRACT(MONTH FROM pv.STARTDATE)    AS year_month_key,
        CASE
            WHEN ov.NAME IN (
                'Fasting glucose',
                'Fasting glucose [Mass or Moles/volume] in Serum or Plasma',
                'GLUCOSE FASTING'
            ) THEN 'FBS'
            WHEN ov.NAME = 'Hemoglobin A1c.' THEN 'A1C'
        END                                      AS result_name,
        NULLIF(
            TRY_CAST(
                regexp_extract(ov.RESULTVALUE, '[0-9]+(\\.[0-9]+)?')
                AS DECIMAL(10,2)
            ), 0
        )                                        AS result_value,
        'OBSERVATIONS'                           AS source_table
    FROM NMR.LEANHIS_OBSERVATIONS o
    JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov
        ON o._ID = ov.OBSERVATIONS_ID
    JOIN NMR.LEANHIS_PATIENTVISITS pv
        ON o.PATIENTVISITUID = pv._ID
    WHERE pv.STARTDATE >= '2025-01-01'
      AND pv.STARTDATE <  '2026-01-01'
      AND ov.NAME IN ('Fasting glucose', 'Hemoglobin A1c.')
),

labs_filtered AS (
    SELECT * FROM labs_raw WHERE result_value IS NOT NULL
),

-- Step 5: Patient visits
patient_visits AS (
    SELECT
        PATIENTUID                               AS patient_key,
        EXTRACT(YEAR FROM STARTDATE) * 100
            + EXTRACT(MONTH FROM STARTDATE)      AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01'
      AND STARTDATE <  '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),

-- Step 6: Patient-month analytical table
patient_months_spine AS (
    SELECT
        bc.patient_key,
        m.year_month_key,
        m.report_year,
        m.report_month,
        bc.gender,
        bc.age_at_jan1,
        bc.is_in_total_population,
        bc.is_dm_prevalent,
        CASE WHEN bc.first_any_dm_date IS NOT NULL
              AND bc.first_any_dm_date < strptime(
                      m.year_month_key::VARCHAR, '%Y%m'
                  )
             THEN TRUE ELSE FALSE
        END                                        AS has_any_dm_before_month,
        CASE WHEN bc.first_e11_date IS NOT NULL
              AND bc.first_e11_date < strptime(m.year_month_key::VARCHAR, '%Y%m')
             THEN TRUE ELSE FALSE
        END                                        AS has_e11_before_month,
        CASE WHEN NOT (bc.first_any_dm_date IS NOT NULL
              AND bc.first_any_dm_date < strptime(
                      m.year_month_key::VARCHAR, '%Y%m'
                  ))
             THEN TRUE ELSE FALSE
        END                                        AS is_at_risk_start,
        bc.first_e11_date
    FROM base_cohort bc
    CROSS JOIN (
        SELECT
            2025                                 AS report_year,
            seq                                   AS report_month,
            2025 * 100 + seq                      AS year_month_key
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    WHERE bc.is_in_total_population = TRUE
),

patient_month_labs AS (
    SELECT
        patient_key,
        year_month_key,
        arg_max(result_value,
            CASE WHEN result_name = 'FBS' THEN visit_date END
        )                                          AS last_fbs_value,
        arg_max(result_value,
            CASE WHEN result_name = 'A1C' THEN visit_date END
        )                                          AS last_a1c_value,
        bool_or(result_name = 'FBS')               AS had_fbs,
        bool_or(result_name = 'A1C')               AS had_a1c
    FROM labs_filtered
    GROUP BY patient_key, year_month_key
),

patient_month_classified AS (
    SELECT
        pms.*,
        CASE WHEN pv.patient_key IS NOT NULL THEN TRUE ELSE FALSE
        END                                          AS had_visit,
        COALESCE(pml.had_fbs, FALSE)                 AS had_fbs,
        COALESCE(pml.had_a1c, FALSE)                 AS had_a1c,
        CASE WHEN pms.is_at_risk_start
              AND (COALESCE(pml.had_fbs, FALSE) OR COALESCE(pml.had_a1c, FALSE))
             THEN TRUE ELSE FALSE
        END                                          AS is_screened,
        pml.last_fbs_value,
        pml.last_a1c_value,

        -- FBS category
        CASE
            WHEN pml.last_fbs_value IS NULL THEN NULL
            WHEN pml.last_fbs_value < 30 THEN
                CASE
                    WHEN pml.last_fbs_value <= 5.5 THEN 'normal'
                    WHEN pml.last_fbs_value <= 6.9 THEN 'elevated'
                    ELSE                                  'abnormal'
                END
            ELSE
                CASE
                    WHEN pml.last_fbs_value <= 99  THEN 'normal'
                    WHEN pml.last_fbs_value <= 125 THEN 'elevated'
                    ELSE                                'abnormal'
                END
        END                                          AS fbs_category,

        -- A1C category
        CASE
            WHEN pml.last_a1c_value IS NULL THEN NULL
            WHEN pml.last_a1c_value < 5.7  THEN 'normal'
            WHEN pml.last_a1c_value <= 6.4 THEN 'elevated'
            ELSE                                 'abnormal'
        END                                          AS a1c_category,

        -- Overall screening category (worst of both)
        CASE greatest(
            COALESCE(CASE
                WHEN a1c_category IS NULL THEN 0
                WHEN a1c_category = 'normal' THEN 1
                WHEN a1c_category = 'elevated' THEN 2
                ELSE 3
            END, 0),
            COALESCE(CASE
                WHEN fbs_category IS NULL THEN 0
                WHEN fbs_category = 'normal' THEN 1
                WHEN fbs_category = 'elevated' THEN 2
                ELSE 3
            END, 0)
        )
        WHEN 3 THEN 'abnormal'
        WHEN 2 THEN 'elevated'
        WHEN 1 THEN 'normal'
        END                                          AS screening_category,

        -- Incidence: first-ever E11 diagnosis during this month
        CASE WHEN pms.first_e11_date IS NOT NULL
              AND pms.first_e11_date >= strptime(pms.year_month_key::VARCHAR, '%Y%m')
              AND pms.first_e11_date < strptime(pms.year_month_key::VARCHAR, '%Y%m') + INTERVAL 1 MONTH
              AND pms.is_at_risk_start = TRUE
             THEN TRUE ELSE FALSE
        END                                          AS is_incident_case

    FROM patient_months_spine pms
    LEFT JOIN patient_visits pv
        ON  pms.patient_key   = pv.patient_key
        AND pms.year_month_key = pv.year_month_key
    LEFT JOIN patient_month_labs pml
        ON  pms.patient_key    = pml.patient_key
        AND pms.year_month_key = pml.year_month_key
),

-- REPORT 1: SCREENING
screening_metrics_monthly AS (
    SELECT
        report_year,
        report_month,
        year_month_key,
        COUNT(DISTINCT CASE WHEN is_at_risk_start = TRUE
                        THEN patient_key END)     AS at_risk_population,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                        THEN patient_key END)     AS screened_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'normal'
                        THEN patient_key END)     AS normal_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'elevated'
                        THEN patient_key END)     AS elevated_count,
        COUNT(DISTINCT CASE WHEN is_screened = TRUE
                              AND screening_category = 'abnormal'
                        THEN patient_key END)     AS abnormal_count,
        ROUND(screened_count * 100.0 / NULLIF(at_risk_population, 0), 2)
                                                  AS screening_rate_pct,
        ROUND(abnormal_count * 100.0 / NULLIF(screened_count, 0), 2)
                                                  AS abnormal_rate_pct
    FROM patient_month_classified
    GROUP BY report_year, report_month, year_month_key
)

SELECT
    report_year                              AS year,
    strftime(strptime(year_month_key::VARCHAR, '%Y%m'), '%b %Y')
                                              AS period,
    at_risk_population,
    screened_count,
    normal_count,
    elevated_count,
    abnormal_count,
    screening_rate_pct,
    abnormal_rate_pct
FROM screening_metrics_monthly
ORDER BY year_month_key
""").fetchall()

# Print screening results
print(f"{'Period':<12} {'At-Risk':>8} {'Screened':>9} {'Normal':>7} {'Elevated':>9} {'Abnormal':>9} {'Scr%':>6} {'Abn%':>6}")
print("-" * 70)
for row in screening:
    year, period, at_risk, scr, norm, elev, abn, scr_pct, abn_pct = row
    print(f"{period:<12} {at_risk:>8} {scr:>9} {norm:>7} {elev:>9} {abn:>9} {scr_pct:>5.1f}% {abn_pct:>5.1f}%")

# ─── REPORT 2: PREVALENCE (ANNUAL) ─────────────────────────────────────
print("\n" + "-" * 70)
print("REPORT 2: PREVALENCE REPORT (ANNUAL)")
print("-" * 70)

prevalence = con.execute("""
WITH
total_population AS (
    SELECT
        _ID                                    AS patient_key,
        NATIONALID                             AS national_id_hash,
        DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
        DATEOFDEATH                            AS date_of_death,
        CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
              AND NATIONALID IS NOT NULL
              AND NATIONALID <> ''
              AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
             THEN TRUE ELSE FALSE
        END                                    AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS
),

dm_diagnoses AS (
    SELECT
        PATIENTUID                             AS patient_key,
        MIN(DIAGNOSIS_DATE)                    AS first_e11_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E11'
    GROUP BY PATIENTUID
),

prevalence_snapshot AS (
    SELECT
        tp.patient_key,
        tp.is_in_total_population,
        dx.first_e11_date,
        CASE WHEN dx.first_e11_date IS NOT NULL
              AND dx.first_e11_date <= '2025-12-31'
             THEN TRUE ELSE FALSE
        END                                    AS has_e11_at_year_end,
        CASE WHEN dx.first_e11_date >= '2025-01-01'
              AND dx.first_e11_date <= '2025-12-31'
             THEN TRUE ELSE FALSE
        END                                    AS is_incident_2025,
        CASE WHEN dx.first_e11_date < '2025-01-01'
             THEN TRUE ELSE FALSE
        END                                    AS is_pre_existing
    FROM total_population tp
    LEFT JOIN dm_diagnoses dx USING (patient_key)
)

SELECT
    COUNT(DISTINCT CASE WHEN is_in_total_population = TRUE
                    THEN patient_key END)      AS total_population,
    COUNT(DISTINCT CASE WHEN has_e11_at_year_end = TRUE
                    THEN patient_key END)      AS prevalent_dm_count,
    COUNT(DISTINCT CASE WHEN is_incident_2025 = TRUE
                    THEN patient_key END)      AS incident_during_year,
    COUNT(DISTINCT CASE WHEN is_pre_existing = TRUE
                          AND has_e11_at_year_end = TRUE
                    THEN patient_key END)      AS pre_existing_dm_count,
    ROUND(prevalent_dm_count * 100.0 / NULLIF(total_population, 0), 2)
                                               AS prevalence_rate_pct
FROM prevalence_snapshot
""").fetchone()

total_pop, prev_count, inc_count, preex_count, prev_rate = prevalence
print(f"  Total Population (age>18, alive, National ID): {total_pop:>5}")
print(f"  Prevalent DM (E11 at Dec 31, 2025):            {prev_count:>5}")
print(f"    - Incident during 2025 (newly diagnosed):    {inc_count:>5}")
print(f"    - Pre-existing before 2025:                  {preex_count:>5}")
print(f"  Prevalence Rate:                               {prev_rate:>5.1f}%")

# ─── REPORT 3: INCIDENCE (MONTHLY) ─────────────────────────────────────
print("\n" + "-" * 70)
print("REPORT 3: INCIDENCE REPORT (MONTHLY)")
print("-" * 70)

incidence = con.execute("""
WITH
total_population AS (
    SELECT
        _ID                                    AS patient_key,
        CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
              AND NATIONALID IS NOT NULL
              AND NATIONALID <> ''
              AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
             THEN TRUE ELSE FALSE
        END                                    AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS
),

all_dm_diagnoses AS (
    SELECT
        PATIENTUID                             AS patient_key,
        MIN(DIAGNOSIS_DATE)                    AS first_any_dm_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ('E10','E11','E13','E14','O24')
    GROUP BY PATIENTUID
),

e11_diagnosis AS (
    SELECT
        PATIENTUID                             AS patient_key,
        MIN(DIAGNOSIS_DATE)                    AS first_e11_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = 'E11'
    GROUP BY PATIENTUID
),

patient_months_spine AS (
    SELECT
        tp.patient_key,
        m.year_month_key,
        m.report_month,
        tp.is_in_total_population,
        adm.first_any_dm_date,
        e11.first_e11_date,
        CASE WHEN tp.is_in_total_population
              AND (adm.first_any_dm_date IS NULL
                   OR adm.first_any_dm_date >= strptime(m.year_month_key::VARCHAR, '%Y%m'))
             THEN TRUE ELSE FALSE
        END                                    AS is_at_risk_start
    FROM total_population tp
    CROSS JOIN (
        SELECT
            2025 * 100 + seq                    AS year_month_key,
            seq                                  AS report_month
        FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)
    ) m
    LEFT JOIN all_dm_diagnoses adm ON tp.patient_key = adm.patient_key
    LEFT JOIN e11_diagnosis e11 ON tp.patient_key = e11.patient_key
    WHERE tp.is_in_total_population = TRUE
)

SELECT
    report_month,
    strftime(strptime(year_month_key::VARCHAR, '%Y%m'), '%b %Y')
                                              AS period,
    COUNT(DISTINCT CASE WHEN is_at_risk_start = TRUE
                    THEN patient_key END)     AS at_risk_population_start,
    COUNT(DISTINCT CASE WHEN is_at_risk_start = TRUE
                          AND first_e11_date IS NOT NULL
                          AND first_e11_date >= strptime(year_month_key::VARCHAR, '%Y%m')
                          AND first_e11_date < strptime(year_month_key::VARCHAR, '%Y%m') + INTERVAL 1 MONTH
                    THEN patient_key END)     AS incident_cases,
    ROUND(incident_cases * 100000.0 / NULLIF(at_risk_population_start, 0), 2)
                                              AS incidence_rate_per_100k
FROM patient_months_spine
GROUP BY report_month, year_month_key
ORDER BY year_month_key
""").fetchall()

print(f"{'Period':<12} {'At-Risk Start':>14} {'New Cases':>10} {'Rate/100k':>10}")
print("-" * 50)
for row in incidence:
    month, period, at_risk, new_cases, rate = row
    print(f"{period:<12} {at_risk:>14} {new_cases:>10} {rate:>10}")

# ─── DIAGNOSTIC: Verify key patients ────────────────────────────────────
print("\n" + "-" * 70)
print("DIAGNOSTIC: Key Patient Verification")
print("-" * 70)

diag = con.execute("""
WITH
tp AS (
    SELECT _ID AS pid,
           CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
                 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN 'IN' ELSE 'OUT' END AS eligible
    FROM NMR.LEANHIS_PATIENTS
),
dx AS (
    SELECT PATIENTUID AS pid,
           MIN(DIAGNOSIS_DATE) AS first_dx,
           LIST(DISTINCT TRIM(UPPER(ICD10_CODE))) AS codes
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    GROUP BY PATIENTUID
),
labs AS (
    SELECT lr.PATIENTUID AS pid,
           COUNT(*) AS lab_count,
           LIST(DISTINCT
             CASE WHEN lrv.NAME LIKE '%glucose%' OR lrv.NAME LIKE '%GLUCOSE%' THEN 'FBS'
                  WHEN lrv.NAME LIKE '%A1c%' OR lrv.NAME LIKE '%Hemoglobin%' THEN 'A1C'
             END) AS test_types
    FROM NMR.LEANHIS_LABRESULTS lr
    JOIN NMR.LEANHIS_LABRESULTS_RESULTVALUES lrv ON lr._ID = lrv.LABRESULTS_ID
    GROUP BY lr.PATIENTUID
)
SELECT tp.pid,
       tp.eligible,
       COALESCE(dx.first_dx::VARCHAR, 'none') AS first_dx,
       COALESCE(dx.codes::VARCHAR, 'none') AS dx_codes,
       COALESCE(labs.lab_count, 0) AS n_labs,
       COALESCE(labs.test_types::VARCHAR, 'none') AS tests
FROM tp
LEFT JOIN dx ON tp.pid = dx.pid
LEFT JOIN labs ON tp.pid = labs.pid
ORDER BY tp.pid
""").fetchall()

print(f"{'PID':<6} {'Eligible':<9} {'First Dx':<12} {'Dx Codes':<16} {'#Labs':<6} {'Tests'}")
print("-" * 80)
for row in diag:
    pid, eligible, first_dx, dx_codes, n_labs, tests = row
    print(f"{pid:<6} {eligible:<9} {first_dx:<12} {dx_codes:<16} {n_labs:<6} {tests}")

con.close()
print("\nDone.")
