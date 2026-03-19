import os
import requests
from datetime import datetime

# API URLs
GTFS_API_URL = "https://datos.tenerife.es/ckan/api/action/package_show?id=36c2e26f-0d18-4b5a-b214-1636168e0765"

# Define the base path where data will be stored (moving up two levels from src/etl)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")


def download_gtfs():
    print("Querying the datos.tenerife.es API for GTFS...")

    # 1. Make the request to the API
    response = requests.get(GTFS_API_URL)
    response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
    data = response.json()

    # 2. Extract the download URL from the JSON
    try:
        # Navigate through the JSON: result -> resources -> first element -> url
        download_url = data["result"]["resources"][0]["url"]
        print(f"Download URL found: {download_url}")
    except (KeyError, IndexError) as e:
        print("Error reading the JSON from the API. The format might have changed.")
        return

    # 3. Create the versioned folder structure (YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")
    target_folder = os.path.join(RAW_DIR, "gtfs", today)
    os.makedirs(target_folder, exist_ok=True)

    file_path = os.path.join(target_folder, "gtfs_titsa.zip")

    # 4. Download and save the file
    print(f"Downloading ZIP file to {file_path}...")

    with requests.get(download_url, stream=True) as r:
        r.raise_for_status()
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    print("GTFS download completed successfully!")


if __name__ == "__main__":
    download_gtfs()