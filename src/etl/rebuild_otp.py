import os
import shutil
import subprocess

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_GTFS_DIR = os.path.join(BASE_DIR, "data", "raw", "gtfs")
OTP_DIR = os.path.join(BASE_DIR, "data", "otp")

def rebuild_otp_graph():
    """Copies the most recent GTFS zip to the OTP folder and rebuilds the graph in Docker."""
    print("--- Phase 5: Rebuilding OpenTripPlanner Graph ---")

    # 1. Find the most recently downloaded GTFS
    if not os.path.exists(RAW_GTFS_DIR):
        raise FileNotFoundError(f"GTFS directory not found: {RAW_GTFS_DIR}")

    date_folders = sorted([f.path for f in os.scandir(RAW_GTFS_DIR) if f.is_dir()], reverse=True)
    if not date_folders:
        raise FileNotFoundError("No downloaded GTFS data found.")

    latest_folder = date_folders[0]
    source_gtfs = os.path.join(latest_folder, "gtfs_titsa.zip")

    if not os.path.exists(source_gtfs):
        raise FileNotFoundError(f"ZIP file not found at {source_gtfs}")

    # 2. Copy the ZIP to the OTP folder (overwriting the old one)
    target_gtfs = os.path.join(OTP_DIR, "gtfs_titsa.zip")
    print(f"Copying {source_gtfs} -> {OTP_DIR}...")
    os.makedirs(OTP_DIR, exist_ok=True)
    shutil.copy2(source_gtfs, target_gtfs)

    # 3. Docker commands via Subprocess
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