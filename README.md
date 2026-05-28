# tfg-llm-gtfs-tenerife
TFG: Desarrollo de un asistente conversacional basado en LLM para la red de transporte público de Tenerife integrando datos GTFS y estimación de ocupación.

Este repositorio contiene el ETL para GTFS y matrices O-D, herramientas de consulta y un servidor MCP (Minimal Chat Protocol) que expone utilidades (herramientas) para un agente LLM (orquestador).

## Estructura del proyecto (resumen)

- `data/`
  - `raw/` : archivos GTFS y matrices O-D descargados (subcarpetas por fecha).
  - `staging/` : archivos ya procesados y conjuntos consolidados para carga/uso.
  - `otp/` : directorio montado para OpenTripPlanner (mapas, graph.obj, etc.).

- `src/`
  - `etl/` : scripts de extracción, transformación y carga (download_gtfs.py, download_od.py, load_gtfs.py, load_od.py, rebuild_otp.py, etc.).
  - `mcp/` : servidor MCP y herramientas que acceden a la base de datos/OTP (`server.py`, `db_tools.py`, `otp_tools.py`).
  - `agent/` : orquestador que actúa como cliente MCP y conecta un LLM (Gemini via `langchain_google_genai`) para interacción conversacional (`orchestrator.py`, `prompts.py`).
  - `config.py` : parámetros y constantes (conexión BD, rutas, etc.).

- `main.py` : lanzador que ejecuta el pipeline ETL completo (descarga, carga en PostgreSQL/PostGIS y reconstrucción del grafo OTP).
- `docker-compose.yml` : servicios Docker (PostGIS, OpenTripPlanner). Útil para levantar DB y OTP localmente.

## Requisitos previos

- Docker / Docker Compose (para PostGIS y OTP): https://docs.docker.com/
- Python 3.10+ y pip. Se recomienda usar un entorno virtual (venv).
- Variables de entorno (opcional): puedes usar un fichero `.env` en la raíz con claves como `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `GOOGLE_API_KEY`, etc. `src/config.py` lee `DB_PARAMS` de estas variables.

Nota: no hay un `requirements.txt` incluido en el repositorio. Instala las dependencias según los imports principales cuando procedas (ej.: `psycopg2-binary`, `fastmcp`, `mcp-client`/`mcp`, `requests`, `geopy`, `python-dotenv`, `langchain_google_genai`, `langchain-core`).

## Flujo detallado de ejecución (descarga → servidor MCP → orquestador)

A continuación se describe un flujo recomendado para ejecutar el proyecto localmente.

Checklist de pasos:

1) Levantar servicios Docker (PostGIS y OTP)
2) Ejecutar el pipeline ETL (`main.py`) para descargar y poblar la BD
3) Iniciar el servidor MCP (`src/mcp/server.py`)
4) Iniciar el orquestador (cliente MCP) `src/agent/orchestrator.py`

Pasos concretos (PowerShell en Windows):

1) Levantar la base de datos PostGIS y OTP (desde la raíz del proyecto):

```powershell
# Levanta únicamente la base de datos y OTP (en background)
docker compose up -d db otp

# O, para levantarlos todos los servicios definidos:
docker compose up -d
```

Comprobaciones:
- DB Postgres estará disponible en el puerto 5432 (según `docker-compose.yml`).
- OTP servirá en http://localhost:8080 (la imagen de OTP busca en `data/otp` el `graph.obj` o cargará feeds si se indica).

2) Ejecutar el pipeline ETL completo (desde la raíz del proyecto):

```powershell
# Ejecuta el pipeline completo: descarga GTFS/OD, carga en Postgres y reconstruye grafo OTP
py main.py

# Si tu sistema usa 'python' en lugar de 'py':
python main.py
```

Notas:
- `main.py` llama internamente a los módulos en `src/etl/` en este orden: descarga GTFS → descarga OD → carga GTFS → carga OD → rebuild OTP.
- Si prefieres controlar fases por separado, ejecuta los scripts individuales en `src/etl/` (por ejemplo `py src/etl/download_gtfs.py`).

3) Iniciar el servidor MCP (expone las herramientas que el orquestador consumirá):

```powershell
# Abrir una nueva terminal y desde la raíz del proyecto:
py src/mcp/server.py

# o
python src/mcp/server.py
```

El servidor MCP imprime las herramientas registradas y arranca en transporte `sse` por defecto. Debe ejecutarse antes de iniciar el orquestador cliente.

4) Iniciar el orquestador (cliente que conecta un LLM y usa las herramientas MCP):

```powershell
# Asegúrate de tener la variable de entorno GOOGLE_API_KEY si vas a usar Gemini
$env:GOOGLE_API_KEY = "<tu_api_key>"
py src/agent/orchestrator.py

# o
python src/agent/orchestrator.py
```

Importante:
- El orquestador se conecta por defecto a `http://localhost:8000/sse` (mismo host donde corre el MCP server creado por `src/mcp/server.py`). Si cambias puertos o host, actualiza `orchestrator.py`.
- Para que la herramienta `plan_trip` funcione correctamente, OpenTripPlanner (OTP) debe estar corriendo y accesible en `http://localhost:8080`.

5) Parar los servicios

```powershell
docker compose down
```

## Ejecución por partes y debugging

- Ejecuta scripts individuales en `src/etl/` para depurar descargas o cargas concretas.
- Revisa `data/raw/` y `data/staging/` para comprobar ficheros descargados y staging.
- Revisa logs de Docker para PostGIS y OTP con `docker compose logs db` y `docker compose logs otp`.

## Comandos útiles

- Levantar solo PostGIS: `docker compose up -d db`
- Levantar solo OTP: `docker compose up -d otp`
- Ejecutar sólo la descarga GTFS: `py src/etl/download_gtfs.py`
- Ejecutar solo servidor MCP: `py src/mcp/server.py`

---
