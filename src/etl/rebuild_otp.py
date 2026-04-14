import os
import shutil
import subprocess
import requests
import glob

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_GTFS_DIR = os.path.join(BASE_DIR, "data", "raw", "gtfs")
OTP_DIR = os.path.join(BASE_DIR, "data", "otp")

# OSM Download parameters
OSM_URL = "https://download.geofabrik.de/africa/canary-islands-latest.osm.pbf"
TARGET_OSM_FILE = os.path.join(OTP_DIR, "canary-islands-latest.osm.pbf")
GTFS_ZIP_FILES = ["gtfs_titsa.zip", "gtfs_metro.zip"]


def download_osm_data():
    """Downloads the latest OSM PBF file from Geofabrik if it doesn't exist."""
    print("Checking OpenStreetMap (OSM) data...")
    os.makedirs(OTP_DIR, exist_ok=True)

    # We check if it exists to prevent being rate-limited/banned by Geofabrik during testing
    if os.path.exists(TARGET_OSM_FILE):
        print(f"-> OSM file already exists. Skipping download.")
        return

    print(f"-> Downloading OSM data from {OSM_URL} (This may take a moment)...")

    try:
        # stream=True allows us to download large files without consuming too much RAM
        with requests.get(OSM_URL, stream=True) as r:
            r.raise_for_status()
            with open(TARGET_OSM_FILE, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print("-> OSM data downloaded successfully.")
    except requests.exceptions.RequestException as e:
        print(f"Critical error downloading OSM data: {e}")
        raise


def rebuild_otp_graph():
    """Copies the most recent GTFS zip, ensures OSM exists, and rebuilds the graph in Docker."""
    print("--- Phase 5: Rebuilding OpenTripPlanner Graph ---")

    # 1. Download/Verify OSM Data
    download_osm_data()

    # 2. Find the most recently downloaded GTFS folder
    if not os.path.exists(RAW_GTFS_DIR):
        raise FileNotFoundError(f"GTFS directory not found: {RAW_GTFS_DIR}")

    date_folders = sorted([f.path for f in os.scandir(RAW_GTFS_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded GTFS data found.")

    latest_folder = date_folders[0]

    # 3. Replace GTFS ZIP files in OTP folder with latest available ones
    for existing_zip in glob.glob(os.path.join(OTP_DIR, "gtfs_*.zip")):
        os.remove(existing_zip)

    copied_count = 0
    for zip_name in GTFS_ZIP_FILES:
        source_gtfs = os.path.join(latest_folder, zip_name)
        if not os.path.exists(source_gtfs):
            print(f"Warning: ZIP file not found at {source_gtfs}. Skipping.")
            continue

        print(f"Copying {source_gtfs} -> {OTP_DIR}...")
        shutil.copy2(source_gtfs, os.path.join(OTP_DIR, zip_name))
        copied_count += 1

    if copied_count == 0:
        raise FileNotFoundError(f"No GTFS ZIP files were found in {latest_folder}")

    # 4. Docker commands via Subprocess
    try:
        # A) Stop the current OTP server (to free up RAM for the build process)
        print("Stopping current OTP server...")
        subprocess.run(["docker", "compose", "stop", "otp"], check=True, cwd=BASE_DIR)

        # B) Run a temporary container to build the new graph
        print("Building the new graph (This might take a minute)...")
        # Using docker compose run ensures it points to the correct volumes defined in yaml
        build_cmd = [
            "docker", "compose", "run", "--rm", "otp", "--build", "--save"
        ]
        subprocess.run(build_cmd, check=True, cwd=BASE_DIR)
        print("Graph built successfully (graph.obj updated).")

        # C) Restart the OTP server in the background with the new data
        print("Restarting the OTP server with the new graph...")
        subprocess.run(["docker", "compose", "up", "-d", "otp"], check=True, cwd=BASE_DIR)
        print("OTP API successfully updated and running!")

    except subprocess.CalledProcessError as e:
        print(f"Critical error executing Docker commands: {e}")
        raise