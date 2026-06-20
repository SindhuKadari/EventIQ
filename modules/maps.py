"""
maps.py — Folium map builder for EventIQ.

Renders:
  - Event location pin (color = risk level)
  - Incident corridor highlight (red dashed line)
  - Diversion routes (green = recommended, yellow = alternate)
  - Nearest police station markers
  - Weather badge on map

Public API:
    build_event_map(event, risk_level, diversion_plan, nearest_ps, weather_ctx)
        -> folium.Map

    build_event_map_html(...)
        -> str  (full HTML string for embedding)
"""

from __future__ import annotations

from typing import Optional

import folium
from folium.plugins import MarkerCluster, MiniMap

# ---------------------------------------------------------------------------
# Risk colour palette (matches risk.py)
# ---------------------------------------------------------------------------
_RISK_COLORS = {
    "Low":      "#2ecc71",
    "Medium":   "#f39c12",
    "High":     "#e74c3c",
    "Critical": "#8e44ad",
}

_RISK_ICONS = {
    "Low":      "info-sign",
    "Medium":   "warning-sign",
    "High":     "fire",
    "Critical": "exclamation-sign",
}

# Route styling
_ROUTE_STYLES = {
    "recommended": {"color": "#27ae60", "weight": 5, "opacity": 0.85, "dashArray": None},
    "alternate":   {"color": "#f39c12", "weight": 4, "opacity": 0.70, "dashArray": "8 4"},
    "blocked":     {"color": "#e74c3c", "weight": 5, "opacity": 0.80, "dashArray": "6 4"},
}

# Police station icon
_PS_ICON_COLOR = "blue"
_PS_ICON = "shield"

# Bangalore bounds
_BLR_CENTER = [12.97, 77.59]
_DEFAULT_ZOOM = 13


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_polyline(encoded: str) -> list[list[float]]:
    """Decode a Google encoded polyline to [[lat, lon], ...] list."""
    try:
        import polyline as _pl
        return [[lat, lon] for lat, lon in _pl.decode(encoded)]
    except Exception:
        return []


def _risk_icon(risk_level: str) -> folium.Icon:
    color_map = {"Low": "green", "Medium": "orange", "High": "red", "Critical": "purple"}
    icon_map = {"Low": "info-sign", "Medium": "warning-sign", "High": "fire", "Critical": "exclamation-sign"}
    return folium.Icon(
        color=color_map.get(risk_level, "blue"),
        icon=icon_map.get(risk_level, "info-sign"),
        prefix="glyphicon",
    )


def _weather_badge_html(weather_ctx: dict) -> str:
    if not weather_ctx:
        return ""
    cond = weather_ctx.get("condition", "")
    temp = weather_ctx.get("temperature_c")
    sev = weather_ctx.get("severity_label", "None")
    sev_color = {"None": "#2ecc71", "Low": "#f39c12", "Moderate": "#e67e22", "Severe": "#e74c3c"}.get(sev, "#7f8c8d")
    temp_str = f"  {temp}°C" if temp is not None else ""
    return f"""
    <div style="
        position: fixed; bottom: 30px; right: 10px; z-index: 1000;
        background: rgba(20,20,35,0.92); color: #ecf0f1;
        padding: 8px 12px; border-radius: 8px; font-size: 12px;
        border-left: 4px solid {sev_color}; font-family: sans-serif;
        box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    ">
        🌤 <b>{cond}</b>{temp_str}<br>
        Traffic impact: <span style="color:{sev_color};font-weight:bold">{sev}</span>
    </div>
    """


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_event_map(
    event: dict,
    risk_level: str = "Medium",
    diversion_plan=None,          # DiversionPlan | None
    nearest_ps: list = None,      # list of dicts from ps_proximity
    weather_ctx: dict = None,
    zoom: int = _DEFAULT_ZOOM,
) -> folium.Map:
    """
    Build and return a fully decorated folium.Map for the given event.

    Args:
        event:         Raw event dict (needs latitude, longitude, corridor, event_cause, address)
        risk_level:    Low / Medium / High / Critical
        diversion_plan: DiversionPlan from diversion_planner (optional)
        nearest_ps:    List of police station dicts from ps_proximity.rank_by_availability()
        weather_ctx:   Dict from weather.get_weather_impact() (optional)
        zoom:          Initial zoom level

    Returns:
        folium.Map
    """
    lat  = float(event.get("latitude")  or _BLR_CENTER[0])
    lon  = float(event.get("longitude") or _BLR_CENTER[1])
    cause    = str(event.get("event_cause")  or "Event")
    corridor = str(event.get("corridor")     or "")
    address  = str(event.get("address")      or f"{lat:.4f}, {lon:.4f}")

    fmap = folium.Map(
        location=[lat, lon],
        zoom_start=zoom,
        tiles="CartoDB dark_matter",
        control_scale=True,
    )

    # ── Mini-map ─────────────────────────────────────────────────────────────
    MiniMap(toggle_display=True, tile_layer="CartoDB dark_matter").add_to(fmap)

    # ── Diversion routes ─────────────────────────────────────────────────────
    if diversion_plan and diversion_plan.routes:
        route_group = folium.FeatureGroup(name="Diversion Routes", show=True)
        for i, route in enumerate(diversion_plan.routes):
            style_key = "recommended" if route.is_recommended else "alternate"
            style = _ROUTE_STYLES[style_key]
            route_label = "✅ Recommended" if route.is_recommended else f"Alt Route {i+1}"
            t = route.weather_adjusted_duration_min or route.duration_in_traffic_min or route.duration_min

            tooltip_html = (
                f"<b>{route_label}</b><br>"
                f"{route.description}<br>"
                f"~{t} min | {route.distance_km} km<br>"
                f"Delay: +{route.delay_vs_normal_min} min"
            )

            if route.polyline:
                coords = _decode_polyline(route.polyline)
                if coords:
                    folium.PolyLine(
                        coords,
                        color=style["color"],
                        weight=style["weight"],
                        opacity=style["opacity"],
                        dash_array=style.get("dashArray"),
                        tooltip=tooltip_html,
                    ).add_to(route_group)
                    continue

            # Fallback: draw straight line origin → via → destination
            end_lat = float(event.get("endlatitude") or lat + 0.05)
            end_lon = float(event.get("endlongitude") or lon)
            folium.PolyLine(
                [[lat, lon], [end_lat, end_lon]],
                color=style["color"],
                weight=style["weight"],
                opacity=style["opacity"],
                dash_array=style.get("dashArray"),
                tooltip=tooltip_html,
            ).add_to(route_group)

        route_group.add_to(fmap)

    # ── Blocked corridor marker (red dashed line from event toward end) ───────
    if event.get("endlatitude") and event.get("endlongitude"):
        end_lat = float(event["endlatitude"])
        end_lon = float(event["endlongitude"])
        if end_lat and end_lon:
            blocked_group = folium.FeatureGroup(name="Blocked Corridor", show=True)
            style = _ROUTE_STYLES["blocked"]
            folium.PolyLine(
                [[lat, lon], [end_lat, end_lon]],
                color=style["color"],
                weight=style["weight"],
                opacity=style["opacity"],
                dash_array=style["dashArray"],
                tooltip=f"⛔ Blocked: {corridor}",
            ).add_to(blocked_group)
            blocked_group.add_to(fmap)

    # ── Police station markers ────────────────────────────────────────────────
    if nearest_ps:
        ps_group = folium.FeatureGroup(name="Police Stations", show=True)
        for ps in nearest_ps[:5]:
            ps_lat = ps.get("lat") or ps.get("latitude")
            ps_lon = ps.get("lon") or ps.get("longitude")
            if not ps_lat or not ps_lon:
                continue
            dist = ps.get("distance_km", 0)
            workload = ps.get("workload_km", 0)
            rank = ps.get("rank", "")
            popup_html = (
                f"<div style='font-family:sans-serif;font-size:12px'>"
                f"<b>🚔 {ps['name']}</b><br>"
                f"Zone: {ps.get('zone','')}<br>"
                f"Distance: {dist:.2f} km<br>"
                f"Workload offset: {workload:.1f} km<br>"
                f"Rank: #{rank}"
                f"</div>"
            )
            folium.Marker(
                location=[ps_lat, ps_lon],
                popup=folium.Popup(popup_html, max_width=200),
                tooltip=f"🚔 {ps['name']} ({dist:.1f} km)",
                icon=folium.Icon(color=_PS_ICON_COLOR, icon="shield", prefix="glyphicon"),
            ).add_to(ps_group)
        ps_group.add_to(fmap)

    # ── Event pin ─────────────────────────────────────────────────────────────
    risk_color_hex = _RISK_COLORS.get(risk_level, "#3498db")
    event_popup_html = (
        f"<div style='font-family:sans-serif;font-size:13px;min-width:200px'>"
        f"<b style='color:{risk_color_hex}'>⚠ {cause.replace('_',' ').title()}</b><br>"
        f"<hr style='margin:4px 0'>"
        f"<b>Corridor:</b> {corridor}<br>"
        f"<b>Address:</b> {address}<br>"
        f"<b>Risk:</b> <span style='color:{risk_color_hex};font-weight:bold'>{risk_level}</span><br>"
    )
    if weather_ctx and weather_ctx.get("condition"):
        event_popup_html += f"<b>Weather:</b> {weather_ctx['condition']}"
        if weather_ctx.get("temperature_c") is not None:
            event_popup_html += f" {weather_ctx['temperature_c']}°C"
        event_popup_html += "<br>"
    event_popup_html += "</div>"

    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(event_popup_html, max_width=260),
        tooltip=f"⚠ {cause.replace('_',' ').title()} — {risk_level}",
        icon=_risk_icon(risk_level),
    ).add_to(fmap)

    # ── Radius circle (visual severity indicator) ────────────────────────────
    radius_m = {"Low": 200, "Medium": 400, "High": 600, "Critical": 900}.get(risk_level, 300)
    folium.Circle(
        location=[lat, lon],
        radius=radius_m,
        color=risk_color_hex,
        fill=True,
        fill_color=risk_color_hex,
        fill_opacity=0.08,
        weight=1.5,
        tooltip=f"{risk_level} impact radius ~{radius_m}m",
    ).add_to(fmap)

    # ── Weather badge (floating HTML) ────────────────────────────────────────
    if weather_ctx:
        badge = _weather_badge_html(weather_ctx)
        if badge:
            fmap.get_root().html.add_child(folium.Element(badge))

    # ── Layer control ─────────────────────────────────────────────────────────
    folium.LayerControl(collapsed=False).add_to(fmap)

    return fmap


def build_event_map_html(
    event: dict,
    risk_level: str = "Medium",
    diversion_plan=None,
    nearest_ps: list = None,
    weather_ctx: dict = None,
    zoom: int = _DEFAULT_ZOOM,
) -> str:
    """Return the map as a full HTML string (for iframe embedding)."""
    fmap = build_event_map(
        event=event,
        risk_level=risk_level,
        diversion_plan=diversion_plan,
        nearest_ps=nearest_ps,
        weather_ctx=weather_ctx,
        zoom=zoom,
    )
    return fmap._repr_html_()
