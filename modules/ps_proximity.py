"""
ps_proximity.py — Police Station Proximity Scoring.

All 54 police station coordinates are derived from the ASTraM dataset
(mean lat/lon per station across all historical events).

No external API needed. Pure Haversine distance ranking.

Public API:
    get_nearest_stations(lat, lon, top_n=3) → list of station dicts
    rank_by_availability(lat, lon, active_events, top_n=3) → adjusted ranking
    get_all_stations() → list of all station dicts
    get_station_coords(name) → (lat, lon)
"""

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Ground-truth station coordinates (derived from train.csv mean lat/lon)
# ---------------------------------------------------------------------------
POLICE_STATIONS: dict = {
    "Adugodi":                  (12.93385, 77.61943),
    "Ashok Nagar":              (12.96236, 77.60979),
    "Banashankari":             (12.92321, 77.55685),
    "Banaswadi":                (13.00087, 77.65669),
    "Basavanagudi":             (12.94262, 77.57138),
    "Bellandur":                (12.91889, 77.67037),
    "Byatarayanapura":          (12.94936, 77.53423),
    "Chamarajpet":              (12.96553, 77.56379),
    "Chikkabanavara":           (13.04809, 77.50618),
    "Chikkajala":               (13.16524, 77.64165),
    "City Market":              (12.96173, 77.57835),
    "Cubbon Park":              (12.97811, 77.59561),
    "Devanahalli Airport":      (13.23799, 77.70195),
    "Electronic City":          (12.85184, 77.66473),
    "HAL Old Airport":          (12.95323, 77.69713),
    "HSR Layout":               (12.91023, 77.63161),
    "Halasur":                  (12.96942, 77.62588),
    "Halasuru Gate":            (12.96716, 77.58732),
    "Hebbala":                  (13.04403, 77.59572),
    "Hennuru":                  (13.04469, 77.63335),
    "High ground":              (12.98870, 77.58548),
    "Hulimavu":                 (12.87264, 77.60441),
    "J.P. Nagar":               (12.90328, 77.59022),
    "Jalahalli":                (13.04361, 77.54884),
    "Jayanagara":               (12.92088, 77.58756),
    "Jeevanbheemanagar":        (12.97311, 77.64554),
    "Jnanabharathi":            (12.96046, 77.50785),
    "K.G. Halli":               (13.03035, 77.62028),
    "K.R. Pura":                (13.01615, 77.70573),
    "K.S. Layout":              (12.90913, 77.55808),
    "Kamakshipalya":            (12.98779, 77.50789),
    "Kengeri":                  (12.91263, 77.48377),
    "Kodigehalli":              (13.04699, 77.58570),
    "Madiwala":                 (12.91774, 77.62142),
    "Magadi Road":              (12.97374, 77.55657),
    "Mahadevapura":             (12.99278, 77.71789),
    "Malleshwaram":             (13.00449, 77.56229),
    "Mico Layout":              (12.91339, 77.60489),
    "Peenya":                   (13.03882, 77.51460),
    "Pulikeshinagar(F.Town)":   (12.99687, 77.61453),
    "R.T. Nagar":               (13.01553, 77.58963),
    "Rajajinagar":              (13.00477, 77.54120),
    "Sadashivanagar":           (13.01033, 77.57972),
    "Sheshadripuram":           (12.98676, 77.57270),
    "Shivajinagar":             (12.98288, 77.60258),
    "Thalagattapura":           (12.87185, 77.54824),
    "Upparpet":                 (12.97666, 77.57717),
    "V.V.Puram (C.Pet)":        (12.95823, 77.57295),
    "Vijayanagara":             (12.97928, 77.54219),
    "Whitefield":               (12.95055, 77.74065),
    "Wilson Garden":            (12.94755, 77.59249),
    "Yelahanka":                (13.10144, 77.59602),
    "Yeshwanthpura":            (13.02620, 77.54476),
}

# Zone assignment (from dataset zone column)
STATION_ZONES: dict = {
    "Adugodi": "South Zone 2",
    "Ashok Nagar": "Central Zone 2",
    "Banashankari": "South Zone 1",
    "Banaswadi": "East Zone 1",
    "Basavanagudi": "South Zone 1",
    "Bellandur": "East Zone 2",
    "Byatarayanapura": "West Zone 1",
    "Chamarajpet": "Central Zone 1",
    "Chikkabanavara": "North Zone 2",
    "Chikkajala": "North Zone 2",
    "City Market": "Central Zone 1",
    "Cubbon Park": "Central Zone 2",
    "Devanahalli Airport": "North Zone 2",
    "Electronic City": "South Zone 2",
    "HAL Old Airport": "East Zone 1",
    "HSR Layout": "South Zone 2",
    "Halasur": "Central Zone 2",
    "Halasuru Gate": "Central Zone 2",
    "Hebbala": "North Zone 1",
    "Hennuru": "North Zone 1",
    "High ground": "Central Zone 2",
    "Hulimavu": "South Zone 2",
    "J.P. Nagar": "South Zone 1",
    "Jalahalli": "North Zone 1",
    "Jayanagara": "South Zone 1",
    "Jeevanbheemanagar": "East Zone 1",
    "Jnanabharathi": "West Zone 1",
    "K.G. Halli": "East Zone 1",
    "K.R. Pura": "East Zone 2",
    "K.S. Layout": "South Zone 1",
    "Kamakshipalya": "West Zone 1",
    "Kengeri": "West Zone 2",
    "Kodigehalli": "North Zone 1",
    "Madiwala": "South Zone 2",
    "Magadi Road": "West Zone 1",
    "Mahadevapura": "East Zone 2",
    "Malleshwaram": "North Zone 1",
    "Mico Layout": "South Zone 2",
    "Peenya": "North Zone 2",
    "Pulikeshinagar(F.Town)": "Central Zone 2",
    "R.T. Nagar": "North Zone 1",
    "Rajajinagar": "West Zone 1",
    "Sadashivanagar": "North Zone 1",
    "Sheshadripuram": "Central Zone 1",
    "Shivajinagar": "Central Zone 2",
    "Thalagattapura": "South Zone 1",
    "Upparpet": "Central Zone 1",
    "V.V.Puram (C.Pet)": "South Zone 1",
    "Vijayanagara": "West Zone 1",
    "Whitefield": "East Zone 2",
    "Wilson Garden": "South Zone 2",
    "Yelahanka": "North Zone 2",
    "Yeshwanthpura": "North Zone 1",
}


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Estimated response time (road factor ≈ 1.4× straight-line)
# ---------------------------------------------------------------------------

def _response_minutes(distance_km: float, road_factor: float = 1.4) -> float:
    """Estimate travel time in minutes assuming average speed of 30 km/h in city."""
    road_km = distance_km * road_factor
    return round((road_km / 30) * 60, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_nearest_stations(
    lat: float,
    lon: float,
    top_n: int = 3,
    exclude: Optional[list] = None,
) -> list:
    """
    Return the top-N nearest police stations to the given coordinates.

    Args:
        lat, lon : Event location.
        top_n    : Number of stations to return.
        exclude  : Station names to skip (e.g., already assigned).

    Returns:
        List of dicts sorted by distance:
        [{name, lat, lon, distance_km, response_min, zone, rank}, ...]
    """
    exclude_set = set(exclude or [])
    results = []

    for name, (ps_lat, ps_lon) in POLICE_STATIONS.items():
        if name in exclude_set or name == "No Police Station":
            continue
        dist = haversine_km(lat, lon, ps_lat, ps_lon)
        results.append(
            {
                "name": name,
                "lat": ps_lat,
                "lon": ps_lon,
                "distance_km": round(dist, 2),
                "response_min": _response_minutes(dist),
                "zone": STATION_ZONES.get(name, "Unknown"),
            }
        )

    results.sort(key=lambda x: x["distance_km"])
    for i, r in enumerate(results[:top_n], start=1):
        r["rank"] = i

    return results[:top_n]


def rank_by_availability(
    lat: float,
    lon: float,
    active_events: Optional[list] = None,
    top_n: int = 3,
) -> list:
    """
    Rank stations by proximity but penalise those with active assignments.

    Each active event adds a 0.5 km workload penalty to the assigned station.
    This keeps dispatch logic transparent and data-driven.

    Args:
        lat, lon      : Event location.
        active_events : List of active event dicts, each with 'police_station'.
        top_n         : Number of stations to return.

    Returns:
        List of station dicts with 'adjusted_distance_km' and 'active_events'.
    """
    active_events = active_events or []

    # Count active assignments per station
    workload: dict = {}
    for evt in active_events:
        ps = str(evt.get("police_station", ""))
        if ps:
            workload[ps] = workload.get(ps, 0) + 1

    results = []
    for name, (ps_lat, ps_lon) in POLICE_STATIONS.items():
        if name == "No Police Station":
            continue
        base_dist = haversine_km(lat, lon, ps_lat, ps_lon)
        penalty = workload.get(name, 0) * 0.5
        adj_dist = base_dist + penalty
        results.append(
            {
                "name": name,
                "lat": ps_lat,
                "lon": ps_lon,
                "distance_km": round(base_dist, 2),
                "adjusted_distance_km": round(adj_dist, 2),
                "response_min": _response_minutes(base_dist),
                "active_assignments": workload.get(name, 0),
                "zone": STATION_ZONES.get(name, "Unknown"),
            }
        )

    results.sort(key=lambda x: x["adjusted_distance_km"])
    for i, r in enumerate(results[:top_n], start=1):
        r["rank"] = i

    return results[:top_n]


def get_all_stations() -> list:
    """Return all stations as a list of dicts with coords and zone."""
    return [
        {
            "name": name,
            "lat": lat,
            "lon": lon,
            "zone": STATION_ZONES.get(name, "Unknown"),
        }
        for name, (lat, lon) in POLICE_STATIONS.items()
        if name != "No Police Station"
    ]


def get_station_coords(name: str) -> Optional[tuple]:
    """Return (lat, lon) for a station name, or None if not found."""
    return POLICE_STATIONS.get(name)


def get_stations_by_zone(zone: str) -> list:
    """Return all stations in a given zone."""
    return [
        {"name": name, "lat": lat, "lon": lon}
        for name, (lat, lon) in POLICE_STATIONS.items()
        if STATION_ZONES.get(name) == zone
    ]
