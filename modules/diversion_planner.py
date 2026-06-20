"""
diversion_planner.py — Google Maps-based diversion route planner for EventIQ.

Uses the Google Maps Directions API to find 2-3 alternate routes around
an incident, ranked by estimated travel time increase vs. the blocked route.

Public API:
    plan_diversions(event, weather_ctx=None) -> DiversionPlan
    get_diversion_summary(plan)              -> str

The API key is read from the GOOGLE_MAPS_API_KEY environment variable (.env).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# ---------------------------------------------------------------------------
# Bangalore-specific known diversion corridors per primary corridor
# ---------------------------------------------------------------------------
# Each entry: primary_corridor -> [(via_waypoint_address, description)]
_CORRIDOR_DIVERSIONS: dict[str, list[tuple[str, str]]] = {
    "Mysore Road": [
        ("Kanakapura Road, Bangalore", "Via Kanakapura Road (parallel south)"),
        ("Bannerghata Road, Bangalore", "Via Bannerghata Road (south alternate)"),
    ],
    "Bellary Road 1": [
        ("Hebbal Flyover, Bangalore", "Via Hebbal–NH44 bypass"),
        ("Outer Ring Road North, Bangalore", "Via ORR north segment"),
    ],
    "Bellary Road 2": [
        ("Hebbal Flyover, Bangalore", "Via Hebbal–NH44 bypass"),
        ("Outer Ring Road North, Bangalore", "Via ORR north segment"),
    ],
    "Bannerghata Road": [
        ("Kanakapura Road, Bangalore", "Via Kanakapura Road (west)"),
        ("Hosur Road, Bangalore", "Via Hosur Road (east)"),
    ],
    "Old Madras Road": [
        ("KR Puram Bridge, Bangalore", "Via KR Puram–Tin Factory"),
        ("Outer Ring Road East, Bangalore", "Via ORR east (Marathahalli)"),
    ],
    "Airport New South Road": [
        ("Bellary Road, Bangalore", "Via Bellary Road main corridor"),
        ("NH44 Bypass, Bangalore", "Via NH44 expressway"),
    ],
    "Hosur Road": [
        ("Bannerghata Road, Bangalore", "Via Bannerghata–BTM Layout"),
        ("Electronic City Phase 2, Bangalore", "Via NICE Road elevated"),
    ],
    "Outer Ring Road East": [
        ("Sarjapur Road, Bangalore", "Via Sarjapur–Carmelaram"),
        ("Whitefield Main Road, Bangalore", "Via Whitefield bypass"),
    ],
    "Tumkur Road": [
        ("Peenya Industrial Area, Bangalore", "Via Peenya–Yeshwanthpur"),
        ("Hesarghatta Road, Bangalore", "Via Hesarghatta bypass"),
    ],
    "Magadi Road": [
        ("Chord Road, Bangalore", "Via Chord Road parallel"),
        ("Mysore Road, Bangalore", "Via Mysore Road south"),
    ],
    "CBD 1": [
        ("MG Road, Bangalore", "Via MG Road–Brigade Road"),
        ("Residency Road, Bangalore", "Via Residency Road"),
    ],
    "CBD 2": [
        ("MG Road, Bangalore", "Via MG Road–Brigade Road"),
        ("Residency Road, Bangalore", "Via Residency Road"),
    ],
    "West of Chord Road": [
        ("Chord Road, Bangalore", "Via Chord Road main"),
        ("Magadi Road, Bangalore", "Via Magadi Road south"),
    ],
    "Domlur Flyover": [
        ("Intermediate Ring Road, Bangalore", "Via IRR–Indira Nagar"),
        ("HAL Airport Road, Bangalore", "Via Old Airport Road"),
    ],
    "Silk Board Junction": [
        ("Bannerghata Road, Bangalore", "Via Bannerghata Road bypass"),
        ("Sarjapur Road, Bangalore", "Via Sarjapur–Agara"),
    ],
    "KR Puram Bridge": [
        ("Outer Ring Road East, Bangalore", "Via ORR east"),
        ("Tin Factory Junction, Bangalore", "Via Tin Factory–Ramamurthy Nagar"),
    ],
    "Non-corridor": [],   # no pre-set diversions for non-corridor events
}

# Generic fallback if corridor not in table
_GENERIC_DIVERSIONS = [
    ("Outer Ring Road, Bangalore", "Via Outer Ring Road"),
    ("NICE Road, Bangalore", "Via NICE Road expressway"),
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Route:
    name: str
    description: str
    distance_km: float
    duration_min: int
    duration_in_traffic_min: Optional[int]
    via: str
    delay_vs_normal_min: int          # vs no-incident duration
    weather_adjusted_duration_min: Optional[int]
    polyline: Optional[str]           # encoded polyline for map rendering
    is_recommended: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiversionPlan:
    origin_address: str
    destination_address: str
    incident_corridor: str
    blocked_route_duration_min: Optional[int]
    routes: list = field(default_factory=list)
    weather_context: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    api_success: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def best_route(self) -> Optional[Route]:
        rec = [r for r in self.routes if r.is_recommended]
        return rec[0] if rec else (self.routes[0] if self.routes else None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coords_to_latlng(lat: float, lon: float) -> str:
    return f"{lat},{lon}"


def _weather_delay_factor(weather_ctx: dict) -> float:
    """Extra travel time multiplier due to weather (1.0 = no delay)."""
    sev = weather_ctx.get("severity", 0) if weather_ctx else 0
    return {0: 1.0, 1: 1.10, 2: 1.25, 3: 1.45}.get(sev, 1.0)


def _call_directions(
    origin: str,
    destination: str,
    waypoint: Optional[str],
    departure_time: str = "now",
) -> Optional[dict]:
    """Single Google Maps Routes API v2 call (POST)."""
    if not _MAPS_KEY:
        return None

    def _latlng_body(coord_str: str) -> dict:
        """Convert '12.97,77.59' or address string to Routes API location body."""
        parts = coord_str.strip().split(",")
        if len(parts) == 2:
            try:
                return {"location": {"latLng": {
                    "latitude": float(parts[0]),
                    "longitude": float(parts[1]),
                }}}
            except ValueError:
                pass
        return {"address": coord_str}

    body: dict = {
        "origin": _latlng_body(origin),
        "destination": _latlng_body(destination),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "computeAlternativeRoutes": True,
        "languageCode": "en-IN",
        "units": "METRIC",
    }
    if waypoint:
        body["intermediates"] = [{"address": waypoint}]

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _MAPS_KEY,
        "X-Goog-FieldMask": (
            "routes.duration,routes.distanceMeters,"
            "routes.legs.duration,routes.legs.distanceMeters,"
            "routes.legs.steps.polyline,routes.polyline.encodedPolyline,"
            "routes.description,routes.localizedValues"
        ),
    }
    try:
        resp = requests.post(_ROUTES_URL, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _parse_route(route: dict, name: str, description: str, via: str,
                 baseline_min: Optional[int], weather_factor: float) -> Route:
    """Parse a Routes API v2 route object."""
    dist_m = route.get("distanceMeters", 0) or 0
    # Routes API returns duration as "123s" string or int seconds
    dur_raw = route.get("duration", "0s")
    if isinstance(dur_raw, str):
        dur_s = int(dur_raw.rstrip("s")) if dur_raw.endswith("s") else int(dur_raw)
    else:
        dur_s = int(dur_raw)

    dur_min = max(1, int(dur_s / 60))
    delay = (dur_min - baseline_min) if baseline_min else 0
    weather_adj = int(dur_min * weather_factor) if weather_factor > 1.0 else None

    # Encoded polyline lives at route level in Routes API
    polyline = route.get("polyline", {}).get("encodedPolyline")

    return Route(
        name=name,
        description=description,
        distance_km=round(dist_m / 1000, 2),
        duration_min=dur_min,
        duration_in_traffic_min=dur_min,   # Routes API already uses traffic
        via=via,
        delay_vs_normal_min=max(0, delay),
        weather_adjusted_duration_min=weather_adj,
        polyline=polyline,
    )


# ---------------------------------------------------------------------------
# Main planner
# ---------------------------------------------------------------------------

class DiversionPlanner:

    def plan_diversions(
        self,
        event: dict,
        weather_ctx: Optional[dict] = None,
    ) -> DiversionPlan:
        """
        Plan 2-3 diversion routes around the event location.

        Args:
            event:       Raw event dict (needs latitude, longitude, corridor,
                         address or a usable location string)
            weather_ctx: Output of weather.get_weather_impact() — used to
                         add weather-adjusted travel times on routes

        Returns:
            DiversionPlan with ranked routes
        """
        lat = float(event.get("latitude") or 12.97)
        lon = float(event.get("longitude") or 77.59)
        corridor = str(event.get("corridor") or "Non-corridor")
        address = str(event.get("address") or _coords_to_latlng(lat, lon))

        origin_latlng = _coords_to_latlng(lat, lon)
        weather_factor = _weather_delay_factor(weather_ctx)
        notes: list[str] = []

        # Choose diversion waypoints for this corridor
        waypoints = _CORRIDOR_DIVERSIONS.get(corridor, _GENERIC_DIVERSIONS)
        if not waypoints and corridor != "Non-corridor":
            waypoints = _GENERIC_DIVERSIONS
            notes.append("No preset diversion for corridor — using generic ORR/NICE Road routes")

        # Use event end-address as destination if available, else 5 km north
        end_lat = float(event.get("endlatitude") or 0.0)
        end_lon = float(event.get("endlongitude") or 0.0)
        if end_lat and end_lon and end_lat != lat:
            dest_latlng = _coords_to_latlng(end_lat, end_lon)
        else:
            dest_latlng = f"{lat + 0.05},{lon}"   # ~5 km north default

        plan = DiversionPlan(
            origin_address=address,
            destination_address=dest_latlng,
            incident_corridor=corridor,
            blocked_route_duration_min=None,
            routes=[],
            weather_context=weather_ctx or {},
            notes=notes,
            api_success=False,
        )

        if not _MAPS_KEY:
            plan.notes.append("Google Maps API key not configured — route data unavailable")
            plan.routes = self._fallback_routes(corridor, weather_factor)
            return plan

        # Fetch baseline (direct route, likely blocked)
        baseline_data = _call_directions(origin_latlng, dest_latlng, waypoint=None)
        baseline_min: Optional[int] = None
        if baseline_data and baseline_data.get("routes"):
            bl_route = baseline_data["routes"][0]
            dur_raw = bl_route.get("duration", "0s")
            if isinstance(dur_raw, str):
                dur_s = int(dur_raw.rstrip("s")) if dur_raw.endswith("s") else int(dur_raw)
            else:
                dur_s = int(dur_raw)
            baseline_min = max(1, int(dur_s / 60))
            plan.blocked_route_duration_min = baseline_min

        # Fetch alternate routes via each waypoint
        routes: list[Route] = []
        for i, (waypoint, description) in enumerate(waypoints[:3], start=1):
            resp = _call_directions(origin_latlng, dest_latlng, waypoint=waypoint)
            if not resp or not resp.get("routes"):
                continue
            plan.api_success = True
            route_obj = resp["routes"][0]
            route = _parse_route(
                route=route_obj,
                name=f"Route {i}",
                description=description,
                via=waypoint.split(",")[0],
                baseline_min=baseline_min,
                weather_factor=weather_factor,
            )
            routes.append(route)

        # Add weather note if applicable
        if weather_ctx and weather_ctx.get("severity", 0) >= 2:
            notes.append(
                f"Weather: {weather_ctx.get('condition','adverse')} — "
                f"travel times adjusted ×{weather_factor:.2f}"
            )

        # Rank: lowest weather-adjusted (or in-traffic) duration first
        routes.sort(key=lambda r: (r.weather_adjusted_duration_min or r.duration_in_traffic_min or r.duration_min))

        # Mark best route
        if routes:
            routes[0].is_recommended = True

        plan.routes = routes
        plan.notes = notes

        if not routes:
            plan.routes = self._fallback_routes(corridor, weather_factor)
            plan.notes.append("API returned no routes — showing preset fallback diversions")

        return plan

    def _fallback_routes(self, corridor: str, weather_factor: float = 1.0) -> list[Route]:
        """Static fallback diversions when API is unavailable."""
        waypoints = _CORRIDOR_DIVERSIONS.get(corridor) or _GENERIC_DIVERSIONS
        fallback = []
        for i, (via, desc) in enumerate(waypoints[:2], start=1):
            est_dur = 25 + i * 8
            weather_adj = int(est_dur * weather_factor) if weather_factor > 1.0 else None
            fallback.append(Route(
                name=f"Route {i} (preset)",
                description=desc,
                distance_km=0.0,
                duration_min=est_dur,
                duration_in_traffic_min=None,
                via=via.split(",")[0],
                delay_vs_normal_min=i * 8,
                weather_adjusted_duration_min=weather_adj,
                polyline=None,
                is_recommended=(i == 1),
            ))
        return fallback


def get_diversion_summary(plan: DiversionPlan) -> str:
    """One-line summary string for display / LLM context."""
    if not plan.routes:
        return "No diversion routes available."
    best = plan.best_route
    parts = [f"{len(plan.routes)} alternate route(s) identified"]
    if best:
        t = best.weather_adjusted_duration_min or best.duration_in_traffic_min or best.duration_min
        parts.append(f"Recommended: {best.description} (~{t} min)")
        if best.delay_vs_normal_min > 0:
            parts.append(f"+{best.delay_vs_normal_min} min vs normal")
    if plan.weather_context.get("severity", 0) >= 1:
        parts.append(f"Weather: {plan.weather_context.get('condition','adverse')}")
    return " | ".join(parts)
