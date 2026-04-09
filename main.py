"""Lanzador simple para ejecutar el ETL completo desde la raíz del proyecto."""

import psycopg2

from src.config import DB_PARAMS
from src.etl.download_gtfs import download_gtfs
from src.etl.download_od import download_od_matrices, get_recent_od_datasets
from src.etl.load_gtfs import extract_latest_gtfs, load_data_to_postgres
from src.etl.load_od import DDL_QUERIES, extract_latest_od, load_matrix_csvs, load_spatial_data


def run_pipeline():
    print("=======================================")
    print(" STARTING TITSA DATA ETL")
    print("=======================================\n")

    print("--- PHASE 1: Downloading GTFS ---")
    download_gtfs()

    print("\n--- PHASE 2: Downloading OD matrices ---")
    recent_datasets = get_recent_od_datasets(limit=2)
    if not recent_datasets:
        print("No OD datasets found.")
    else:
        for dataset in recent_datasets:
            download_od_matrices(dataset["id"], dataset["folder"])

    print("\n--- PHASE 3: Loading GTFS into PostgreSQL ---")
    gtfs_staging_path = extract_latest_gtfs()
    load_data_to_postgres(gtfs_staging_path)

    print("\n--- PHASE 4: Loading OD data into PostgreSQL/PostGIS ---")
    od_staging_path = extract_latest_od()

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("Setting up OD schemas and tables...")
        cur.execute(DDL_QUERIES)

        load_spatial_data(cur, od_staging_path)
        load_matrix_csvs(cur, od_staging_path)

        conn.commit()
        print("--- OD load completed successfully ---")
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    print("\n=======================================")
    print(" ETL PIPELINE COMPLETED")
    print("=======================================")


if __name__ == "__main__":
    run_pipeline()
