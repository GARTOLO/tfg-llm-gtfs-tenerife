import os
import json
import zipfile
import psycopg2
import glob
import io
import csv
import shutil

from src.config import DB_PARAMS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "od")
STAGING_DIR = os.path.join(BASE_DIR, "data", "staging", "od")

CAPACIDAD_DEFAULT = 65


DDL_QUERIES = f"""
CREATE SCHEMA IF NOT EXISTS analytics;

DROP TABLE IF EXISTS analytics.dim_zonas_censales CASCADE;
CREATE TABLE analytics.dim_zonas_censales (
    zonificacion_censal_codigo  VARCHAR(50) PRIMARY KEY,
    municipio_codigo_ine        INT,
    municipio_nombre            VARCHAR(255),
    geometria                   GEOMETRY(Polygon, 4326)
);

-- Do not DROP this table to preserve manual capacity edits
CREATE TABLE IF NOT EXISTS analytics.dim_capacidad_linea (
    linea_id            VARCHAR(50) PRIMARY KEY,
    capacidad_pasajeros INT         NOT NULL DEFAULT {CAPACIDAD_DEFAULT},
    tipo_vehiculo       VARCHAR(100),
    gtfs_route_id       VARCHAR(50),
    notas               TEXT,
    actualizado_en      TIMESTAMP DEFAULT NOW()
);

DROP TABLE IF EXISTS analytics.fact_od_mensual CASCADE;
CREATE TABLE analytics.fact_od_mensual (
    id                  BIGSERIAL PRIMARY KEY,
    linea_id            VARCHAR(50),
    titulo_id           INT,
    viaje_hora          INT,
    parada_entrada_id   VARCHAR(50),
    parada_salida_id    VARCHAR(50),
    pasajeros_cantidad  INT,
    fechas_calculadas   INT,
    linea_siguiente_id  VARCHAR(50),
    linea_anterior_id   VARCHAR(50),
    matriz_id           VARCHAR(100),
    tipo_dia            VARCHAR(20)
);

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
    fechas_calculadas INT, linea_siguiente_id VARCHAR(50), linea_anterior_id VARCHAR(50),
    matriz_id VARCHAR(100)
);
"""


DDL_MARTS = f"""
-- =========================================================================
-- SUPPORT: dim_expediciones_hora
-- Average daily trips by line, hour, and day type.
--
-- Why AVG instead of COUNT/days:
--   TITSA uses unique trip_id values per trip (not reused across weeks).
--   Each trip appears N times in calendar_dates (once per active day).
--   If we use COUNT(DISTINCT trip_id), we get unique trips (~14),
--   and dividing by 130 working days gives 0.1 -> ROUND = 0.
--   The correct solution is:
--     1. Count distinct trips PER DAY (trips_por_dia)
--     2. Average that count across all days of that type (AVG)
--   So: AVG(14 trips/day over 130 days) = 14 ✓
-- =========================================================================
DROP TABLE IF EXISTS analytics.dim_expediciones_hora CASCADE;
CREATE TABLE analytics.dim_expediciones_hora AS
WITH trips_por_dia AS (
    -- Day-level: how many distinct trips each line operates
    -- in each hour, for each specific date in the GTFS calendar
    SELECT
        r.route_short_name                                              AS linea_id,
        cd.date                                                         AS fecha,
        MOD(EXTRACT(HOUR FROM st.departure_time::interval)::int, 24)   AS viaje_hora,
        CASE EXTRACT(DOW FROM cd.date::date)::int
            WHEN 0 THEN 'Festivo'
            WHEN 6 THEN 'Sabado'
            ELSE 'Laborable'
        END                                                             AS tipo_dia,
        COUNT(DISTINCT t.trip_id)                                       AS trips_ese_dia
    FROM gtfs_raw.trips t
    JOIN gtfs_raw.routes r
        ON r.route_id = t.route_id
    JOIN gtfs_raw.stop_times st
        ON st.trip_id = t.trip_id
        AND st.stop_sequence = 1
    JOIN gtfs_raw.calendar_dates cd
        ON cd.service_id = t.service_id
        AND cd.exception_type = 1
    GROUP BY r.route_short_name, cd.date, viaje_hora, tipo_dia
)
-- Average across all days of the same type
-- AVG(trips_ese_dia) = real daily average number of trips
SELECT
    linea_id,
    viaje_hora,
    tipo_dia,
    ROUND(AVG(trips_ese_dia)) AS num_expediciones
FROM trips_por_dia
GROUP BY linea_id, viaje_hora, tipo_dia;

CREATE INDEX idx_exp_hora_linea ON analytics.dim_expediciones_hora(linea_id, viaje_hora, tipo_dia);


-- =========================================================================
-- MART 1: fact_ocupacion_estimada_linea
-- Granularity: line + day_type
-- =========================================================================
DROP TABLE IF EXISTS analytics.fact_ocupacion_estimada_linea CASCADE;
CREATE TABLE analytics.fact_ocupacion_estimada_linea AS
SELECT
    od.linea_id,
    od.tipo_dia,
    ROUND(SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0)))
        AS pasajeros_dia_promedio,
    SUM(od.pasajeros_cantidad)
        AS pasajeros_total_periodo,
    COUNT(1)
        AS rutas_od_registradas,
    COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT})
        AS capacidad_vehiculo_ref,
    cap.gtfs_route_id
FROM analytics.fact_od_mensual od
LEFT JOIN analytics.dim_capacidad_linea cap ON cap.linea_id = od.linea_id
GROUP BY od.linea_id, od.tipo_dia, cap.capacidad_pasajeros, cap.gtfs_route_id;

CREATE INDEX idx_ocup_linea_linea ON analytics.fact_ocupacion_estimada_linea(linea_id);


-- =========================================================================
-- MART 2: fact_ocupacion_estimada_viaje
-- Granularity: line + hour + day_type
--
-- Occupancy formula:
--   pct = average_daily_passengers_per_time_slot / (num_trips * bus_capacity) * 100
-- =========================================================================
DROP TABLE IF EXISTS analytics.fact_ocupacion_estimada_viaje CASCADE;
CREATE TABLE analytics.fact_ocupacion_estimada_viaje AS
SELECT
    od.linea_id,
    od.viaje_hora,
    od.tipo_dia,

    ROUND(SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0)))
        AS pasajeros_franja_horaria,

    SUM(od.pasajeros_cantidad)
        AS pasajeros_franja_total_periodo,

    COALESCE(exp.num_expediciones, 1)
        AS num_expediciones,

    COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT})
        AS capacidad_vehiculo_ref,

    COALESCE(exp.num_expediciones, 1) * COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT})
        AS capacidad_franja_total,

    ROUND(
        SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0))
        / NULLIF(
            COALESCE(exp.num_expediciones, 1) * COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT}),
            0
        ) * 100,
        1
    ) AS pct_ocupacion_estimado,

    CASE
        WHEN ROUND(
            SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0))
            / NULLIF(
                COALESCE(exp.num_expediciones, 1) * COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT}),
                0
            ) * 100
        ) >= 80 THEN 'muy_alto'
        WHEN ROUND(
            SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0))
            / NULLIF(
                COALESCE(exp.num_expediciones, 1) * COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT}),
                0
            ) * 100
        ) >= 60 THEN 'alto'
        WHEN ROUND(
            SUM(od.pasajeros_cantidad::numeric / NULLIF(od.fechas_calculadas, 0))
            / NULLIF(
                COALESCE(exp.num_expediciones, 1) * COALESCE(cap.capacidad_pasajeros, {CAPACIDAD_DEFAULT}),
                0
            ) * 100
        ) >= 35 THEN 'moderado'
        ELSE 'bajo'
    END AS nivel_ocupacion,

    CASE WHEN exp.num_expediciones IS NULL THEN TRUE ELSE FALSE END
        AS expediciones_estimadas,

    cap.gtfs_route_id

FROM analytics.fact_od_mensual od
LEFT JOIN analytics.dim_capacidad_linea cap
    ON cap.linea_id = od.linea_id
LEFT JOIN analytics.dim_expediciones_hora exp
    ON  exp.linea_id   = od.linea_id
    AND exp.viaje_hora  = od.viaje_hora
    AND exp.tipo_dia    = od.tipo_dia
GROUP BY
    od.linea_id, od.viaje_hora, od.tipo_dia,
    cap.capacidad_pasajeros, cap.gtfs_route_id,
    exp.num_expediciones;

CREATE INDEX idx_ocup_viaje_linea  ON analytics.fact_ocupacion_estimada_viaje(linea_id);
CREATE INDEX idx_ocup_viaje_hora   ON analytics.fact_ocupacion_estimada_viaje(linea_id, viaje_hora);
CREATE INDEX idx_ocup_viaje_gtfs   ON analytics.fact_ocupacion_estimada_viaje(gtfs_route_id);
CREATE INDEX idx_ocup_viaje_nivel  ON analytics.fact_ocupacion_estimada_viaje(nivel_ocupacion);


-- =========================================================================
-- MCP VIEW: v_ocupacion_mcp
-- =========================================================================
DROP VIEW IF EXISTS analytics.v_ocupacion_mcp;
CREATE VIEW analytics.v_ocupacion_mcp AS
SELECT
    v.linea_id,
    r.route_short_name      AS gtfs_route_short_name,
    r.route_long_name       AS gtfs_route_long_name,
    v.viaje_hora,
    v.tipo_dia,
    v.pasajeros_franja_horaria,
    v.num_expediciones,
    v.capacidad_vehiculo_ref,
    v.capacidad_franja_total,
    v.pct_ocupacion_estimado,
    v.nivel_ocupacion,
    v.expediciones_estimadas,
    format(
        'Línea %s (%s) a las %sh en día %s: ~%s pasajeros repartidos en %s expediciones '
        '(capacidad total %s plazas), ocupación estimada %s%% (%s)%s.',
        COALESCE(r.route_short_name, v.linea_id),
        r.route_long_name,
        v.viaje_hora,
        v.tipo_dia,
        v.pasajeros_franja_horaria,
        v.num_expediciones,
        v.capacidad_franja_total,
        v.pct_ocupacion_estimado,
        v.nivel_ocupacion,
        CASE WHEN v.expediciones_estimadas
            THEN ' [expediciones estimadas, dato GTFS no disponible para esta hora]'
            ELSE ''
        END
    ) AS resumen_llm
FROM analytics.fact_ocupacion_estimada_viaje v
LEFT JOIN analytics.dim_capacidad_linea cap ON cap.linea_id = v.linea_id
LEFT JOIN gtfs_raw.routes r ON r.route_id = cap.gtfs_route_id;
"""


def extract_latest_od():
    print("--- Extracting OD Files to Staging ---")
    if not os.path.exists(RAW_DIR):
        raise FileNotFoundError(f"Raw directory not found: {RAW_DIR}")

    date_folders = sorted([f.path for f in os.scandir(RAW_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded OD data found in raw directory.")

    latest_folder = date_folders[0]
    os.makedirs(STAGING_DIR, exist_ok=True)

    for zip_path in glob.glob(os.path.join(latest_folder, "*.zip")):
        print(f"  Unzipping {os.path.basename(zip_path)}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(STAGING_DIR)

    for geo_path in glob.glob(os.path.join(latest_folder, "*.geojson")):
        shutil.copy(geo_path, STAGING_DIR)

    return STAGING_DIR


def load_spatial_data(cur, staging_path):
    print("--- Loading Spatial Data (GeoJSON) ---")
    geojson_files = glob.glob(os.path.join(staging_path, "*censal*.geojson"))
    if not geojson_files:
        print("  Warning: No census GeoJSON found. Skipping.")
        return

    with open(geojson_files[0], 'r', encoding='utf-8') as f:
        data = json.load(f)

    inserted = 0
    for feature in data.get('features', []):
        props = feature.get('properties', {})
        cod_censal = str(props.get('zonificacion_censal_codigo', ''))
        if not cod_censal:
            continue
        cur.execute("""
            INSERT INTO analytics.dim_zonas_censales
                (zonificacion_censal_codigo, municipio_codigo_ine, municipio_nombre, geometria)
            VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
            ON CONFLICT (zonificacion_censal_codigo) DO NOTHING;
        """, (
            cod_censal,
            props.get('municipio_codigo_ine'),
            props.get('municipio_nombre', 'Desconocido'),
            json.dumps(feature.get('geometry'))
        ))
        inserted += 1
    print(f"  Loaded {inserted} census zones.")


def seed_capacidad_desde_gtfs(cur):
    print("--- Seeding dim_capacidad_linea desde GTFS ---")
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.schemata WHERE schema_name = 'gtfs_raw'
        );
    """)
    if not cur.fetchone()[0]:
        print("  Schema 'gtfs_raw' no encontrado, saltando seed.")
        return

    cur.execute(f"""
        INSERT INTO analytics.dim_capacidad_linea
            (linea_id, capacidad_pasajeros, gtfs_route_id, notas)
        SELECT
            r.route_short_name,
            {CAPACIDAD_DEFAULT},
            r.route_id,
            'Seed automático desde GTFS - capacidad por defecto'
        FROM gtfs_raw.routes r
        ON CONFLICT (linea_id) DO UPDATE
            SET gtfs_route_id  = EXCLUDED.gtfs_route_id,
                actualizado_en = NOW()
        WHERE analytics.dim_capacidad_linea.gtfs_route_id IS NULL;
    """)
    print(f"  {cur.rowcount} líneas procesadas en dim_capacidad_linea.")


def load_matrix_csvs(cur, staging_path):
    print("--- Loading OD Matrix CSVs ---")
    csv_files = glob.glob(os.path.join(staging_path, "*.csv"))
    laborables_file = festivos_file = None

    for f in csv_files:
        name = os.path.basename(f).lower()
        if "no laborable" in name or "no_laborable" in name or "festivo" in name:
            festivos_file = f
        elif "laborable" in name:
            laborables_file = f

    columnas_lab = [
        "linea_id", "titulo_id", "viaje_hora", "parada_entrada_id", "parada_salida_id",
        "pasajeros_cantidad", "fechas_calculadas", "linea_siguiente_id", "linea_anterior_id",
        "matriz_id"
    ]
    columnas_fest = [
        "linea_id", "titulo_id", "viaje_hora", "parada_entrada_id", "parada_salida_id",
        "pasajeros_cantidad", "tipo_dia", "fechas_calculadas", "linea_siguiente_id",
        "linea_anterior_id", "matriz_id"
    ]

    def process_and_copy(file_path, temp_table, valid_cols):
        print(f"  Procesando {os.path.basename(file_path)}...")
        buffer = io.StringIO()
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            writer = csv.DictWriter(buffer, fieldnames=valid_cols, extrasaction='ignore')
            writer.writeheader()
            for row in reader:
                writer.writerow({k: (v if v != '' else None) for k, v in row.items() if k in valid_cols})
        buffer.seek(0)
        cur.copy_expert(
            f"COPY {temp_table} ({', '.join(valid_cols)}) FROM STDIN WITH CSV HEADER DELIMITER ','",
            buffer
        )

    if laborables_file:
        process_and_copy(laborables_file, "stg_laborables", columnas_lab)
        cur.execute("""
            INSERT INTO analytics.fact_od_mensual
                (linea_id, titulo_id, viaje_hora, parada_entrada_id, parada_salida_id,
                 pasajeros_cantidad, fechas_calculadas, linea_siguiente_id, linea_anterior_id,
                 matriz_id, tipo_dia)
            SELECT *, 'Laborable' FROM stg_laborables;
        """)
        print(f"  Laborables: {cur.rowcount} filas.")

    if festivos_file:
        process_and_copy(festivos_file, "stg_festivos", columnas_fest)
        cur.execute("""
            INSERT INTO analytics.fact_od_mensual
                (linea_id, titulo_id, viaje_hora, parada_entrada_id, parada_salida_id,
                 pasajeros_cantidad, fechas_calculadas, linea_siguiente_id, linea_anterior_id,
                 matriz_id, tipo_dia)
            SELECT
                linea_id, titulo_id, viaje_hora, parada_entrada_id, parada_salida_id,
                pasajeros_cantidad, fechas_calculadas, linea_siguiente_id, linea_anterior_id,
                matriz_id, tipo_dia
            FROM stg_festivos;
        """)
        print(f"  No-laborables: {cur.rowcount} filas.")


def build_analytics_marts(cur):
    print("--- Calculando Tablas Resumen (Data Marts) ---")
    cur.execute(DDL_MARTS)
    print("  Marts y vista MCP calculados con éxito.")


def main():
    conn = None
    try:
        staging_path = extract_latest_od()
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("Setting up schemas and tables...")
        cur.execute(DDL_QUERIES)

        load_spatial_data(cur, staging_path)
        seed_capacidad_desde_gtfs(cur)
        load_matrix_csvs(cur, staging_path)
        build_analytics_marts(cur)

        conn.commit()
        print("--- ETL for OD Matrix Completed Successfully! ---")

    except Exception as e:
        print(f"ETL Process Failed: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            cur.close()
            conn.close()


if __name__ == "__main__":
    main()