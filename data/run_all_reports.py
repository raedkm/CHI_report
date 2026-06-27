"""
run_all_reports.py
==================
Runs all 4 condition reports (DM, HTN, DLP, Obesity) against chi_sim.db.
Each condition produces 3 reports: Screening (monthly), Prevalence (annual), Incidence (monthly).

Usage:
    uv run python run_all_reports.py [condition]

    condition: dm | htn | dlp | ob | all (default: all)
"""
import duckdb, os, sys

DB = os.path.join(os.path.dirname(__file__), "chi_sim.db")

# ===========================================================================
# SHARED HELPERS
# ===========================================================================

def header(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def subheader(title):
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def run_query(con, sql, params=None):
    """Run a query and return all rows. Handles sql with optional params."""
    if params:
        return con.execute(sql, params).fetchall()
    return con.execute(sql).fetchall()

def print_table(columns, rows, formats=None):
    """Print a formatted table."""
    if not formats:
        formats = [str] * len(columns)
    col_widths = [max(len(c), max((len(fmt(r[i])) for r in rows), default=0)) for i, (c, fmt) in enumerate(zip(columns, formats))]
    # Header
    header_parts = [c.ljust(col_widths[i]) for i, c in enumerate(columns)]
    print("  " + "  ".join(header_parts))
    print("  " + "-" * (sum(col_widths) + 2 * (len(columns) - 1)))
    # Rows
    for row in rows:
        parts = [fmt(row[i]).ljust(col_widths[i]) if i < len(formats) else str(row[i]).ljust(col_widths[i]) for i, fmt in enumerate(formats)]
        print("  " + "  ".join(parts))


# ===========================================================================
# CONDITION CONFIGURATIONS
# ===========================================================================

CONDITIONS = {
    "dm": {
        "name": "Diabetes Mellitus (DM)",
        "icd10_codes": ["E10", "E11", "E13", "E14", "O24"],
        "target_icd10": "E11",
        "has_labs": True,
        "has_obs": True,
        "lab_names": [
            "Fasting glucose",
            "Fasting glucose [Mass or Moles/volume] in Serum or Plasma",
            "GLUCOSE FASTING",
            "Hemoglobin A1c."
        ],
        "obs_names": ["Fasting glucose", "Hemoglobin A1c."],
    },
    "htn": {
        "name": "Hypertension (HTN)",
        "icd10_codes": ["I10", "I11", "I12", "I13", "I15"],
        "target_icd10": "I10",
        "has_labs": False,
        "has_obs": True,
        "obs_names": ["Systolic BP", "Diastolic BP"],
    },
    "dlp": {
        "name": "Dyslipidemia (DLP)",
        "icd10_codes": ["E78"],
        "target_icd10": "E78",
        "has_labs": True,
        "has_obs": True,
        "lab_names": [
            "Cholesterol.in HDL", "Cholesterol in HDL",
            "Cholesterol.in LDL",
            "Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay",
            "Cholesterol in Serum or Plasma", "Triglyceride"
        ],
        "obs_names": ["Cholesterol.in HDL", "Cholesterol in HDL", "Triglyceride"],
    },
    "ob": {
        "name": "Obesity (OB)",
        "icd10_codes": ["E66"],
        "target_icd10": "E66",
        "has_labs": False,
        "has_obs": True,
        "obs_names": ["BMI"],
    },
}


# ===========================================================================
# REPORT GENERATOR — builds and runs all 3 reports for one condition
# ===========================================================================

def run_condition(con, cfg):
    """Run all 3 reports for a given condition configuration."""
    name = cfg["name"]
    icd10_list = cfg["icd10_codes"]
    target_icd10 = cfg["target_icd10"]
    has_labs = cfg["has_labs"]
    has_obs = cfg["has_obs"]
    lab_names = cfg.get("lab_names", [])
    obs_names = cfg.get("obs_names", [])

    # Build the lab name IN clause for SQL
    lab_names_sql = ", ".join(f"'{n}'" for n in lab_names) if lab_names else "''"
    obs_names_sql = ", ".join(f"'{n}'" for n in obs_names) if obs_names else "''"
    icd10_sql = ", ".join(f"'{c}'" for c in icd10_list)

    # Build the source query union parts
    def build_marker_cases(prefix="lrv"):
        """Generate CASE statements for marker extraction based on condition.
        Returns (result_name_case, value_extract) with {p} placeholders for table alias."""
        if cfg == CONDITIONS["dm"]:
            return """
        CASE
            WHEN {p}.NAME IN ('Fasting glucose','Fasting glucose [Mass or Moles/volume] in Serum or Plasma','GLUCOSE FASTING')
                THEN 'FBS'
            WHEN {p}.NAME = 'Hemoglobin A1c.' THEN 'A1C'
        END""", """
        NULLIF(TRY_CAST(regexp_extract({p}.RESULTVALUE, '[0-9]+(\\\\.[0-9]+)?') AS DECIMAL(10,2)), 0)
        """
        elif cfg == CONDITIONS["htn"]:
            return """
        CASE
            WHEN {p}.NAME = 'Systolic BP' THEN 'SYS'
            WHEN {p}.NAME = 'Diastolic BP' THEN 'DIA'
        END""", """
        NULLIF(TRY_CAST(regexp_extract({p}.RESULTVALUE, '[0-9]+(\\\\.[0-9]+)?') AS DECIMAL(10,2)), 0)
        """
        elif cfg == CONDITIONS["dlp"]:
            return """
        CASE
            WHEN {p}.NAME IN ('Cholesterol.in HDL','Cholesterol in HDL') THEN 'HDL'
            WHEN {p}.NAME IN ('Cholesterol.in LDL','Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay') THEN 'LDL'
            WHEN {p}.NAME = 'Cholesterol in Serum or Plasma' THEN 'CHOL'
            WHEN {p}.NAME = 'Triglyceride' THEN 'TRIG'
        END""", """
        NULLIF(TRY_CAST(regexp_extract({p}.RESULTVALUE, '[0-9]+(\\\\.[0-9]+)?') AS DECIMAL(10,2)), 0)
        """
        elif cfg == CONDITIONS["ob"]:
            return """
        'BMI'
        """, """
        NULLIF(TRY_CAST(regexp_extract({p}.RESULTVALUE, '[0-9]+(\\\\.[0-9]+)?') AS DECIMAL(10,2)), 0)
        """
        return "", ""

    marker_case, value_extract = build_marker_cases()

    # Build the classification SQL
    def build_classification():
        """Generate the screening category classification SQL."""
        if cfg == CONDITIONS["dm"]:
            # FBS + A1C -> worst of both (inline sub-categories)
            return """
        -- DM Classification: worst of A1C and FBS (inline sub-categories)
        CASE greatest(
            CASE WHEN pml.last_a1c_value IS NULL THEN 0
                 WHEN pml.last_a1c_value < 5.7 THEN 1
                 WHEN pml.last_a1c_value <= 6.4 THEN 2
                 ELSE 3 END,
            CASE WHEN pml.last_fbs_value IS NULL THEN 0
                 WHEN pml.last_fbs_value < 30 THEN
                     CASE WHEN pml.last_fbs_value <= 5.5 THEN 1
                          WHEN pml.last_fbs_value <= 6.9 THEN 2
                          ELSE 3 END
                 ELSE
                     CASE WHEN pml.last_fbs_value <= 99 THEN 1
                          WHEN pml.last_fbs_value <= 125 THEN 2
                          ELSE 3 END
            END
        ) WHEN 3 THEN 'abnormal' WHEN 2 THEN 'elevated' WHEN 1 THEN 'normal' END AS screening_category,
        CASE WHEN pml.last_fbs_value IS NOT NULL OR pml.last_a1c_value IS NOT NULL
            THEN CONCAT('FBS:', CAST(ROUND(pml.last_fbs_value,1) AS VARCHAR), ' A1C:', CAST(ROUND(pml.last_a1c_value,1) AS VARCHAR))
        END AS secondary_category""", """
        -- Per-marker aggregation (DM)
        MAX(CASE WHEN result_name = 'FBS' THEN value END) AS last_fbs_value,
        MAX(CASE WHEN result_name = 'A1C' THEN value END) AS last_a1c_value""", """
        bool_or(result_name = 'FBS') AS had_marker1,
        bool_or(result_name = 'A1C') AS had_marker2"""
        elif cfg == CONDITIONS["htn"]:
            # SYS + DIA → combined
            return """
        -- HTN Classification: combined SYS/DIA
        CASE
            WHEN pml.last_sys IS NULL OR pml.last_dia IS NULL THEN NULL
            WHEN pml.last_sys >= 130 OR pml.last_dia >= 90 THEN 'abnormal'
            WHEN (pml.last_sys BETWEEN 120 AND 129) OR (pml.last_dia BETWEEN 80 AND 89) THEN 'elevated'
            ELSE 'normal'
        END AS screening_category,
        CASE WHEN pml.last_sys IS NOT NULL AND pml.last_dia IS NOT NULL
            THEN CONCAT('SYS:', CAST(pml.last_sys AS VARCHAR), ' DIA:', CAST(pml.last_dia AS VARCHAR))
        END AS secondary_category""", """
        -- Per-marker aggregation (HTN)
        MAX(CASE WHEN result_name = 'SYS' THEN value END) AS last_sys,
        MAX(CASE WHEN result_name = 'DIA' THEN value END) AS last_dia""", """
        bool_or(result_name = 'SYS') AS had_marker1,
        bool_or(result_name = 'DIA') AS had_marker2"""
        elif cfg == CONDITIONS["dlp"]:
            return """
        -- DLP Classification: worst of HDL, LDL, CHOL, TRIG (gender-specific HDL)
        CASE greatest(
            COALESCE(CASE WHEN pml.last_hdl_value IS NULL THEN 0
                WHEN pms.gender='Male' AND pml.last_hdl_value >= 40 THEN 1
                WHEN pms.gender='Female' AND pml.last_hdl_value >= 50 THEN 1
                ELSE 3 END, 0),
            COALESCE(CASE WHEN pml.last_trig_value IS NULL THEN 0 WHEN pml.last_trig_value < 150 THEN 1 WHEN pml.last_trig_value <= 199 THEN 2 ELSE 3 END, 0),
            COALESCE(CASE WHEN pml.last_chol_value IS NULL THEN 0 WHEN pml.last_chol_value < 200 THEN 1 WHEN pml.last_chol_value <= 239 THEN 2 ELSE 3 END, 0),
            COALESCE(CASE WHEN pml.last_ldl_value IS NULL THEN 0 WHEN pml.last_ldl_value < 130 THEN 1 WHEN pml.last_ldl_value <= 159 THEN 2 ELSE 3 END, 0)
        ) WHEN 3 THEN 'abnormal' WHEN 2 THEN 'elevated' WHEN 1 THEN 'normal' END AS screening_category,
        CASE WHEN pml.last_hdl_value IS NOT NULL
            THEN CONCAT('HDL:', CAST(pml.last_hdl_value AS VARCHAR), ' LDL:', CAST(pml.last_ldl_value AS VARCHAR))
        END AS secondary_category""", """
        -- Per-marker aggregation (DLP)
        MAX(CASE WHEN result_name = 'HDL' THEN value END) AS last_hdl_value,
        MAX(CASE WHEN result_name = 'LDL' THEN value END) AS last_ldl_value,
        MAX(CASE WHEN result_name = 'CHOL' THEN value END) AS last_chol_value,
        MAX(CASE WHEN result_name = 'TRIG' THEN value END) AS last_trig_value""", """
        bool_or(result_name = 'HDL') AS had_marker1,
        bool_or(result_name = 'LDL') AS had_marker2"""
        elif cfg == CONDITIONS["ob"]:
            return """
        -- Obesity Classification (mapped to standard categories)
        CASE
            WHEN pml.last_bmi IS NULL THEN NULL
            WHEN pml.last_bmi < 18.5 THEN 'underweight'
            WHEN pml.last_bmi <= 24.9 THEN 'normal'
            WHEN pml.last_bmi <= 29.9 THEN 'elevated'
            ELSE 'abnormal'
        END AS screening_category,
        CASE WHEN pml.last_bmi IS NOT NULL THEN CAST(pml.last_bmi AS VARCHAR) END AS secondary_category""", """
        -- Per-marker aggregation (Obesity)
        MAX(CASE WHEN result_name = 'BMI' THEN value END) AS last_bmi""", """
        bool_or(result_name = 'BMI') AS had_marker1,
        FALSE AS had_marker2"""
        return "", "", ""

    class_sql, marker_agg, marker_flags = build_classification()

    # Build the source part of the SQL
    def build_source_union():
        """Build the UNION ALL of LABRESULTS and OBSERVATIONS for this condition."""
        parts = []
        visit_range = "pv.STARTDATE >= '2025-01-01' AND pv.STARTDATE < '2026-01-01'"

        if has_labs:
            parts.append(f"""
    SELECT
        lr.PATIENTUID AS patient_key,
        pv.STARTDATE AS visit_date,
        EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
        {marker_case.format(p='lrv')} AS result_name,
        {value_extract.format(p='lrv')} AS value
    FROM NMR.LEANHIS_LABRESULTS lr
    JOIN NMR.LEANHIS_LABRESULTS_RESULTVALUES lrv ON lr._ID = lrv.LABRESULTS_ID
    JOIN NMR.LEANHIS_PATIENTVISITS pv ON lr.PATIENTVISITUID = pv._ID
    WHERE {visit_range}
      AND lrv.NAME IN ({lab_names_sql})
""")

        if has_obs:
            parts.append(f"""
    SELECT
        o.PATIENTUID AS patient_key,
        pv.STARTDATE AS visit_date,
        EXTRACT(YEAR FROM pv.STARTDATE)*100 + EXTRACT(MONTH FROM pv.STARTDATE) AS year_month_key,
        {marker_case.format(p='ov')} AS result_name,
        {value_extract.format(p='ov')} AS value
    FROM NMR.LEANHIS_OBSERVATIONS o
    JOIN NMR.LEANHIS_OBSERVATIONS_OBSERVATIONVALUES ov ON o._ID = ov.OBSERVATIONS_ID
    JOIN NMR.LEANHIS_PATIENTVISITS pv ON o.PATIENTVISITUID = pv._ID
    WHERE {visit_range}
      AND ov.NAME IN ({obs_names_sql})
""")

        return "\nUNION ALL\n".join(parts)

    source_union_sql = build_source_union()

    # Build the full query
    # For HTN, we need paired BP values per visit — aggregate at visit level first
    extra_cte = ""
    if cfg == CONDITIONS["htn"]:
        extra_cte = """,
-- HTN: Aggregate BP per visit (pair SYS+DIA from same visit)
markers_per_visit AS (
    SELECT
        patient_key,
        visit_date,
        year_month_key,
        MAX(CASE WHEN result_name='SYS' THEN value END) AS sys_val,
        MAX(CASE WHEN result_name='DIA' THEN value END) AS dia_val
    FROM markers_raw
    GROUP BY patient_key, visit_date, year_month_key
    HAVING sys_val IS NOT NULL AND dia_val IS NOT NULL
),
markers_filtered AS (
    SELECT patient_key, visit_date, year_month_key, 'SYS' AS result_name, sys_val AS value FROM markers_per_visit
    UNION ALL
    SELECT patient_key, visit_date, year_month_key, 'DIA' AS result_name, dia_val AS value FROM markers_per_visit
)"""
    elif cfg == CONDITIONS["ob"]:
        extra_cte = """,
-- Obesity: Filter BMI to valid range 10-80
markers_filtered AS (
    SELECT * FROM markers_raw WHERE value IS NOT NULL AND value BETWEEN 10 AND 80
)"""
    else:
        extra_cte = """,
markers_filtered AS (
    SELECT * FROM markers_raw WHERE value IS NOT NULL
)"""

    # Determine the screening check
    if cfg == CONDITIONS["dm"]:
        screening_check = "COALESCE(pml.had_marker1, FALSE) OR COALESCE(pml.had_marker2, FALSE)"
    elif cfg == CONDITIONS["htn"]:
        screening_check = "COALESCE(pml.had_marker1, FALSE) AND COALESCE(pml.had_marker2, FALSE)"
    elif cfg == CONDITIONS["dlp"]:
        screening_check = "COALESCE(pml.had_marker1, FALSE) OR COALESCE(pml.had_marker2, FALSE)"
    elif cfg == CONDITIONS["ob"]:
        screening_check = "COALESCE(pml.had_marker1, FALSE)"

    # Determine abnormal/case category value for reporting
    if cfg == CONDITIONS["ob"]:
        case_category = "'obese'"
    else:
        case_category = "'abnormal'"

    sql = f"""
WITH
total_population AS (
    SELECT _ID AS patient_key, NATIONALID, GENDERUID AS gender, DATEOFBIRTH, DATEOFDEATH,
           DATEDIFF('year', DATEOFBIRTH, '2025-01-01') AS age_at_jan1,
           CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
                 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS is_in_total_population
    FROM NMR.LEANHIS_PATIENTS
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
),
all_dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_any_dm_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ({icd10_sql})
    GROUP BY PATIENTUID
),
target_dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_target_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = '{target_icd10}'
    GROUP BY PATIENTUID
),
base_cohort AS (
    SELECT tp.patient_key, tp.gender, tp.age_at_jan1, tp.is_in_total_population,
           COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
           adm.first_any_dm_date, tdx.first_target_date,
           CASE WHEN adm.first_any_dm_date IS NOT NULL THEN TRUE ELSE FALSE END AS has_any_dx,
           CASE WHEN tp.is_in_total_population AND adm.first_any_dm_date IS NULL
                THEN TRUE ELSE FALSE END AS is_in_at_risk
    FROM total_population tp
    LEFT JOIN phc USING (patient_key)
    LEFT JOIN all_dx adm USING (patient_key)
    LEFT JOIN target_dx tdx USING (patient_key)
),
markers_raw AS ({source_union_sql}){extra_cte},
patient_visits AS (
    SELECT PATIENTUID AS patient_key,
           EXTRACT(YEAR FROM STARTDATE)*100 + EXTRACT(MONTH FROM STARTDATE) AS year_month_key
    FROM NMR.LEANHIS_PATIENTVISITS
    WHERE STARTDATE >= '2025-01-01' AND STARTDATE < '2026-01-01'
    GROUP BY PATIENTUID, year_month_key
),
patient_months_spine AS (
    SELECT bc.*, m.year_month_key, m.report_year, m.report_month,
           CASE WHEN bc.first_any_dm_date IS NOT NULL
                 AND bc.first_any_dm_date < strptime(m.year_month_key::VARCHAR, '%Y%m')
                THEN TRUE ELSE FALSE END AS has_dx_before,
           CASE WHEN NOT (bc.first_any_dm_date IS NOT NULL
                 AND bc.first_any_dm_date < strptime(m.year_month_key::VARCHAR, '%Y%m'))
                THEN TRUE ELSE FALSE END AS is_at_risk_start,
           bc.first_target_date
    FROM base_cohort bc
    CROSS JOIN (SELECT seq AS report_month, 2025*100+seq AS year_month_key, 2025 AS report_year
                FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)) m
    WHERE bc.is_in_total_population = TRUE
),
patient_month_markers AS (
    SELECT patient_key, year_month_key,{marker_agg},{marker_flags}
    FROM markers_filtered
    GROUP BY patient_key, year_month_key
),
patient_month_classified AS (
    SELECT pms.*,
           CASE WHEN pv.patient_key IS NOT NULL THEN TRUE ELSE FALSE END AS had_visit,
           COALESCE(pml.had_marker1, FALSE) AS had_marker1,
           COALESCE(pml.had_marker2, FALSE) AS had_marker2,
           CASE WHEN pms.is_at_risk_start AND ({screening_check})
                THEN TRUE ELSE FALSE END AS is_screened,{class_sql},
           CASE WHEN pms.first_target_date IS NOT NULL
                 AND pms.first_target_date >= strptime(pms.year_month_key::VARCHAR, '%Y%m')
                 AND pms.first_target_date < strptime(pms.year_month_key::VARCHAR, '%Y%m') + INTERVAL 1 MONTH
                 AND pms.is_at_risk_start = TRUE
                THEN TRUE ELSE FALSE END AS is_incident_case
    FROM patient_months_spine pms
    LEFT JOIN patient_visits pv ON pms.patient_key=pv.patient_key AND pms.year_month_key=pv.year_month_key
    LEFT JOIN patient_month_markers pml ON pms.patient_key=pml.patient_key AND pms.year_month_key=pml.year_month_key
),
screening_monthly AS (
    SELECT health_cluster, report_year, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk_pop,
           COUNT(DISTINCT CASE WHEN is_screened THEN patient_key END) AS screened,
           COALESCE(COUNT(DISTINCT CASE WHEN is_screened AND screening_category='normal' THEN patient_key END), 0) AS normal_n,
           COALESCE(COUNT(DISTINCT CASE WHEN is_screened AND screening_category='elevated' THEN patient_key END), 0) AS elevated_n,
           COALESCE(COUNT(DISTINCT CASE WHEN is_screened AND screening_category IN ('abnormal','obese','underweight') THEN patient_key END), 0) AS case_n,
           ROUND(COALESCE(screened,0)*100.0/NULLIF(at_risk_pop,0), 2) AS screen_rate,
           ROUND(COALESCE(case_n,0)*100.0/NULLIF(COALESCE(screened,0),0), 2) AS case_rate
    FROM patient_month_classified
    GROUP BY health_cluster, report_year, report_month, year_month_key
)
-- Monthly detail rows (sort_order=0)
SELECT health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk_pop, screened, normal_n, elevated_n, case_n, screen_rate, case_rate,
       year_month_key AS sort_key, 0 AS sort_order
FROM screening_monthly

UNION ALL

-- Cluster subtotal rows (sort_order=1)
SELECT health_cluster,
       '── ' || health_cluster || ' TOTAL ──' AS period,
       SUM(at_risk_pop), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk_pop),0), 2) AS screen_rate,
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0), 2) AS case_rate,
       99999 AS sort_key, 1 AS sort_order
FROM screening_monthly
GROUP BY health_cluster

UNION ALL

-- Grand total row (sort_order=2)
SELECT '── ALL CLUSTERS ──' AS health_cluster,
       '── 2025 ALL CLUSTERS ──' AS period,
       SUM(at_risk_pop), SUM(screened), SUM(normal_n), SUM(elevated_n), SUM(case_n),
       ROUND(SUM(screened)*100.0/NULLIF(SUM(at_risk_pop),0), 2) AS screen_rate,
       ROUND(SUM(case_n)*100.0/NULLIF(SUM(screened),0), 2) AS case_rate,
       99999 AS sort_key, 2 AS sort_order
FROM screening_monthly
ORDER BY health_cluster, sort_order, sort_key
"""
    rows = run_query(con, sql)

    # --- SCREENING REPORT ---
    subheader(f"{name} — Report 1: Screening (Monthly)")
    print_table(
        ["Cluster", "Period", "At-Risk", "Screened", "Normal", "Elevated", "Case", "Scr%", "Case%"],
        rows,
        [str, str, str, str, str, str, str,
         lambda v: f"{v:.1f}%" if v is not None else "  N/A", lambda v: f"{v:.1f}%" if v is not None else "  N/A"]
    )

    # --- PREVALENCE REPORT ---
    prev_sql = f"""
WITH
total_population AS (
    SELECT _ID AS patient_key,
           CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
                 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS eligible
    FROM NMR.LEANHIS_PATIENTS
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
),
target_dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_target_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = '{target_icd10}'
    GROUP BY PATIENTUID
)
-- Per-cluster rows
SELECT
    COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
    COUNT(DISTINCT CASE WHEN eligible THEN tp.patient_key END) AS total_pop,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date <= '2025-12-31' THEN tp.patient_key END) AS prevalent,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date BETWEEN '2025-01-01' AND '2025-12-31' THEN tp.patient_key END) AS incident_yr,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date < '2025-01-01' THEN tp.patient_key END) AS pre_existing,
    ROUND(prevalent*100.0/NULLIF(total_pop,0), 2) AS prev_rate,
    0 AS sort_order
FROM total_population tp
LEFT JOIN phc USING (patient_key)
LEFT JOIN target_dx tdx USING (patient_key)
GROUP BY health_cluster

UNION ALL

-- Grand total
SELECT
    '── ALL CLUSTERS ──' AS health_cluster,
    COUNT(DISTINCT CASE WHEN eligible THEN tp.patient_key END) AS total_pop,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date <= '2025-12-31' THEN tp.patient_key END) AS prevalent,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date BETWEEN '2025-01-01' AND '2025-12-31' THEN tp.patient_key END) AS incident_yr,
    COUNT(DISTINCT CASE WHEN tdx.first_target_date < '2025-01-01' THEN tp.patient_key END) AS pre_existing,
    ROUND(COUNT(DISTINCT CASE WHEN tdx.first_target_date <= '2025-12-31' THEN tp.patient_key END)*100.0
          / NULLIF(COUNT(DISTINCT CASE WHEN eligible THEN tp.patient_key END),0), 2) AS prev_rate,
    2 AS sort_order
FROM total_population tp
LEFT JOIN phc USING (patient_key)
LEFT JOIN target_dx tdx USING (patient_key)
ORDER BY health_cluster, sort_order
"""
    rows = run_query(con, prev_sql)
    subheader(f"{name} — Report 2: Prevalence (Annual)")
    print_table(
        ["Cluster", "Total Pop", "Prevalent", "Incident", "Pre-Existing", "Rate"],
        rows,
        [str, str, str, str, str, lambda v: f"{v:.1f}%"]
    )

    # --- INCIDENCE REPORT ---
    inc_sql = f"""
WITH
total_population AS (
    SELECT _ID AS patient_key,
           CASE WHEN DATEDIFF('year', DATEOFBIRTH, '2025-01-01') > 18
                 AND NATIONALID IS NOT NULL AND NATIONALID <> ''
                 AND (DATEOFDEATH IS NULL OR DATEOFDEATH >= '2025-01-01')
                THEN TRUE ELSE FALSE END AS eligible
    FROM NMR.LEANHIS_PATIENTS
),
phc AS (
    SELECT PATIENTUID AS patient_key, HEALTH_CLUSTER AS health_cluster_raw
    FROM NMR.LEANHIS_PHC_ASSIGNMENT
),
all_dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_dx
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) IN ({icd10_sql})
    GROUP BY PATIENTUID
),
target_dx AS (
    SELECT PATIENTUID AS patient_key, MIN(DIAGNOSIS_DATE) AS first_target_date
    FROM NMR.LEANHIS_DIAGNOSIS_CODES
    WHERE TRIM(UPPER(ICD10_CODE)) = '{target_icd10}'
    GROUP BY PATIENTUID
),
spine AS (
    SELECT p._ID AS patient_key, COALESCE(phc.health_cluster_raw, 'Unassigned') AS health_cluster,
           m.year_month_key, m.report_month,
           eligible,
           adm.first_dx, tdx.first_target_date
    FROM NMR.LEANHIS_PATIENTS p
    CROSS JOIN (SELECT seq AS report_month, 2025*100+seq AS year_month_key
                FROM (VALUES (1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12)) AS m(seq)) m
    LEFT JOIN total_population tp ON p._ID=tp.patient_key
    LEFT JOIN phc ON p._ID=phc.patient_key
    LEFT JOIN all_dx adm ON p._ID=adm.patient_key
    LEFT JOIN target_dx tdx ON p._ID=tdx.patient_key
    WHERE eligible
),
at_risk_spine AS (
    SELECT *, CASE WHEN first_dx IS NULL OR first_dx >= strptime(year_month_key::VARCHAR,'%Y%m')
                   THEN TRUE ELSE FALSE END AS is_at_risk_start
    FROM spine
),
incidence_monthly AS (
    SELECT health_cluster, report_month, year_month_key,
           COUNT(DISTINCT CASE WHEN is_at_risk_start THEN patient_key END) AS at_risk,
           COUNT(DISTINCT CASE WHEN is_at_risk_start AND first_target_date IS NOT NULL
                                AND first_target_date >= strptime(year_month_key::VARCHAR,'%Y%m')
                                AND first_target_date < strptime(year_month_key::VARCHAR,'%Y%m') + INTERVAL 1 MONTH
                           THEN patient_key END) AS incident,
           ROUND(incident*100000.0/NULLIF(at_risk,0), 2) AS rate
    FROM at_risk_spine
    GROUP BY health_cluster, report_month, year_month_key
)
-- Monthly detail rows (sort_order=0)
SELECT health_cluster,
       strftime(strptime(year_month_key::VARCHAR,'%Y%m'),'%b %Y') AS period,
       at_risk, incident, rate,
       year_month_key AS sort_key, 0 AS sort_order
FROM incidence_monthly

UNION ALL

-- Cluster subtotal rows (sort_order=1)
SELECT health_cluster,
       '── ' || health_cluster || ' TOTAL ──' AS period,
       NULL AS at_risk, SUM(incident) AS incident,
       ROUND(SUM(incident)*100000.0/NULLIF(MAX(CASE WHEN report_month=1 THEN at_risk END),0), 2) AS rate,
       99999 AS sort_key, 1 AS sort_order
FROM incidence_monthly
GROUP BY health_cluster

UNION ALL

-- Grand total row (sort_order=2)
SELECT '── ALL CLUSTERS ──' AS health_cluster,
       '── 2025 ALL CLUSTERS ──' AS period,
       NULL AS at_risk, SUM(incident) AS incident,
       ROUND(SUM(incident)*100000.0/NULLIF(SUM(CASE WHEN report_month=1 THEN at_risk END),0), 2) AS rate,
       99999 AS sort_key, 2 AS sort_order
FROM incidence_monthly
ORDER BY health_cluster, sort_order, sort_key
"""
    rows = run_query(con, inc_sql)
    subheader(f"{name} — Report 3: Incidence (Monthly)")
    print_table(
        ["Cluster", "Period", "At-Risk Start", "New Cases", "Rate/100k"],
        rows,
        [str, str, str, str, lambda v: f"{v:.1f}" if v is not None else "  N/A"]
    )


# ===========================================================================
# MAIN
# ===========================================================================

if __name__ == "__main__":
    condition = sys.argv[1] if len(sys.argv) > 1 else "all"
    con = duckdb.connect(DB)

    header("CHI REPORTS — ALL CONDITIONS")
    print(f"  Database: {DB}")
    print(f"  Report Year: 2025")

    if condition == "all":
        for key in ["dm", "htn", "dlp", "ob"]:
            run_condition(con, CONDITIONS[key])
    elif condition in CONDITIONS:
        run_condition(con, CONDITIONS[condition])
    else:
        print(f"Unknown condition: {condition}. Use: dm, htn, dlp, ob, all")
        con.close()
        sys.exit(1)

    con.close()
    header("ALL REPORTS COMPLETE")
