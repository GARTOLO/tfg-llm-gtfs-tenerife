import os
import zipfile
import psycopg2

from src.config import DB_PARAMS

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "gtfs")
STAGING_DIR = os.path.join(BASE_DIR, "data", "staging", "gtfs")

# SQL Statements to Drop, Create Schema and Tables
DDL_QUERIES = """
-- 1. Drop existing tables to ensure idempotency (overwrite data)
DROP TABLE IF EXISTS gtfs_raw.stop_times CASCADE;
DROP TABLE IF EXISTS gtfs_raw.trips CASCADE;
DROP TABLE IF EXISTS gtfs_raw.shapes CASCADE;
DROP TABLE IF EXISTS gtfs_raw.calendar_dates CASCADE;
DROP TABLE IF EXISTS gtfs_raw.calendar CASCADE;
DROP TABLE IF EXISTS gtfs_raw.stops CASCADE;
DROP TABLE IF EXISTS gtfs_raw.routes CASCADE;
DROP TABLE IF EXISTS gtfs_raw.agency CASCADE;

CREATE SCHEMA IF NOT EXISTS gtfs_raw;

-- 2. Create Master Tables
CREATE TABLE gtfs_raw.agency (
    agency_id VARCHAR(50) PRIMARY KEY,
    agency_name VARCHAR(255),
    agency_url VARCHAR(255),
    agency_timezone VARCHAR(50),
    agency_lang VARCHAR(10),
    agency_phone VARCHAR(50)
);

CREATE TABLE gtfs_raw.routes (
    route_id VARCHAR(50) PRIMARY KEY,
    agency_id VARCHAR(50),
    route_short_name VARCHAR(50),
    route_long_name VARCHAR(255),
    route_type INT,
    route_url VARCHAR(255),
    route_color VARCHAR(10),
    route_text_color VARCHAR(10)
);

CREATE TABLE gtfs_raw.stops (
    stop_id VARCHAR(50) PRIMARY KEY,
    stop_name VARCHAR(255),
    stop_lat DOUBLE PRECISION,
    stop_lon DOUBLE PRECISION,
    stop_url VARCHAR(255)
);

CREATE TABLE gtfs_raw.calendar (
    service_id VARCHAR(50) PRIMARY KEY,
    monday INT, tuesday INT, wednesday INT, thursday INT, friday INT, saturday INT, sunday INT,
    start_date VARCHAR(8),
    end_date VARCHAR(8)
);

CREATE TABLE gtfs_raw.calendar_dates (
    service_id VARCHAR(50),
    date VARCHAR(8),
    exception_type INT,
    PRIMARY KEY (service_id, date)
);

-- 3. Create Operational Tables
CREATE TABLE gtfs_raw.shapes (
    shape_id VARCHAR(50),
    shape_pt_lat DOUBLE PRECISION,
    shape_pt_lon DOUBLE PRECISION,
    shape_pt_sequence INT,
    shape_dist_traveled DOUBLE PRECISION,
    PRIMARY KEY (shape_id, shape_pt_sequence)
);

CREATE TABLE gtfs_raw.trips (
    route_id VARCHAR(50),
    service_id VARCHAR(50),
    trip_id VARCHAR(100) PRIMARY KEY,
    trip_headsign VARCHAR(255),
    shape_id VARCHAR(50)
);

CREATE TABLE gtfs_raw.stop_times (
    trip_id VARCHAR(100),
    arrival_time VARCHAR(20),
    departure_time VARCHAR(20),
    stop_id VARCHAR(50),
    stop_sequence INT,
    PRIMARY KEY (trip_id, stop_sequence)
);
"""

# Recommended indexes for performance [cite: 107-112]
INDEX_QUERIES = """
CREATE INDEX IF NOT EXISTS idx_st_stop_time ON gtfs_raw.stop_times(stop_id, departure_time);
CREATE INDEX IF NOT EXISTS idx_st_trip_seq ON gtfs_raw.stop_times(trip_id, stop_sequence);
CREATE INDEX IF NOT EXISTS idx_trips_route_srv ON gtfs_raw.trips(route_id, service_id);
CREATE INDEX IF NOT EXISTS idx_cal_dates ON gtfs_raw.calendar_dates(date, service_id);
"""

# Views for analytical querying and LLM consumption
VIEWS_QUERIES = """
-- 1. View: Itinerario de paradas ordenado por línea
CREATE OR REPLACE VIEW gtfs_raw.v_paradas_por_linea AS
SELECT DISTINCT 
    r.route_short_name AS linea, 
    t.trip_headsign AS destino, 
    st.stop_sequence AS orden, 
    s.stop_name AS parada,
    s.stop_lat,
    s.stop_lon
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.trip_id = st.trip_id
JOIN gtfs_raw.stops s ON st.stop_id = s.stop_id
ORDER BY r.route_short_name, t.trip_headsign, st.stop_sequence;

-- 2. View: Primer y último servicio del día por línea y destino
CREATE OR REPLACE VIEW gtfs_raw.v_primer_ultimo_servicio AS
SELECT 
    r.route_short_name AS linea, 
    t.trip_headsign AS destino, 
    MIN(st.arrival_time) AS primer_servicio, 
    MAX(st.arrival_time) AS ultimo_servicio
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.trip_id = st.trip_id
GROUP BY r.route_short_name, t.trip_headsign
ORDER BY r.route_short_name;

-- 3. View: Horarios detallados (Adaptada para TITSA - Lee de calendar_dates)
CREATE OR REPLACE VIEW gtfs_raw.v_horarios_linea_parada AS
SELECT 
    r.route_short_name AS linea, 
    s.stop_name AS parada, 
    st.arrival_time AS hora_paso,
    cd.date AS fecha_operacion
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.trip_id = st.trip_id
JOIN gtfs_raw.stops s ON st.stop_id = s.stop_id
JOIN gtfs_raw.calendar_dates cd ON t.service_id = cd.service_id
WHERE cd.exception_type = 1;


-- 4. View: Líneas activas por fecha (Para saber qué opera hoy)
CREATE OR REPLACE VIEW gtfs_raw.v_lineas_activas_fecha AS
SELECT DISTINCT 
    r.route_short_name AS linea, 
    cd.date AS fecha
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.route_id = t.route_id
JOIN gtfs_raw.calendar_dates cd ON t.service_id = cd.service_id
WHERE cd.exception_type = 1;

-- 5. View: Conexiones Directas (Pares Origen-Destino sin transbordo)
-- Nota: Limitamos a la misma línea y viaje para evitar cruces masivos
CREATE OR REPLACE VIEW gtfs_raw.v_conexiones_directas AS
SELECT DISTINCT
    r.route_short_name AS linea,
    s1.stop_name AS origen,
    s2.stop_name AS destino
FROM gtfs_raw.stop_times st1
JOIN gtfs_raw.stop_times st2 ON st1.trip_id = st2.trip_id AND st1.stop_sequence < st2.stop_sequence
JOIN gtfs_raw.trips t ON st1.trip_id = t.trip_id
JOIN gtfs_raw.routes r ON t.route_id = r.route_id
JOIN gtfs_raw.stops s1 ON st1.stop_id = s1.stop_id
JOIN gtfs_raw.stops s2 ON st2.stop_id = s2.stop_id;

-- 6. View: Headways (Frecuencia de paso en minutos por línea y parada)
-- Usamos funciones ventana (LAG) para comparar la hora con el viaje anterior
CREATE OR REPLACE VIEW gtfs_raw.v_headways AS
WITH tiempos AS (
    SELECT 
        r.route_short_name AS linea,
        s.stop_name AS parada,
        st.arrival_time,
        -- Extraemos solo la hora para hacer una agrupación básica (ej. "A las 08:00 pasan 4 guaguas")
        SUBSTRING(st.arrival_time FROM 1 FOR 2) AS franja_horaria
    FROM gtfs_raw.routes r
    JOIN gtfs_raw.trips t ON r.route_id = t.route_id
    JOIN gtfs_raw.stop_times st ON t.trip_id = st.trip_id
    JOIN gtfs_raw.stops s ON st.stop_id = s.stop_id
)
SELECT 
    linea,
    parada,
    franja_horaria,
    COUNT(*) AS expediciones_por_hora,
    ROUND(60.0 / NULLIF(COUNT(*), 0)) AS frecuencia_estimada_minutos
FROM tiempos
GROUP BY linea, parada, franja_horaria
ORDER BY linea, parada, franja_horaria;
"""

def extract_latest_gtfs():
    """Finds the most recent GTFS zip and extracts it to the staging folder."""
    print("--- Extracting GTFS ZIP to Staging ---")

    # Check if raw directory exists
    if not os.path.exists(RAW_DIR):
        raise FileNotFoundError(f"Raw directory not found: {RAW_DIR}")

    # Get all date folders, sort descending to get the newest
    date_folders = sorted([f.path for f in os.scandir(RAW_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded GTFS data found in raw directory.")

    latest_folder = date_folders[0]
    zip_path = os.path.join(latest_folder, "gtfs_titsa.zip")

    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"ZIP file not found at {zip_path}")

    # Ensure staging directory exists
    os.makedirs(STAGING_DIR, exist_ok=True)

    print(f"Unzipping {zip_path} into {STAGING_DIR}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(STAGING_DIR)

    return STAGING_DIR


def validate_csv_headers(file_path, expected_columns):
    """Reads the first line of the CSV to validate mandatory columns exist."""
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        header = f.readline().strip().split(',')

    missing_cols = [col for col in expected_columns if col not in header]
    if missing_cols:
        raise ValueError(f"Validation failed for {os.path.basename(file_path)}: Missing columns {missing_cols}")
    return True 


def load_data_to_postgres(staging_path):
    """Creates schemas, tables, and bulk loads CSV files into PostgreSQL."""
    print("--- Loading CSVs into PostgreSQL ---")

    # List of files we want to load. Order matters slightly for referential integrity (if enforced).
    files_to_load = [
        "agency.txt", "routes.txt", "stops.txt",
        "calendar.txt", "calendar_dates.txt",
        "shapes.txt", "trips.txt", "stop_times.txt"
    ]

    # Defines minimum mandatory columns to validate before loading
    mandatory_columns = {
        "agency.txt": ["agency_id", "agency_name", "agency_url", "agency_timezone"],
        "routes.txt": ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
        "stops.txt": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
        "trips.txt": ["route_id", "service_id", "trip_id", "shape_id"],
        "stop_times.txt": ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]
    }

    conn = None
    try:
        # Connect to the PostgreSQL database
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("Creating schemas and empty tables (dropping existing ones)...")
        cur.execute(DDL_QUERIES)
        conn.commit()

        # Bulk load each file
        for file_name in files_to_load:
            file_path = os.path.join(staging_path, file_name)
            table_name = file_name.replace(".txt", "")

            if os.path.exists(file_path):
                # 1. Validar columnas si el archivo es obligatorio
                if file_name in mandatory_columns:
                    validate_csv_headers(file_path, mandatory_columns[file_name])
                    print(f"Validation passed for {file_name}. All mandatory columns are present.")

                # 2. Cargar datos
                print(f"Loading {file_name} into gtfs_raw.{table_name}...")
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    copy_sql = f"COPY gtfs_raw.{table_name} FROM STDIN WITH CSV HEADER DELIMITER ','"
                    cur.copy_expert(sql=copy_sql, file=f)
                conn.commit()
            else:
                print(f"Warning: {file_name} not found in staging. Skipping.")

        print("Creating performance indexes...")
        cur.execute(INDEX_QUERIES)
        conn.commit()

        print("Generating analytical views...")
        cur.execute(VIEWS_QUERIES)
        conn.commit()

        cur.close()
        print("Data loaded, indexed, and views generated successfully!")

    except psycopg2.Error as e:
        print(f"Database error occurred: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    try:
        extracted_path = extract_latest_gtfs()
        load_data_to_postgres(extracted_path)
    except Exception as e:
        print(f"ETL Process Failed: {e}")