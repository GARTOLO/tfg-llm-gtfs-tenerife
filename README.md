# tfg-llm-gtfs-tenerife
TFG: Desarrollo de un asistente conversacional basado en LLM para la red de transporte público de Tenerife integrando datos GTFS y estimación de ocupación.

## Flujo de trabajo (resumen)
1. Levantar la base de datos PostgreSQL/PostGIS.
2. Descargar datos crudos (GTFS y matrices OD) en `data/raw/`.
3. Ejecutar las cargas ETL para poblar PostgreSQL:
   - GTFS en esquema `gtfs_raw`.
   - OD en esquema `analytics`.

## Ejecución rápida
Desde la raíz del proyecto:

```bash
docker compose up -d
python src/etl/main_downloader.py
python src/etl/load_gtfs.py
python src/etl/load_od.py
```

> Nota: la conexión a base de datos se toma de variables de entorno (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`) definidas en `src/config.py` (vía `.env` o valores por defecto).
