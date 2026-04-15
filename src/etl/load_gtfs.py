import os
import shutil
import zipfile
import csv
import io
import psycopg2

from src.config import DB_PARAMS

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "gtfs")
STAGING_DIR = os.path.join(BASE_DIR, "data", "staging", "gtfs")

# Feed configuration
GTFS_ZIP_FILES = {
    "titsa": "gtfs_titsa.zip",
    "metro": "gtfs_metro.zip",
}

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
    feed_id VARCHAR(20) NOT NULL,
    agency_id VARCHAR(50),
    agency_name VARCHAR(255),
    agency_url VARCHAR(255),
    agency_timezone VARCHAR(50),
    agency_lang VARCHAR(10),
    agency_phone VARCHAR(50)
);

CREATE TABLE gtfs_raw.routes (
    feed_id VARCHAR(20) NOT NULL,
    route_id VARCHAR(50) NOT NULL,
    agency_id VARCHAR(50),
    route_short_name VARCHAR(50),
    route_long_name VARCHAR(255),
    route_type INT,
    route_url VARCHAR(255),
    route_color VARCHAR(10),
    route_text_color VARCHAR(10),
    PRIMARY KEY (feed_id, route_id)
);

CREATE TABLE gtfs_raw.stops (
    feed_id VARCHAR(20) NOT NULL,
    stop_id VARCHAR(50) NOT NULL,
    stop_name VARCHAR(255),
    stop_lat DOUBLE PRECISION,
    stop_lon DOUBLE PRECISION,
    stop_url VARCHAR(255),
    PRIMARY KEY (feed_id, stop_id)
);

CREATE TABLE gtfs_raw.calendar (
    feed_id VARCHAR(20) NOT NULL,
    service_id VARCHAR(50) NOT NULL,
    monday INT,
    tuesday INT,
    wednesday INT,
    thursday INT,
    friday INT,
    saturday INT,
    sunday INT,
    start_date VARCHAR(8),
    end_date VARCHAR(8),
    PRIMARY KEY (feed_id, service_id)
);

CREATE TABLE gtfs_raw.calendar_dates (
    feed_id VARCHAR(20) NOT NULL,
    service_id VARCHAR(50) NOT NULL,
    date VARCHAR(8) NOT NULL,
    exception_type INT,
    PRIMARY KEY (feed_id, service_id, date)
);

-- 3. Create Operational Tables
CREATE TABLE gtfs_raw.shapes (
    feed_id VARCHAR(20) NOT NULL,
    shape_id VARCHAR(50) NOT NULL,
    shape_pt_lat DOUBLE PRECISION,
    shape_pt_lon DOUBLE PRECISION,
    shape_pt_sequence INT NOT NULL,
    shape_dist_traveled DOUBLE PRECISION,
    PRIMARY KEY (feed_id, shape_id, shape_pt_sequence)
);

CREATE TABLE gtfs_raw.trips (
    feed_id VARCHAR(20) NOT NULL,
    route_id VARCHAR(50),
    service_id VARCHAR(50),
    trip_id VARCHAR(100) NOT NULL,
    trip_headsign VARCHAR(255),
    shape_id VARCHAR(50),
    PRIMARY KEY (feed_id, trip_id)
);

CREATE TABLE gtfs_raw.stop_times (
    feed_id VARCHAR(20) NOT NULL,
    trip_id VARCHAR(100) NOT NULL,
    arrival_time VARCHAR(20),
    departure_time VARCHAR(20),
    stop_id VARCHAR(50),
    stop_sequence INT NOT NULL,
    PRIMARY KEY (feed_id, trip_id, stop_sequence)
);
"""

# Recommended indexes for performance
INDEX_QUERIES = """
CREATE INDEX IF NOT EXISTS idx_st_stop_time ON gtfs_raw.stop_times(feed_id, stop_id, departure_time);
CREATE INDEX IF NOT EXISTS idx_st_trip_seq ON gtfs_raw.stop_times(feed_id, trip_id, stop_sequence);
CREATE INDEX IF NOT EXISTS idx_trips_route_srv ON gtfs_raw.trips(feed_id, route_id, service_id);
CREATE INDEX IF NOT EXISTS idx_cal_dates ON gtfs_raw.calendar_dates(feed_id, date, service_id);
"""

# Views for analytical querying and LLM consumption
VIEWS_QUERIES = """
-- 1. View: Itinerario de paradas ordenado por linea y operador
CREATE OR REPLACE VIEW gtfs_raw.v_paradas_por_linea AS
SELECT DISTINCT
    r.feed_id,
    r.route_short_name AS linea,
    t.trip_headsign AS destino,
    st.stop_sequence AS orden,
    s.stop_name AS parada,
    s.stop_lat,
    s.stop_lon
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.feed_id = t.feed_id AND r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.feed_id = st.feed_id AND t.trip_id = st.trip_id
JOIN gtfs_raw.stops s ON st.feed_id = s.feed_id AND st.stop_id = s.stop_id
ORDER BY r.feed_id, r.route_short_name, t.trip_headsign, st.stop_sequence;

-- 2. View: Primer y ultimo servicio del dia por linea y destino
CREATE OR REPLACE VIEW gtfs_raw.v_primer_ultimo_servicio AS
SELECT
    r.feed_id,
    r.route_short_name AS linea,
    t.trip_headsign AS destino,
    MIN(st.arrival_time) AS primer_servicio,
    MAX(st.arrival_time) AS ultimo_servicio
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.feed_id = t.feed_id AND r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.feed_id = st.feed_id AND t.trip_id = st.trip_id
GROUP BY r.feed_id, r.route_short_name, t.trip_headsign
ORDER BY r.feed_id, r.route_short_name;

-- 3. View: Horarios detallados (usa calendar_dates)
CREATE OR REPLACE VIEW gtfs_raw.v_horarios_linea_parada AS
SELECT
    r.feed_id,
    r.route_short_name AS linea,
    s.stop_name AS parada,
    st.arrival_time AS hora_paso,
    cd.date AS fecha_operacion
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.feed_id = t.feed_id AND r.route_id = t.route_id
JOIN gtfs_raw.stop_times st ON t.feed_id = st.feed_id AND t.trip_id = st.trip_id
JOIN gtfs_raw.stops s ON st.feed_id = s.feed_id AND st.stop_id = s.stop_id
JOIN gtfs_raw.calendar_dates cd ON t.feed_id = cd.feed_id AND t.service_id = cd.service_id
WHERE cd.exception_type = 1;

-- 4. View: Lineas activas por fecha
CREATE OR REPLACE VIEW gtfs_raw.v_lineas_activas_fecha AS
SELECT DISTINCT
    r.feed_id,
    r.route_short_name AS linea,
    cd.date AS fecha
FROM gtfs_raw.routes r
JOIN gtfs_raw.trips t ON r.feed_id = t.feed_id AND r.route_id = t.route_id
JOIN gtfs_raw.calendar_dates cd ON t.feed_id = cd.feed_id AND t.service_id = cd.service_id
WHERE cd.exception_type = 1;

-- 5. View: Conexiones directas
CREATE OR REPLACE VIEW gtfs_raw.v_conexiones_directas AS
SELECT DISTINCT
    r.feed_id,
    r.route_short_name AS linea,
    s1.stop_name AS origen,
    s2.stop_name AS destino
FROM gtfs_raw.stop_times st1
JOIN gtfs_raw.stop_times st2
    ON st1.feed_id = st2.feed_id
   AND st1.trip_id = st2.trip_id
   AND st1.stop_sequence < st2.stop_sequence
JOIN gtfs_raw.trips t ON st1.feed_id = t.feed_id AND st1.trip_id = t.trip_id
JOIN gtfs_raw.routes r ON t.feed_id = r.feed_id AND t.route_id = r.route_id
JOIN gtfs_raw.stops s1 ON st1.feed_id = s1.feed_id AND st1.stop_id = s1.stop_id
JOIN gtfs_raw.stops s2 ON st2.feed_id = s2.feed_id AND st2.stop_id = s2.stop_id;

-- 6. View: Headways por linea y parada
CREATE OR REPLACE VIEW gtfs_raw.v_headways AS
WITH tiempos AS (
    SELECT
        r.feed_id,
        r.route_short_name AS linea,
        s.stop_name AS parada,
        st.arrival_time,
        SUBSTRING(st.arrival_time FROM 1 FOR 2) AS franja_horaria
    FROM gtfs_raw.routes r
    JOIN gtfs_raw.trips t ON r.feed_id = t.feed_id AND r.route_id = t.route_id
    JOIN gtfs_raw.stop_times st ON t.feed_id = st.feed_id AND t.trip_id = st.trip_id
    JOIN gtfs_raw.stops s ON st.feed_id = s.feed_id AND st.stop_id = s.stop_id
)
SELECT
    feed_id,
    linea,
    parada,
    franja_horaria,
    COUNT(*) AS expediciones_por_hora,
    ROUND(60.0 / NULLIF(COUNT(*), 0)) AS frecuencia_estimada_minutos
FROM tiempos
GROUP BY feed_id, linea, parada, franja_horaria
ORDER BY feed_id, linea, parada, franja_horaria;
"""


def _clean_directory(path):
    """Removes directory contents while keeping the directory itself."""
    os.makedirs(path, exist_ok=True)
    for entry in os.scandir(path):
        if entry.is_dir():
            shutil.rmtree(entry.path)
        else:
            os.remove(entry.path)


def extract_latest_gtfs():
    """Finds the most recent GTFS folder and extracts all known feeds to staging."""
    print("--- Extracting GTFS ZIP files to Staging ---")

    if not os.path.exists(RAW_DIR):
        raise FileNotFoundError(f"Raw directory not found: {RAW_DIR}")

    date_folders = sorted([f.path for f in os.scandir(RAW_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded GTFS data found in raw directory.")

    latest_folder = date_folders[0]
    _clean_directory(STAGING_DIR)

    extracted_paths = {}
    for feed_id, zip_name in GTFS_ZIP_FILES.items():
        zip_path = os.path.join(latest_folder, zip_name)
        if not os.path.exists(zip_path):
            print(f"Warning: ZIP file not found for '{feed_id}' at {zip_path}. Skipping.")
            continue

        feed_staging_dir = os.path.join(STAGING_DIR, feed_id)
        _clean_directory(feed_staging_dir)

        print(f"Unzipping {zip_path} into {feed_staging_dir}...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(feed_staging_dir)

        extracted_paths[feed_id] = feed_staging_dir

    if not extracted_paths:
        raise FileNotFoundError(f"No GTFS ZIP files found in latest folder: {latest_folder}")

    return extracted_paths


def validate_csv_headers(file_path, expected_columns):
    """Reads the first line of the CSV to validate mandatory columns exist."""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        header = f.readline().strip().split(",")

    missing_cols = [col for col in expected_columns if col not in header]
    if missing_cols:
        raise ValueError(f"Validation failed for {os.path.basename(file_path)}: Missing columns {missing_cols}")
    return True


def _load_feed_table(cur, file_path, table_name, feed_id):
    """Loads one GTFS text file into its table using COPY + feed tagging robustly, filtering columns in memory."""
    temp_table = f"stg_{table_name}_{feed_id}"

    cur.execute(f"DROP TABLE IF EXISTS {temp_table};")
    cur.execute(f"CREATE TEMP TABLE {temp_table} (LIKE gtfs_raw.{table_name} INCLUDING DEFAULTS);")
    cur.execute(f"ALTER TABLE {temp_table} DROP COLUMN feed_id;")

    columns_dict = {
        "agency": ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang", "agency_phone"],
        "routes": ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "route_url",
                   "route_color", "route_text_color"],
        "stops": ["stop_id", "stop_name", "stop_lat", "stop_lon", "stop_url"],
        "calendar": ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                     "start_date", "end_date"],
        "calendar_dates": ["service_id", "date", "exception_type"],
        "shapes": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"],
        "trips": ["route_id", "service_id", "trip_id", "trip_headsign", "shape_id"],
        "stop_times": ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
    }

    valid_table_columns = columns_dict[table_name]

    # 1. Usar un búfer de memoria para limpiar el CSV antes de dárselo a PostgreSQL
    buffer = io.StringIO()

    with open(file_path, "r", encoding="utf-8-sig") as f:
        # csv.DictReader es vital porque entiende si hay comas DENTRO del texto (ej. nombres de paradas)
        reader = csv.DictReader(f)

        # Intersección: Qué columnas de este CSV nos interesan realmente
        copy_columns = [col for col in reader.fieldnames if col in valid_table_columns]

        if not copy_columns:
            print(f"Warning: No valid columns found for {table_name} in {feed_id}. Skipping.")
            return

        # Escribimos en el búfer solo las columnas válidas, ignorando el resto (extrasaction='ignore')
        writer = csv.DictWriter(buffer, fieldnames=copy_columns, extrasaction='ignore')
        writer.writeheader()
        for row in reader:
            writer.writerow(row)

    # 2. Rebobinar el búfer al principio para que Postgres pueda leerlo
    buffer.seek(0)
    col_string = ", ".join(copy_columns)

    # 3. Inyectar datos desde el búfer de memoria
    copy_sql = f"COPY {temp_table} ({col_string}) FROM STDIN WITH CSV HEADER DELIMITER ','"
    cur.copy_expert(sql=copy_sql, file=buffer)

    # 4. Insertar en la tabla final añadiendo el feed_id
    cur.execute(
        f"""
        INSERT INTO gtfs_raw.{table_name} (feed_id, {col_string})
        SELECT %s, {col_string}
        FROM {temp_table}
        ON CONFLICT DO NOTHING;
        """,
        (feed_id,)
    )


def load_data_to_postgres(staging_paths):
    """Creates schemas/tables and bulk-loads one or many GTFS feeds into PostgreSQL."""
    print("--- Loading GTFS CSVs into PostgreSQL ---")

    if isinstance(staging_paths, str):
        staging_paths = {"titsa": staging_paths}

    files_to_load = [
        "agency.txt",
        "routes.txt",
        "stops.txt",
        "calendar.txt",
        "calendar_dates.txt",
        "shapes.txt",
        "trips.txt",
        "stop_times.txt",
    ]

    mandatory_columns = {
        "agency.txt": ["agency_name", "agency_url", "agency_timezone"],
        "routes.txt": ["route_id", "route_short_name", "route_long_name", "route_type"],
        "stops.txt": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
        "trips.txt": ["route_id", "service_id", "trip_id", "shape_id"],
        "stop_times.txt": ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
        "calendar_dates.txt": ["service_id", "date", "exception_type"],
        "calendar.txt": [
            "service_id",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "start_date",
            "end_date",
        ],
    }

    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("Creating schemas and empty tables (dropping existing ones)...")
        cur.execute(DDL_QUERIES)
        conn.commit()

        for feed_id, feed_staging_path in staging_paths.items():
            print(f"--- Loading feed '{feed_id}' from {feed_staging_path} ---")
            for file_name in files_to_load:
                file_path = os.path.join(feed_staging_path, file_name)
                table_name = file_name.replace(".txt", "")

                if not os.path.exists(file_path):
                    print(f"Warning: {file_name} not found for '{feed_id}'. Skipping.")
                    continue

                if file_name in mandatory_columns:
                    validate_csv_headers(file_path, mandatory_columns[file_name])
                    print(f"Validation passed for {file_name} ({feed_id}).")

                print(f"Loading {file_name} into gtfs_raw.{table_name} ({feed_id})...")
                _load_feed_table(cur, file_path, table_name, feed_id)
                conn.commit()

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
        extracted_paths = extract_latest_gtfs()
        load_data_to_postgres(extracted_paths)
    except Exception as e:
        print(f"ETL Process Failed: {e}")

