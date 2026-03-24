import os
from dotenv import load_dotenv

load_dotenv()

DB_PARAMS = {
    # os.getenv("VARIABLE_NAME", "default_value")
    "dbname": os.getenv("DB_NAME", "gtfs_titsa"),
    "user": os.getenv("DB_USER", "postgres_user"),
    "password": os.getenv("DB_PASSWORD", "postgres_password"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")