# tfg-llm-gtfs-tenerife
TFG: Desarrollo de un asistente conversacional basado en LLM para la red de transporte público de Tenerife integrando datos GTFS y estimación de ocupación.

## Flujo de trabajo (resumen)
1. Levantar la base de datos PostgreSQL/PostGIS.
2. Ejecutar el script único de ETL para descargar los datos crudos (GTFS y matrices OD) en `data/raw/`.
3. Ejecutar las cargas ETL para poblar PostgreSQL/PostGIS:
   - GTFS en esquema `gtfs_raw`.
   - OD en esquema `analytics`.

## Ejecución rápida
Desde la raíz del proyecto:

```bash
docker compose up -d
py main.py
```

Si prefieres ejecutar las fases por separado:

```bash
py src/etl/download_gtfs.py
py src/etl/download_od.py
py src/etl/load_gtfs.py
py src/etl/load_od.py
```

> Si tu instalación usa `python` en lugar de `py`, puedes sustituir el comando sin problema.

> Nota: la conexión a base de datos se toma de variables de entorno (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`) definidas en `src/config.py` (vía `.env` o valores por defecto).
