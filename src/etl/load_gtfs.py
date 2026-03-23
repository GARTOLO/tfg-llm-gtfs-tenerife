import os
import zipfile
import psycopg2

# Database connection parameters (Matching docker-compose.yml)
DB_PARAMS = {
    "dbname": "gtfs_titsa",
    "user": "postgres_user",
    "password": "postgres_password",
    "host": "localhost",
    "port": "5432"
}

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


def load_data_to_postgres(staging_path):
    """Creates schemas, tables, and bulk loads CSV files into PostgreSQL."""
    print("--- Loading CSVs into PostgreSQL ---")

    # List of files we want to load. Order matters slightly for referential integrity (if enforced).
    files_to_load = [
        "agency.txt", "routes.txt", "stops.txt",
        "calendar.txt", "calendar_dates.txt",
        "shapes.txt", "trips.txt", "stop_times.txt"
    ]

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
                print(f"Loading {file_name} into gtfs_raw.{table_name}...")
                # utf-8-sig removes the BOM (Byte Order Mark) if it exists at the start of the file
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    copy_sql = f"COPY gtfs_raw.{table_name} FROM STDIN WITH CSV HEADER DELIMITER ','"
                    cur.copy_expert(sql=copy_sql, file=f)
                conn.commit()
            else:
                print(f"Warning: {file_name} not found in staging. Skipping.")

        print("Creating performance indexes...")
        cur.execute(INDEX_QUERIES)
        conn.commit()

        cur.close()
        print("Data loaded and indexed successfully!")

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