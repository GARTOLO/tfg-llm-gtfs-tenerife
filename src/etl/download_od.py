import os
import requests
from datetime import datetime

# CKAN API URLs
CKAN_SEARCH_URL = "https://datos.tenerife.es/ckan/api/3/action/package_search"
CKAN_PACKAGE_URL = "https://datos.tenerife.es/ckan/api/3/action/package_show?id="

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")


def get_recent_od_datasets(limit=2):
    """
    Searches the CKAN API for the most recent OD Matrix datasets.
    limit=2 means it will fetch the current month and the previous month.
    """
    print(f"Searching for the {limit} most recent OD Matrix datasets...")

    # We query datasets with 'Matriz Origen-Destino' in the title, sorted by newest first
    params = {
        "q": 'title:"Matriz Origen-Destino de transporte público"',
        "sort": "metadata_created desc",
        "rows": limit
    }

    response = requests.get(CKAN_SEARCH_URL, params=params)
    response.raise_for_status()
    data = response.json()

    results = data.get("result", {}).get("results", [])
    datasets = []

    for dataset in results:
        dataset_id = dataset.get("id")
        # Extract the creation year-month (YYYY-MM) to name our local folder
        created_date_str = dataset.get("metadata_created", "")[:10]

        if created_date_str:
            folder_month = created_date_str[:7]  # Keeps only YYYY-MM
        else:
            folder_month = "unknown_date"

        datasets.append({
            "id": dataset_id,
            "folder": folder_month,
            "title": dataset.get("title")
        })

    return datasets


def download_od_matrices(dataset_id, folder_month):
    """
    Downloads the required ZIP and GeoJSON files for a specific dataset ID.
    """
    print(f"\nProcessing dataset: {folder_month} (ID: {dataset_id})")

    url = f"{CKAN_PACKAGE_URL}{dataset_id}"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()

    resources = data.get("result", {}).get("resources", [])
    target_files = []

    # Filter the exact files we need
    for res in resources:
        name = res.get("name", "").lower()
        fmt = res.get("format", "").upper()
        download_url = res.get("url")

        if "días laborables" in name and fmt == "ZIP":
            target_files.append({"name": "laborables", "url": download_url, "ext": ".zip"})
        elif "días no laborables" in name and fmt == "ZIP":
            target_files.append({"name": "festivos", "url": download_url, "ext": ".zip"})
        elif "censal" in name and fmt == "GEOJSON":
            target_files.append({"name": "zonificacion_censal", "url": download_url, "ext": ".geojson"})
        elif "títulos" in name and fmt == "CSV":
            target_files.append({"name": "titulos_transporte", "url": download_url, "ext": ".csv"})

    if not target_files:
        print("No matching OD resources found in this dataset.")
        return

    # Create target folder
    target_folder = os.path.join(RAW_DIR, "od", folder_month)
    os.makedirs(target_folder, exist_ok=True)

    # Download files, skipping if they already exist locally
    for file_info in target_files:
        safe_name = file_info["name"].replace(" ", "_").replace("/", "-").lower() + file_info["ext"]
        file_path = os.path.join(target_folder, safe_name)

        if os.path.exists(file_path):
            print(f"-> File {safe_name} already exists. Skipping download.")
            continue

        print(f"-> Downloading {file_info['name']}...")

        with requests.get(file_info["url"], stream=True) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    print(f"OD Matrices for {folder_month} processed successfully!")


if __name__ == "__main__":
    # 1. First, find the IDs for the latest 2 months
    recent_datasets = get_recent_od_datasets(limit=2)

    if not recent_datasets:
        print("No OD datasets found on the server.")
    else:
        # 2. Then, download the files for each of those months
        for ds in recent_datasets:
            print(f"\nFound dataset: {ds['title']}")
            download_od_matrices(ds["id"], ds["folder"])