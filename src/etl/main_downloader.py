import os
from download_gtfs import download_gtfs
from download_od import get_recent_od_datasets, download_od_matrices

def run_all_downloads():
    print("=======================================")
    print(" STARTING TITSA DATA EXTRACTION (ETL)")
    print("=======================================\n")

    # 1. Download GTFS Data
    print("--- PHASE 1: Downloading GTFS Static Data ---")
    try:
        download_gtfs()
    except Exception as e:
        print(f"Failed to download GTFS: {e}")

    print("\n--- PHASE 2: Downloading OD Matrices ---")
    # 2. Download OD Matrices Data
    try:
        recent_datasets = get_recent_od_datasets(limit=2)
        if not recent_datasets:
            print("No OD datasets found.")
        else:
            for ds in recent_datasets:
                download_od_matrices(ds["id"], ds["folder"])
    except Exception as e:
        print(f"Failed to download OD Matrices: {e}")

    print("\n=======================================")
    print(" ALL DOWNLOAD TASKS COMPLETED")
    print("=======================================")

if __name__ == "__main__":
    run_all_downloads()