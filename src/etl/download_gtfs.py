import os
import requests
from datetime import datetime

from src.etl.data_wrangling import fix_expired_gtfs_zip

# CKAN API URL template
GTFS_API_URL = "https://datos.tenerife.es/ckan/api/action/package_show?id={package_id}"

# GTFS feeds to download on each run
GTFS_FEEDS = [
    {
        "feed_id": "titsa",
        "package_id": "36c2e26f-0d18-4b5a-b214-1636168e0765",
        "output_filename": "gtfs_titsa.zip",
    },
    {
        "feed_id": "metro",
        "package_id": "58b3868a-c492-4a01-a49b-5221db8ab3fb",
        "output_filename": "gtfs_metro.zip",
    },
]

# Define the base path where data will be stored (moving up two levels from src/etl)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")


def get_download_url(package_id):
    """Resolves the first valid resource URL from a CKAN package."""
    response = requests.get(GTFS_API_URL.format(package_id=package_id), timeout=30)
    response.raise_for_status()
    data = response.json()

    resources = data.get("result", {}).get("resources", [])
    if not resources:
        raise ValueError(f"No resources found for package {package_id}")

    for resource in resources:
        url = resource.get("url")
        if url and url.lower().endswith(".zip"):
            return url

    fallback_url = resources[0].get("url")
    if not fallback_url:
        raise ValueError(f"No downloadable URL found for package {package_id}")
    return fallback_url


def download_gtfs():
    print("Querying datos.tenerife.es CKAN API for GTFS feeds...")

    # 1. Create the versioned folder structure (YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")
    target_folder = os.path.join(RAW_DIR, "gtfs", today)
    os.makedirs(target_folder, exist_ok=True)

    downloaded_files = {}
    for feed in GTFS_FEEDS:
        feed_id = feed["feed_id"]
        output_filename = feed["output_filename"]

        print(f"Resolving download URL for feed '{feed_id}'...")
        download_url = get_download_url(feed["package_id"])
        print(f"Download URL found for '{feed_id}': {download_url}")

        file_path = os.path.join(target_folder, output_filename)

        # 2. Download and save each file
        print(f"Downloading '{feed_id}' ZIP to {file_path}...")
        with requests.get(download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        print(f"Validando fechas operativas de '{feed_id}'...")
        fix_expired_gtfs_zip(file_path)

        downloaded_files[feed_id] = file_path

    print("GTFS downloads completed successfully!")
    return downloaded_files


if __name__ == "__main__":
    download_gtfs()