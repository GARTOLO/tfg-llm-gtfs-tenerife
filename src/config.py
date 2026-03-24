import os
from dotenv import load_dotenv

load_dotenv()

DB_PARAMS = {
    # os.getenv("NOMBRE_VARIABLE", "valor_por_defecto_si_falla")
    "dbname": os.getenv("DB_NAME", "gtfs_titsa"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")