"""Simple launcher to run the complete ETL pipeline from the project root."""

from src.etl.download_gtfs import download_gtfs
from src.etl.download_od import download_od_matrices, get_recent_od_datasets
from src.etl.load_gtfs import main as load_gtfs_main
from src.etl.load_od import main as load_od_main
from src.etl.rebuild_otp import rebuild_otp_graph

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
    load_gtfs_main()

    print("\n--- PHASE 4: Loading OD data into PostgreSQL/PostGIS ---")
    load_od_main()

    print("\n--- PHASE 5: Rebuilding OTP Routing Engine ---")
    rebuild_otp_graph() # <-- Execute the new phase

    print("\n=======================================")
    print(" ETL PIPELINE COMPLETED SUCCESSFULLY")
    print("=======================================")


if __name__ == "__main__":
    run_pipeline()