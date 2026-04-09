import os
import json
import zipfile
import psycopg2
import glob

from src.config import DB_PARAMS

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "od")
STAGING_DIR = os.path.join(BASE_DIR, "data", "staging", "od")

# DDL Queries to set up the Analytics Schema
DDL_QUERIES = """
CREATE SCHEMA IF NOT EXISTS analytics;

-- 1. Drop existing tables to allow re-runs
DROP TABLE IF EXISTS analytics.fact_od_mensual CASCADE;
DROP TABLE IF EXISTS analytics.dim_zonas_censales CASCADE;

-- 2. Create Spatial Dimension Table (GeoJSON)
CREATE TABLE analytics.dim_zonas_censales (
    zonificacion_censal_codigo VARCHAR(50) PRIMARY KEY,
    municipio_codigo_ine INT,
    municipio_nombre VARCHAR(255),
    geometria GEOMETRY(Polygon, 4326)
);

-- 3. Create Fact Table for OD Matrix
CREATE TABLE analytics.fact_od_mensual (
    linea_id VARCHAR(50),
    titulo_id INT,
    viaje_hora INT,
    parada_entrada_id VARCHAR(50),
    parada_salida_id VARCHAR(50),
    pasajeros_cantidad INT,
    fechas_calculadas INT,
    linea_siguiente_id VARCHAR(50),
    linea_anterior_id VARCHAR(50),
    matriz_id VARCHAR(100),
    tipo_dia VARCHAR(20)
);

-- 4. Create Temporary Staging Tables for CSVs (Handles the 10 vs 11 columns issue)
DROP TABLE IF EXISTS stg_laborables;
CREATE TEMP TABLE stg_laborables (
    linea_id VARCHAR(50), titulo_id INT, viaje_hora INT, parada_entrada_id VARCHAR(50),
    parada_salida_id VARCHAR(50), pasajeros_cantidad INT, fechas_calculadas INT,
    linea_siguiente_id VARCHAR(50), linea_anterior_id VARCHAR(50), matriz_id VARCHAR(100)
);

DROP TABLE IF EXISTS stg_festivos;
CREATE TEMP TABLE stg_festivos (
    linea_id VARCHAR(50), titulo_id INT, viaje_hora INT, parada_entrada_id VARCHAR(50),
    parada_salida_id VARCHAR(50), pasajeros_cantidad INT, tipo_dia VARCHAR(20), 
    fechas_calculadas INT, linea_siguiente_id VARCHAR(50), linea_anterior_id VARCHAR(50), matriz_id VARCHAR(100)
);
"""


def extract_latest_od():
    """Extracts the latest OD zip files to the staging directory."""
    print("--- Extracting OD Files to Staging ---")

    if not os.path.exists(RAW_DIR):
        raise FileNotFoundError(f"Raw directory not found: {RAW_DIR}")

    date_folders = sorted([f.path for f in os.scandir(RAW_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded OD data found in raw directory.")

    latest_folder = date_folders[0]
    os.makedirs(STAGING_DIR, exist_ok=True)

    # Extract all ZIPs found in the folder
    zip_files = glob.glob(os.path.join(latest_folder, "*.zip"))
    for zip_path in zip_files:
        print(f"Unzipping {os.path.basename(zip_path)}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(STAGING_DIR)

    # Copy GeoJSONs directly to staging
    geojson_files = glob.glob(os.path.join(latest_folder, "*.geojson"))
    import shutil
    for geo_path in geojson_files:
        shutil.copy(geo_path, STAGING_DIR)

    return STAGING_DIR


def load_spatial_data(cur, staging_path):
    """Loads the Census GeoJSON into PostGIS."""
    print("--- Loading Spatial Data (GeoJSON) ---")

    # Find the census geojson
    geojson_files = glob.glob(os.path.join(staging_path, "*censal*.geojson"))
    if not geojson_files:
        print("Warning: No census GeoJSON found. Skipping spatial load.")
        return

    geojson_path = geojson_files[0]
    print(f"Parsing {os.path.basename(geojson_path)}...")

    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    inserted = 0

    for feature in features:
        props = feature.get('properties', {})
        geom = json.dumps(feature.get('geometry'))

        cod_censal = str(props.get('zonificacion_censal_codigo', ''))
        cod_ine = props.get('municipio_codigo_ine')
        nombre = props.get('municipio_nombre', 'Desconocido')

        if cod_censal:
            # PostGIS ST_GeomFromGeoJSON converts the string into a real database polygon
            insert_query = """
                INSERT INTO analytics.dim_zonas_censales 
                (zonificacion_censal_codigo, municipio_codigo_ine, municipio_nombre, geometria)
                VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
                ON CONFLICT (zonificacion_censal_codigo) DO NOTHING;
            """
            cur.execute(insert_query, (cod_censal, cod_ine, nombre, geom))
            inserted += 1

    print(f"Successfully loaded {inserted} census zones into PostGIS.")


def load_matrix_csvs(cur, staging_path):
    """Loads the OD CSVs handling the schema differences (10 vs 11 columns)."""
    print("--- Loading OD Matrix CSVs ---")

    csv_files = glob.glob(os.path.join(staging_path, "*.csv"))

    laborables_file = None
    festivos_file = None

    for f in csv_files:
        name = os.path.basename(f).lower()
        if "no laborable" in name or "no_laborable" in name or "festivo" in name:
            festivos_file = f
        elif "laborable" in name:
            laborables_file = f

    # 1. Load Laborables (10 columns)
    if laborables_file:
        print(f"Loading {os.path.basename(laborables_file)} into temporary staging...")
        with open(laborables_file, 'r', encoding='utf-8-sig') as f:
            cur.copy_expert("COPY stg_laborables FROM STDIN WITH CSV HEADER DELIMITER ','", f)

        print("Transforming and inserting laborables into final table...")
        cur.execute("""
            INSERT INTO analytics.fact_od_mensual
            SELECT linea_id, titulo_id, viaje_hora, parada_entrada_id, parada_salida_id, 
                   pasajeros_cantidad, fechas_calculadas, linea_siguiente_id, linea_anterior_id, 
                   matriz_id, 'Laborable' AS tipo_dia
            FROM stg_laborables;
        """)

    # 2. Load Festivos/No Laborables (11 columns)
    if festivos_file:
        print(f"Loading {os.path.basename(festivos_file)} into temporary staging...")
        with open(festivos_file, 'r', encoding='utf-8-sig') as f:
            cur.copy_expert("COPY stg_festivos FROM STDIN WITH CSV HEADER DELIMITER ','", f)

        print("Transforming and inserting festivos into final table...")
        cur.execute("""
            INSERT INTO analytics.fact_od_mensual
            SELECT linea_id, titulo_id, viaje_hora, parada_entrada_id, parada_salida_id, 
                   pasajeros_cantidad, fechas_calculadas, linea_siguiente_id, linea_anterior_id, 
                   matriz_id, tipo_dia
            FROM stg_festivos;
        """)


def main():
    conn = None
    try:
        staging_path = extract_latest_od()

        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("Setting up schemas and tables...")
        cur.execute(DDL_QUERIES)

        load_spatial_data(cur, staging_path)
        load_matrix_csvs(cur, staging_path)

        conn.commit()
        print("--- ETL for OD Matrix Completed Successfully! ---")

    except Exception as e:
        print(f"ETL Process Failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cur.close()
            conn.close()


if __name__ == "__main__":
    main()