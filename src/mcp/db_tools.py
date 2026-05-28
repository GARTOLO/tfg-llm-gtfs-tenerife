import psycopg2
from src.config import DB_PARAMS
from src.etl.load_od import CAPACIDAD_DEFAULT

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut


def get_coordinates(location_name: str) -> str:
    """
    Translates a street address, place name, or point of interest into GPS coordinates (latitude and longitude).
    ALWAYS use this tool before 'plan_trip' if the user provides text locations instead of coordinates.

    Args:
        location_name: The name of the place or street (e.g., 'Intercambiador Santa Cruz', 'Calle Herradores La Laguna').
    """

    query = f"{location_name}, Tenerife, Islas Canarias, España"

    # An exception will be thrown if a custom user_agent is not specified.
    geolocator = Nominatim(user_agent="TitsaGPT_Tenerife_TFG")

    try:
        location = geolocator.geocode(query, timeout=10)

        if location:
            return f"Éxito. Coordenadas para '{location_name}': latitud {location.latitude}, longitud {location.longitude}"
        else:
            return f"Error: No he podido encontrar la ubicación '{location_name}' en Tenerife. Pídele al usuario que sea más específico (ej. añadiendo el municipio)."

    except GeocoderTimedOut:
        return "Error: El servicio de mapas de OpenStreetMap ha tardado demasiado. Inténtalo de nuevo."
    except Exception as e:
        return f"Error interno de geocodificación: {str(e)}"

def get_line_occupancy(route_id: str, day_type: str = 'Laborable') -> str:
    """
    Returns the estimated passenger occupancy profile for a specific transit route for the ENTIRE DAY.
    Do NOT pass a 'time' or 'hour' argument. This tool automatically returns the data for all 24 hours.
    If the user asks for a specific hour (for example, 'at 16:00' or 'in the afternoon'), still call this tool
    and then select the relevant hourly row(s) from its output before answering.

    Args:
        route_id: The transit route/line number (e.g., '15', '57', '910', 'L1'). If the user says "línea 57", use '57' directly. Do NOT ask the user for confirmation or an exact identifier.
        day_type: The type of day. MUST be 'Laborable', 'Sabado' (Saturday, no tilde), or 'Festivo' (holidays/Sundays).
        The function normalizes common variations: 'sábado', 'Saturday', 'sunday', 'holiday' are accepted and mapped to the canonical form.
    """
    linea_id_clean = route_id.lstrip('0') if route_id.startswith('0') and len(route_id) > 1 else route_id

    # Normalize day type (catch hallucinations like English day names or different capitalizations)
    day_type_lower = day_type.lower()
    if day_type_lower in ['sabado', 'sábado', 'saturday']:
        tipo_dia_db = 'Sabado'
    elif day_type_lower in ['festivo', 'domingo', 'sunday', 'holiday']:
        tipo_dia_db = 'Festivo'
    else:
        tipo_dia_db = 'Laborable'

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        query = """
            SELECT
                viaje_hora,
                pasajeros_franja_horaria,
                num_expediciones,
                capacidad_vehiculo_ref,
                capacidad_franja_total,
                pct_ocupacion_estimado,
                nivel_ocupacion,
                expediciones_estimadas,
                gtfs_route_short_name,
                gtfs_route_long_name
            FROM analytics.v_ocupacion_mcp
            WHERE linea_id = %s
              AND tipo_dia  = %s
            ORDER BY viaje_hora ASC;
        """
        cur.execute(query, (linea_id_clean, tipo_dia_db))
        results = cur.fetchall()

        # Fallback: si no encontramos con el ID limpio, probamos con el original
        if not results and linea_id_clean != route_id:
            cur.execute(query, (route_id, tipo_dia_db))
            results = cur.fetchall()
            if results:
                linea_id_clean = route_id

        if not results:
            return (
                f"No tengo datos de ocupación para la línea '{route_id}' "
                f"en días tipo '{tipo_dia_db}'. "
                f"Comprueba que el identificador de línea es correcto."
            )

        # Metadatos de cabecera (iguales en todas las filas)
        _, _, _, capacidad_ref, _, _, _, _, route_short, route_long = results[0]
        nombre_linea = f"{route_short} - {route_long}" if route_short else linea_id_clean
        capacidad_ref = capacidad_ref or CAPACIDAD_DEFAULT

        # Hora punta = fila con más pasajeros
        hora_punta = max(results, key=lambda r: r[1] or 0)

        # Construimos el perfil horario
        iconos = {'bajo': '🟢', 'moderado': '🟡', 'alto': '🟠', 'muy_alto': '🔴'}
        lineas_perfil = []
        total_pasajeros = 0
        hay_estimadas = False

        for hora, pasajeros, num_exp, _, cap_franja, pct, nivel, exp_estimadas, _, _ in results:
            pasajeros = pasajeros or 0
            pct       = pct or 0
            num_exp   = num_exp or 1
            cap_franja = cap_franja or capacidad_ref
            pax_por_expedicion = round(pasajeros / num_exp, 1) if num_exp else 0
            icono     = iconos.get(nivel, '⚪')
            aviso     = ' ⚠️' if exp_estimadas else ''
            lineas_perfil.append(
                f"  {icono} {hora:02d}:00 → {pasajeros} pax | "
                f"{num_exp} expediciones (~{pax_por_expedicion} pax/exp) | "
                f"{cap_franja} plazas totales | "
                f"{pct}% ocupación ({nivel}){aviso}"
            )
            total_pasajeros += pasajeros
            if exp_estimadas:
                hay_estimadas = True

        hp_hora, hp_pax, hp_exp, _, hp_cap, hp_pct, hp_nivel, _, _, _ = hora_punta

        respuesta = (
            f"📊 Ocupación de la línea {nombre_linea} — {tipo_dia_db}\n"
            f"{'─' * 55}\n"
            + "\n".join(lineas_perfil)
            + f"\n{'─' * 55}\n"
            f"⏱  Hora punta: {hp_hora:02d}:00 — {hp_pax} pax en {hp_exp} expediciones "
            f"(~{round(hp_pax / hp_exp, 1) if hp_exp else 0} pax/exp) "
            f"({hp_pct}% ocupación, {hp_nivel})\n"
            f"👥 Total pasajeros estimados en el día: {total_pasajeros}\n"
            f"🚌 Capacidad de referencia por vehículo: {capacidad_ref} plazas\n"
        )

        if hay_estimadas:
            respuesta += (
                f"\n⚠️  Algunas franjas horarias tienen expediciones estimadas "
                f"(sin dato GTFS para esa hora). El porcentaje de ocupación en esas "
                f"franjas es menos fiable.\n"
            )

        respuesta += (
            f"\n[CONTEXTO PARA LA IA]\n"
            f"Pasajeros por franja = media diaria real (pasajeros_cantidad / fechas_calculadas), "
            f"sumando ambos sentidos (ida + vuelta). No interpretarlo como pax por bus. "
            f"Si el usuario quiere una lectura más intuitiva, usa pax/exp = pasajeros / expediciones. "
            f"Expediciones = media diaria de salidas del GTFS para esa línea, hora y tipo de día. "
            f"Ocupación (%) = pasajeros / (expediciones × {capacidad_ref} plazas/bus). "
            f"Capacidad por defecto {capacidad_ref} plazas — actualizable en dim_capacidad_linea."
        )

        return respuesta

    except Exception as e:
        return f"Error al consultar la base de datos: {str(e)}"
    finally:
        if conn:
            cur.close()
            conn.close()


def get_stop_info(stop_id: str) -> str:
    """
    Returns information about a specific transit stop, including its name and the list of lines that operate there.

    Args:
        stop_id: The ID code of the stop (e.g., '1014', '9181').
    """
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        # 1. Get the name of the stop
        cur.execute("SELECT stop_name FROM gtfs_raw.stops WHERE stop_id = %s;", (stop_id,))
        stop = cur.fetchone()

        if not stop:
            return f"No he encontrado ninguna parada con el código {stop_id}."

        stop_name = stop[0]

        # 2. Get the lines that operate at this stop
        cur.execute("""
                    SELECT DISTINCT r.route_short_name, r.route_long_name
                    FROM gtfs_raw.stop_times st
                             JOIN gtfs_raw.trips t ON st.trip_id = t.trip_id
                             JOIN gtfs_raw.routes r ON t.route_id = r.route_id
                    WHERE st.stop_id = %s
                    ORDER BY r.route_short_name;
                    """, (stop_id,))

        lines = cur.fetchall()

        respuesta = f"🚏 Parada {stop_id}: {stop_name}\n\n"
        respuesta += "Líneas que operan en esta parada:\n"

        for short_name, long_name in lines:
            respuesta += f"- Línea {short_name}: {long_name}\n"

        respuesta += "\nNota para la IA: Si el usuario quiere saber a qué hora exacta pasa la guagua por aquí para ir a un sitio, recuérdale usar la herramienta 'plan_trip'."

        return respuesta

    except Exception as e:
        return f"Error al consultar la parada: {str(e)}"
    finally:
        if conn:
            cur.close()
            conn.close()


def get_route_info(route_id: str) -> str:
    """
    Returns general information about a specific transit route (bus or tram).
    Provides the full name of the route (origin - destination) and its operating hours.

    Args:
        route_id: The ID of the route (e.g., '15', '910', 'L1').
    """

    linea_id_clean = route_id.lstrip('0') if route_id.startswith('0') and len(route_id) > 1 else route_id

    conn = None
    cur = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        # 1. Get the line
        cur.execute("""
                    SELECT route_short_name, route_long_name
                    FROM gtfs_raw.routes
                    WHERE route_short_name = %s
                       OR route_short_name = %s LIMIT 1;
                    """, (linea_id_clean, route_id))

        route = cur.fetchone()
        if not route:
            return f"No he encontrado información para la línea {route_id} en la base de datos."

        short_name, long_name = route

        # 2. Get the first and last service
        cur.execute("""
                    SELECT MIN(st.departure_time), MAX(st.arrival_time)
                    FROM gtfs_raw.trips t
                             JOIN gtfs_raw.stop_times st ON t.trip_id = st.trip_id
                             JOIN gtfs_raw.routes r ON t.route_id = r.route_id
                    WHERE r.route_short_name = %s
                       OR r.route_short_name = %s;
                    """, (linea_id_clean, route_id))

        horarios = cur.fetchone()
        primer_servicio = horarios[0][:5] if horarios[0] else "Desconocido"
        ultimo_servicio = horarios[1][:5] if horarios[1] else "Desconocido"

        respuesta = f"🚌 Información de la Línea {short_name}:\n"
        respuesta += f"- Trayecto: {long_name}\n"
        respuesta += f"- Horario habitual de operación: Desde las {primer_servicio} hasta las {ultimo_servicio} aprox.\n"
        respuesta += "\nNota para la IA: Usa esta información para dar contexto al usuario. Si el usuario pide un viaje exacto ahora mismo, usa la herramienta 'plan_trip'."

        return respuesta

    except Exception as e:
        return f"Error al consultar la ruta: {str(e)}"
    finally:
        if conn:
            cur.close()
            conn.close()

def get_routes_demo() -> str:
    """Return example routes"""
    return "Rutas disponibles: Ruta A, Ruta B, Ruta C"