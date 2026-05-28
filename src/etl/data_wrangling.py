import os
import shutil
import zipfile
import csv
from datetime import datetime


def fix_expired_gtfs_zip(zip_path):
    """
    Read a zipped GTFS feed, check whether its dates have expired compared to today and, if so,
    shift the years forward to make it active again. This is a common issue in Metrotenerife GTFS.
    """
    if not os.path.exists(zip_path):
        return

    # 1. Extract the ZIP file to a temporary folder
    temp_dir = zip_path + "_temp_extract"
    os.makedirs(temp_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    calendar_path = os.path.join(temp_dir, "calendar.txt")
    if not os.path.exists(calendar_path):
        shutil.rmtree(temp_dir)
        return  # If no calendar.txt is found, we cannot determine expiration, so we skip.

    # 2. Find the maximum expiration date in calendar.txt (end_date field).
    max_year = 0
    with open(calendar_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if 'end_date' in row and row['end_date'].isdigit():
                year = int(row['end_date'][:4])
                if year > max_year:
                    max_year = year

    current_year = datetime.now().year

    # 3. If the GTFS feed has expired, calculate how many years to add.
    if 0 < max_year < current_year:
        years_to_add = (current_year - max_year) + 1
        print(f"🔧 Data Wrangling: Patching dates in {os.path.basename(zip_path)} (adding {years_to_add} years)...")

        def shift_date(date_str):
            if not date_str or len(date_str) != 8: return date_str
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                # Handle leap years by trying to replace the year and, if it fails, set March 1st.
                try:
                    new_dt = dt.replace(year=dt.year + years_to_add)
                except ValueError:
                    new_dt = dt.replace(year=dt.year + years_to_add, month=3, day=1)
                return new_dt.strftime("%Y%m%d")
            except:
                return date_str

        # 4. Rewrite calendar.txt with shifted dates.
        rows = []
        with open(calendar_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if 'end_date' in row: row['end_date'] = shift_date(row['end_date'])
                rows.append(row)

        with open(calendar_path, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # 5. Recreate the ZIP file with the modified contents.
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

    # 6. Clean up the temporary directory.
    shutil.rmtree(temp_dir)