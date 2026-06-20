"""
heatmap.py — Traffic event density heatmap for EventIQ.

Builds a folium HeatMap from:
  1. Historical events in train.csv  (background density)
  2. Live/active events from storage.py  (real-time layer)

Public API:
    build_heatmap(active_events, filters)  -> folium.Map
    build_heatmap_html(...)                -> str
"""

from __future__ import annotations

import os
from typing import Optional

import folium
import numpy as np
import pandas as pd
from folium.plugins import HeatMap, HeatMapWithTime, MiniMap

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)
_TRAIN_CSV = os.path.join(BASE_DIR, "train.csv")

_BLR_CENTER = [12.97, 77.59]

# WMO severity → heatmap intensity modifier (live events get boosted weight)
_WEATHER_INTENSITY_BOOST = {0: 1.0, 1: 1.2, 2: 1.5, 3: 2.0}

# Risk → heat weight
_RISK_WEIGHT = {"Low": 0.3, "Medium": 0.6, "High": 1.0, "Critical": 1.5}

# Cause → base weight (for historical layer)
_CAUSE_WEIGHT: dict[str, float] = {
    "accident":          1.4,
    "protest":           1.2,
    "vip_movement":      1.1,
    "public_event":      1.0,
    "congestion":        0.9,
    "vehicle_breakdown": 0.7,
    "construction":      0.6,
    "water_logging":     0.8,
    "tree_fall":         0.5,
    "procession":        1.0,
}

# ── Cache historical points so CSV is only read once per process ─────────────
_HIST_CACHE: Optional[list] = None


def _load_historical(
    cause_filter: Optional[str] = None,
    corridor_filter: Optional[str] = None,
    hour_filter: Optional[int] = None,
) -> list[list[float]]:
    """
    Load [lat, lon, weight] points from train.csv.
    Returns cached result when no filters applied.
    """
    global _HIST_CACHE

    if cause_filter is None and corridor_filter is None and hour_filter is None:
        if _HIST_CACHE is not None:
            return _HIST_CACHE

    try:
        df = pd.read_csv(_TRAIN_CSV, usecols=[
            "latitude", "longitude", "event_cause", "corridor",
            "start_datetime", "requires_road_closure",
        ])
    except Exception:
        return []

    df = df.dropna(subset=["latitude", "longitude"])
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])

    # Bangalore bounding box (rough)
    df = df[(df["latitude"].between(12.7, 13.2)) & (df["longitude"].between(77.3, 77.9))]

    # Optional filters
    if cause_filter:
        df = df[df["event_cause"].str.lower() == cause_filter.lower()]
    if corridor_filter:
        df = df[df["corridor"].str.lower() == corridor_filter.lower()]
    if hour_filter is not None:
        try:
            df["_hour"] = pd.to_datetime(
                df["start_datetime"], format="mixed", utc=True, errors="coerce"
            ).dt.hour
            df = df[df["_hour"] == hour_filter]
        except Exception:
            pass

    # Assign weight per cause
    def _w(row):
        cause = str(row.get("event_cause", "")).lower()
        base = _CAUSE_WEIGHT.get(cause, 0.5)
        closure = 1.3 if row.get("requires_road_closure") else 1.0
        return round(base * closure, 2)

    points = [
        [float(row["latitude"]), float(row["longitude"]), _w(row)]
        for _, row in df.iterrows()
    ]

    if cause_filter is None and corridor_filter is None and hour_filter is None:
        _HIST_CACHE = points

    return points


def _live_points(active_events: list, weather_intensity: float = 1.0) -> list[list[float]]:
    """Convert active events (from storage.py) to heatmap [lat, lon, weight] list."""
    points = []
    for ev in active_events:
        try:
            lat = float(ev.get("lat") or ev.get("latitude") or 0)
            lon = float(ev.get("lon") or ev.get("longitude") or 0)
            if not lat or not lon:
                continue
            risk = str(ev.get("risk_level") or "Medium")
            base_w = _RISK_WEIGHT.get(risk, 0.6)
            points.append([lat, lon, round(base_w * weather_intensity * 2.5, 2)])
        except Exception:
            continue
    return points


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_heatmap(
    active_events: list = None,
    cause_filter: Optional[str] = None,
    corridor_filter: Optional[str] = None,
    hour_filter: Optional[int] = None,
    weather_ctx: Optional[dict] = None,
    show_historical: bool = True,
    show_live: bool = True,
    zoom: int = 11,
) -> folium.Map:
    """
    Build a traffic density heatmap combining historical and live events.

    Args:
        active_events:    List of active event dicts from storage.get_active_events()
        cause_filter:     Filter historical events to this cause (or None for all)
        corridor_filter:  Filter historical events to this corridor (or None for all)
        hour_filter:      Filter to events during this hour 0-23 (or None for all)
        weather_ctx:      Dict from weather.get_weather_impact() — boosts live intensity
        show_historical:  Whether to include the historical background layer
        show_live:        Whether to include the live events layer
        zoom:             Initial zoom level

    Returns:
        folium.Map
    """
    fmap = folium.Map(
        location=_BLR_CENTER,
        zoom_start=zoom,
        tiles="CartoDB dark_matter",
        control_scale=True,
    )

    MiniMap(toggle_display=True, tile_layer="CartoDB dark_matter").add_to(fmap)

    weather_intensity = 1.0
    if weather_ctx:
        sev = weather_ctx.get("severity", 0)
        weather_intensity = _WEATHER_INTENSITY_BOOST.get(sev, 1.0)

    # ── Historical layer ──────────────────────────────────────────────────────
    if show_historical:
        hist_points = _load_historical(cause_filter, corridor_filter, hour_filter)
        if hist_points:
            HeatMap(
                hist_points,
                name="Historical Events",
                min_opacity=0.25,
                max_zoom=16,
                radius=18,
                blur=15,
                gradient={
                    "0.2": "#2ecc71",
                    "0.4": "#f1c40f",
                    "0.6": "#e67e22",
                    "0.8": "#e74c3c",
                    "1.0": "#8e44ad",
                },
            ).add_to(fmap)

    # ── Live / active events layer ────────────────────────────────────────────
    if show_live and active_events:
        live_points = _live_points(active_events, weather_intensity)
        if live_points:
            HeatMap(
                live_points,
                name="Live Active Events",
                min_opacity=0.5,
                max_zoom=18,
                radius=25,
                blur=12,
                gradient={
                    "0.3": "#3498db",
                    "0.6": "#e67e22",
                    "1.0": "#e74c3c",
                },
            ).add_to(fmap)

        # Add markers for live events
        live_group = folium.FeatureGroup(name="Live Event Pins", show=True)
        for ev in (active_events or []):
            try:
                lat = float(ev.get("lat") or ev.get("latitude") or 0)
                lon = float(ev.get("lon") or ev.get("longitude") or 0)
                if not lat or not lon:
                    continue
                risk     = str(ev.get("risk_level") or "Medium")
                cause    = str(ev.get("event_type") or ev.get("event_cause") or "Event")
                corridor = str(ev.get("corridor") or "")
                color_map = {"Low": "green", "Medium": "orange", "High": "red", "Critical": "purple"}
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=8,
                    color=color_map.get(risk, "blue"),
                    fill=True,
                    fill_color=color_map.get(risk, "blue"),
                    fill_opacity=0.8,
                    tooltip=f"🔴 LIVE: {cause} | {corridor} | {risk}",
                ).add_to(live_group)
            except Exception:
                continue
        live_group.add_to(fmap)

    # ── Weather badge ─────────────────────────────────────────────────────────
    if weather_ctx and weather_ctx.get("condition"):
        cond = weather_ctx.get("condition", "")
        temp = weather_ctx.get("temperature_c")
        sev  = weather_ctx.get("severity_label", "None")
        sev_color = {"None": "#2ecc71", "Low": "#f39c12", "Moderate": "#e67e22", "Severe": "#e74c3c"}.get(sev, "#7f8c8d")
        temp_str = f"  {temp}°C" if temp is not None else ""
        badge_html = f"""
        <div style="
            position: fixed; bottom: 30px; right: 10px; z-index: 1000;
            background: rgba(20,20,35,0.92); color: #ecf0f1;
            padding: 8px 12px; border-radius: 8px; font-size: 12px;
            border-left: 4px solid {sev_color}; font-family: sans-serif;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
        ">
            🌤 <b>{cond}</b>{temp_str}<br>
            Heat intensity boost: <span style="color:{sev_color};font-weight:bold">×{weather_intensity:.1f}</span>
        </div>
        """
        fmap.get_root().html.add_child(folium.Element(badge_html))

    # ── Stats legend ──────────────────────────────────────────────────────────
    n_hist = len(_load_historical(cause_filter, corridor_filter, hour_filter)) if show_historical else 0
    n_live = len(active_events or [])
    title_parts = []
    if cause_filter:
        title_parts.append(f"Cause: {cause_filter}")
    if corridor_filter:
        title_parts.append(f"Corridor: {corridor_filter}")
    if hour_filter is not None:
        title_parts.append(f"Hour: {hour_filter:02d}:00")
    filter_str = " | ".join(title_parts) if title_parts else "All events"
    legend_html = f"""
    <div style="
        position: fixed; top: 10px; left: 50px; z-index: 1000;
        background: rgba(20,20,35,0.88); color: #ecf0f1;
        padding: 8px 14px; border-radius: 8px; font-size: 12px;
        border-left: 4px solid #3498db; font-family: sans-serif;
    ">
        📊 <b>EventIQ Traffic Heatmap</b><br>
        {filter_str}<br>
        Historical: {n_hist:,} pts &nbsp;|&nbsp; Live: {n_live} event(s)
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def build_heatmap_html(
    active_events: list = None,
    cause_filter: Optional[str] = None,
    corridor_filter: Optional[str] = None,
    hour_filter: Optional[int] = None,
    weather_ctx: Optional[dict] = None,
    show_historical: bool = True,
    show_live: bool = True,
) -> str:
    """Return the heatmap as a full HTML string."""
    fmap = build_heatmap(
        active_events=active_events,
        cause_filter=cause_filter,
        corridor_filter=corridor_filter,
        hour_filter=hour_filter,
        weather_ctx=weather_ctx,
        show_historical=show_historical,
        show_live=show_live,
    )
    return fmap._repr_html_()


def get_hotspot_corridors(top_n: int = 5) -> list[dict]:
    """
    Return the top-N highest density corridors from historical data.
    Used for the heatmap sidebar summary.
    """
    try:
        df = pd.read_csv(_TRAIN_CSV, usecols=["corridor", "latitude", "longitude", "event_cause"])
        df = df.dropna(subset=["corridor"])
        counts = df.groupby("corridor").size().sort_values(ascending=False).head(top_n)
        result = []
        for corridor, count in counts.items():
            c_df = df[df["corridor"] == corridor]
            top_cause = c_df["event_cause"].mode()
            result.append({
                "corridor": corridor,
                "event_count": int(count),
                "top_cause": str(top_cause.iloc[0]) if len(top_cause) else "unknown",
            })
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Hexagonal Heatmap
# ---------------------------------------------------------------------------

def _hex_vertices(center_lat: float, center_lon: float,
                  size_lat: float, size_lon: float) -> list[tuple]:
    """Return 6 (lat, lon) vertices for a flat-top hexagon."""
    import math
    verts = []
    for i in range(6):
        angle = math.radians(60 * i)
        verts.append((
            center_lat + size_lat * math.sin(angle),
            center_lon + size_lon * math.cos(angle),
        ))
    verts.append(verts[0])  # close
    return verts


def _intensity_color(intensity: float) -> tuple[str, str]:
    """Return (fill_color, stroke_color) for a 0-1 intensity value."""
    if intensity < 0.15:
        return "rgba(46,204,113,0.55)", "#2ecc71"
    elif intensity < 0.30:
        return "rgba(241,196,15,0.60)", "#f1c40f"
    elif intensity < 0.55:
        return "rgba(230,126,34,0.70)", "#e67e22"
    elif intensity < 0.80:
        return "rgba(231,76,60,0.78)", "#e74c3c"
    else:
        return "rgba(142,68,173,0.88)", "#8e44ad"


def build_hex_heatmap(
    active_events: list = None,
    cause_filter: Optional[str] = None,
    hour_filter: Optional[int] = None,
    weather_ctx: Optional[dict] = None,
    n_cols: int = 32,
    zoom: int = 11,
) -> folium.Map:
    """
    Build a hexagonal bin heatmap of Bangalore traffic density.

    Each hexagonal cell is coloured by event density:
      Green → Yellow → Orange → Red → Purple  (Low → Critical)

    Args:
        active_events:  Live events list (from storage)
        cause_filter:   Restrict historical events to this cause
        hour_filter:    Restrict historical events to this hour 0–23
        weather_ctx:    Weather dict — used for badge overlay
        n_cols:         Number of hex columns across the city (resolution)
        zoom:           Initial folium zoom level

    Returns:
        folium.Map with hexagonal polygon layer + live pins + legend
    """
    import math

    fmap = folium.Map(
        location=_BLR_CENTER,
        zoom_start=zoom,
        tiles="CartoDB dark_matter",
        control_scale=True,
    )
    MiniMap(toggle_display=True, tile_layer="CartoDB dark_matter").add_to(fmap)

    # ── Load points ───────────────────────────────────────────────────────────
    hist_points = _load_historical(cause_filter, None, hour_filter)
    weather_intensity = 1.0
    if weather_ctx:
        sev = weather_ctx.get("severity", 0)
        weather_intensity = _WEATHER_INTENSITY_BOOST.get(sev, 1.0)
    live_points = _live_points(active_events or [], weather_intensity)
    all_points = hist_points + live_points

    if not all_points:
        # Empty map placeholder
        folium.Marker(_BLR_CENTER, tooltip="No data available").add_to(fmap)
        return fmap

    # ── Hex geometry ──────────────────────────────────────────────────────────
    lat_min, lat_max = 12.82, 13.08
    lon_min, lon_max = 77.45, 77.78

    lat_scale = math.cos(math.radians(12.97))   # ~0.974 at Bangalore
    hex_w = (lon_max - lon_min) / n_cols        # column width in degrees lon
    hex_h = hex_w / lat_scale                   # equivalent height in degrees lat
    row_h = hex_h * math.sqrt(3) / 2            # vertical row spacing

    # ── Bin points into hex grid ──────────────────────────────────────────────
    bins: dict[tuple, float] = {}
    for lat, lon, w in all_points:
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            continue
        col = int((lon - lon_min) / hex_w)
        row_offset_lat = (hex_h * 0.5) if (col % 2) else 0.0
        row = int((lat - lat_min - row_offset_lat) / row_h)
        key = (col, row)
        bins[key] = bins.get(key, 0.0) + w

    if not bins:
        return fmap

    max_count = max(bins.values())

    # ── Draw hexagonal polygons ───────────────────────────────────────────────
    hex_group = folium.FeatureGroup(name="Hex Density Grid", show=True)
    size_lon = hex_w * 0.52          # slight shrink for visible gap between hexes
    size_lat = size_lon / lat_scale

    for (col, row), count in bins.items():
        center_lon = lon_min + col * hex_w + hex_w * 0.5
        row_offset_lat = (hex_h * 0.5) if (col % 2) else 0.0
        center_lat = lat_min + row * row_h + row_h * 0.5 + row_offset_lat

        intensity = count / max_count
        fill_color, stroke_color = _intensity_color(intensity)
        pct = f"{intensity * 100:.0f}%"
        events_label = f"{count:.1f}"
        tooltip_text = (
            f"Density: {events_label} event-units  |  Intensity: {pct}"
            + (f"  |  Cause: {cause_filter}" if cause_filter else "")
        )

        verts = _hex_vertices(center_lat, center_lon, size_lat, size_lon)
        folium.Polygon(
            locations=verts,
            fill=True,
            fill_color=fill_color,
            color=stroke_color,
            weight=0.6,
            fill_opacity=0.72,
            tooltip=tooltip_text,
        ).add_to(hex_group)

    hex_group.add_to(fmap)

    # ── Live event pins on top ────────────────────────────────────────────────
    if active_events:
        pin_group = folium.FeatureGroup(name="Live Event Pins", show=True)
        color_map = {"Low": "green", "Medium": "orange", "High": "red", "Critical": "purple"}
        for ev in active_events:
            try:
                lat = float(ev.get("lat") or ev.get("latitude") or 0)
                lon = float(ev.get("lon") or ev.get("longitude") or 0)
                if not lat or not lon:
                    continue
                risk  = str(ev.get("risk_level") or "Medium")
                cause = str(ev.get("event_type") or ev.get("event_cause") or "Event")
                corr  = str(ev.get("corridor") or "")
                folium.CircleMarker(
                    location=[lat, lon], radius=9,
                    color=color_map.get(risk, "blue"),
                    fill=True, fill_color=color_map.get(risk, "blue"),
                    fill_opacity=0.9, weight=2,
                    tooltip=f"🔴 LIVE: {cause} | {corr} | {risk}",
                ).add_to(pin_group)
            except Exception:
                continue
        pin_group.add_to(fmap)

    # ── Weather badge ─────────────────────────────────────────────────────────
    if weather_ctx and weather_ctx.get("condition"):
        cond = weather_ctx.get("condition", "")
        temp = weather_ctx.get("temperature_c")
        sev_label = weather_ctx.get("severity_label", "None")
        sev_color = {"None": "#2ecc71", "Low": "#f39c12", "Moderate": "#e67e22", "Severe": "#e74c3c"}.get(sev_label, "#7f8c8d")
        temp_str = f"  {temp}°C" if temp is not None else ""
        badge_html = f"""
        <div style="
            position: fixed; bottom: 30px; right: 10px; z-index: 1000;
            background: rgba(13,17,23,0.93); color: #ecf0f1;
            padding: 8px 12px; border-radius: 8px; font-size: 12px;
            border-left: 4px solid {sev_color}; font-family: sans-serif;
            box-shadow: 0 2px 8px rgba(0,0,0,0.5);">
            🌤 <b>{cond}</b>{temp_str}<br>
            Weather: <span style="color:{sev_color};font-weight:bold">{sev_label}</span>
            &nbsp; ×{weather_intensity:.1f} boost
        </div>"""
        fmap.get_root().html.add_child(folium.Element(badge_html))

    # ── Map legend ────────────────────────────────────────────────────────────
    n_hist = len(hist_points)
    n_live = len(active_events or [])
    filter_parts = []
    if cause_filter:
        filter_parts.append(f"Cause: {cause_filter}")
    if hour_filter is not None:
        filter_parts.append(f"Hour: {hour_filter:02d}:00")
    filter_str = " | ".join(filter_parts) if filter_parts else "All events"

    legend_html = """
    <div style="
        position: fixed; top: 10px; left: 50px; z-index: 1000;
        background: rgba(13,17,23,0.92); color: #ecf0f1;
        padding: 10px 14px; border-radius: 8px; font-size: 12px;
        border-left: 4px solid #58a6ff; font-family: sans-serif;
        box-shadow: 0 2px 8px rgba(0,0,0,0.5);">
        <b>⬡ EventIQ Hex Heatmap</b><br>
        <span style="color:#8b949e">""" + filter_str + f"""</span><br>
        Historical: {n_hist:,} pts &nbsp;|&nbsp; Live: {n_live} event(s)
        <br><br>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px">
            <span style="font-size:11px;color:#8b949e">Density:</span>
            <span style="background:rgba(46,204,113,0.5);padding:1px 7px;border-radius:4px;font-size:11px">Low</span>
            <span style="background:rgba(241,196,15,0.55);padding:1px 7px;border-radius:4px;font-size:11px">Moderate</span>
            <span style="background:rgba(230,126,34,0.65);padding:1px 7px;border-radius:4px;font-size:11px">High</span>
            <span style="background:rgba(231,76,60,0.75);padding:1px 7px;border-radius:4px;font-size:11px">Severe</span>
            <span style="background:rgba(142,68,173,0.85);padding:1px 7px;border-radius:4px;font-size:11px">Critical</span>
        </div>
    </div>"""
    fmap.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def build_hex_heatmap_html(
    active_events: list = None,
    cause_filter: Optional[str] = None,
    hour_filter: Optional[int] = None,
    weather_ctx: Optional[dict] = None,
    n_cols: int = 32,
) -> str:
    """Return the hexagonal heatmap as a full HTML string."""
    fmap = build_hex_heatmap(
        active_events=active_events,
        cause_filter=cause_filter,
        hour_filter=hour_filter,
        weather_ctx=weather_ctx,
        n_cols=n_cols,
    )
    return fmap._repr_html_()
