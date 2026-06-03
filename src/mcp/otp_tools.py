import requests
from datetime import datetime
from typing import Optional

OTP_GRAPHQL_URL = "http://localhost:8080/otp/routers/default/index/graphql"


def plan_trip(
        origin_lat: float,
        origin_lon: float,
        destination_lat: float,
        destination_lon: float,
        date: Optional[str] = None,
        time: Optional[str] = None
) -> str:
    """
    Calculates the best public transit or walking route between two geographical points.
    Useful for answering routing queries like "how do I get from X to Y".

    Args:
        origin_lat: Latitude of the starting point (e.g., 28.48114)
        origin_lon: Longitude of the starting point (e.g., -16.31590)
        destination_lat: Latitude of the destination point (e.g., 28.45543)
        destination_lon: Longitude of the destination point (e.g., -16.25464)
        date: (Optional) Date in YYYY-MM-DD format. If omitted, today's date is used.
        time: (Optional) Time in HH:MM:SS format. If omitted, the current time is used.
    """

    # If the LLM does not specify a date or time, use the current local time
    now = datetime.now()
    if not date:
        date = now.strftime("%Y-%m-%d")
    if not time:
        time = now.strftime("%H:%M:%S")

    # GraphQL query written exactly with OTP 2 syntax
    query = """
    query planTrip($latFrom: Float!, $lonFrom: Float!, $latTo: Float!, $lonTo: Float!, $date: String, $time: String) {
      plan(
        from: {lat: $latFrom, lon: $lonFrom}
        to: {lat: $latTo, lon: $lonTo}
        date: $date
        time: $time
        numItineraries: 2
      ) {
        itineraries {
          duration
          walkDistance
          legs {
            mode
            startTime
            endTime
            route {
              shortName
            }
            from {
              name
            }
            to {
              name
            }
          }
        }
      }
    }
    """

    variables = {
        "latFrom": origin_lat,
        "lonFrom": origin_lon,
        "latTo": destination_lat,
        "lonTo": destination_lon,
        "date": date,
        "time": time
    }

    try:
        response = requests.post(
            OTP_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=10
        )
        response.raise_for_status()

        data = response.json()

        # Validation: Check if OTP found any valid itineraries
        if not data.get("data") or not data["data"].get("plan") or not data["data"]["plan"].get("itineraries"):
            return "No feasible routes were found between these two points for the specified date/time."

        # Return the clean JSON to the LLM as a string
        itineraries = data["data"]["plan"]["itineraries"]
        return str(itineraries)

    except requests.exceptions.RequestException as e:
        return f"Critical error connecting to the routing engine (OpenTripPlanner): {e}"