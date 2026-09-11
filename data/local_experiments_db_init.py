#!/usr/bin/env python3
"""Initialize the local experiment database with nano-bio schema."""

import sqlite3
import os
import sys


def init_local_experiment_db(db_path: str) -> None:
    """Create tables for local nanomaterial experiment data."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Materials table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT,
            core_element TEXT,
            coating TEXT,
            size_mean_nm REAL,
            size_std_nm REAL,
            zeta_potential_mv REAL,
            hydrodynamic_diameter_nm REAL,
            shape TEXT,
            band_gap_ev REAL,
            synthesis_method TEXT,
            characterization_methods TEXT,
            notes TEXT
        )
    """)

    # Antibacterial assays
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS antibacterial_assays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            bacterium_name TEXT NOT NULL,
            gram_stain TEXT,
            is_probiotic INTEGER DEFAULT 0,
            is_pathogen INTEGER DEFAULT 0,
            MIC_ug_ml REAL,
            MBC_ug_ml REAL,
            log_reduction REAL,
            time_to_99pct_kill_min REAL,
            pH REAL,
            temperature_C REAL,
            assay_method TEXT,
            in_vitro_or_in_vivo TEXT DEFAULT 'in_vitro',
            biological_replicates INTEGER DEFAULT 3,
            notes TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    """)

    # Enzyme-like activity assays
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enzyme_activity_assays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            enzyme_type TEXT NOT NULL,
            activity_level TEXT,
            km_value REAL,
            vmax_value REAL,
            kcat_value REAL,
            substrate TEXT,
            pH_optimal REAL,
            temp_optimal_C REAL,
            ros_type_detected TEXT,
            detection_method TEXT,
            biological_replicates INTEGER DEFAULT 3,
            notes TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    """)

    # Toxicity assays
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS toxicity_assays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            endpoint_type TEXT NOT NULL,
            cell_line_or_organism TEXT,
            concentration_ug_ml REAL,
            viability_pct REAL,
            ic50_ug_ml REAL,
            ld50_mg_kg REAL,
            hemolysis_rate_pct REAL,
            organ_damage_type TEXT,
            organ_damage_severity TEXT,
            affected_organ TEXT,
            exposure_time_h REAL,
            assay_method TEXT,
            biological_replicates INTEGER DEFAULT 3,
            notes TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    """)

    conn.commit()
    conn.close()
    print(f"Local experiment DB initialized at {db_path}")


if __name__ == "__main__":
    db_path = os.environ.get(
        "LOCAL_EXP_DB_PATH",
        os.path.join(os.path.dirname(__file__), "..", "data", "local_experiments.db")
    )
    db_path = os.path.realpath(db_path)
    init_local_experiment_db(db_path)
