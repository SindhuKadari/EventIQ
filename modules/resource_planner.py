"""
resource_planner.py — Rule-based resource recommendation for EventIQ.

NO fake ML. Rules are derived from:
  - Risk level (Low / Medium / High / Critical)
  - Event cause and type (from dataset's 17 causes)
  - Historical corridor + zone profiles (via historical_profiles.py)
  - Weather impact (via weather.py)
  - Road closure flag
  - Vehicle type (heavy vehicles need tow trucks)
  - Cascade probability (extra manpower for cascading risk)

Outputs a ResourcePlan dataclass with:
  - officers_required    int
  - barricades_required  int
  - tow_trucks_required  int
  - ambulances_suggested int
  - diversion_teams      int
  - shift_hours          int
  - deployment_notes     list[str]
  - weather_context      dict
  - resource_multiplier  float  (from weather)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Base resource tables by risk level
# ---------------------------------------------------------------------------
_BASE_RESOURCES = {
    #             officers  barricades  tow  ambulance  div_teams  shift_h
    "Low":       (2,        2,          0,   0,         0,         4),
    "Medium":    (4,        4,          1,   1,         1,         6),
    "High":      (8,        8,          2,   2,         2,         8),
    "Critical":  (14,       16,         3,   3,         3,         12),
}

# Per-cause adjustments (delta officers, delta barricades, delta tow, delta amb, note)
_CAUSE_ADJUSTMENTS = {
    "accident":           (+2, +2, +2, +2, "Accident: extra rescue + tow crew"),
    "vip_movement":       (+4, +4,  0,  0, "VIP: expanded security perimeter"),
    "procession":         (+3, +4,  0,  0, "Procession: crowd management officers"),
    "protest":            (+4, +6,  0,  1, "Protest: riot barriers + medical standby"),
    "public_event":       (+3, +4,  0,  1, "Public event: crowd control + medical"),
    "vehicle_breakdown":  (+0, +1, +2,  0, "Breakdown: tow & lane clearance crew"),
    "construction":       (+1, +4,  0,  0, "Construction: lane separation barriers"),
    "congestion":         (+2, +2,  0,  0, "Congestion: traffic flow officers"),
    "water_logging":      (+1, +2,  0,  1, "Water-logging: drainage team + medical"),
    "tree_fall":          (+1, +2, +1,  0, "Tree-fall: clearance + tow equipment"),
    "pot_holes":          (+0, +2,  0,  0, "Potholes: warning cones + flagmen"),
    "road_conditions":    (+0, +2,  0,  0, "Road conditions: safety barriers"),
    "fog/low visibility": (+1, +2,  0,  0, "Fog: reflective cones + patrol"),
    "debris":             (+0, +2, +1,  0, "Debris: clearance crew"),
    "Debris":             (+0, +2, +1,  0, "Debris: clearance crew"),
    "vip movement":       (+4, +4,  0,  0, "VIP: expanded security perimeter"),
}

# Heavy vehicle types that always get +1 tow
_HEAVY_VEH = {"heavy_vehicle", "truck", "ksrtc_bus", "private_bus", "bmtc_bus"}

# Road closure always adds diversion team + extra barricades
_CLOSURE_ADJUSTMENT = (0, +4, 0, 0, +1, "Road closure: diversion team + extra barricades")

# Cascade probability thresholds → extra officers
_CASCADE_OFFICER_BOOST = [
    (0.80, 4, "High cascade risk: inter-corridor coordination officers"),
    (0.50, 2, "Moderate cascade risk: liaison officers added"),
]

# Weather severity boosts (on top of weather multiplier applied at the end)
_WEATHER_OFFICER_BOOST = {
    1: (1, "Light rain/fog: reflective vests + additional patrol"),
    2: (2, "Moderate adverse weather: extra officers for road safety"),
    3: (4, "Severe weather: emergency response team + additional support"),
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ResourcePlan:
    officers_required: int
    barricades_required: int
    tow_trucks_required: int
    ambulances_suggested: int
    diversion_teams: int
    shift_hours: int
    deployment_notes: list = field(default_factory=list)
    weather_context: dict = field(default_factory=dict)
    resource_multiplier: float = 1.0
    cascade_boost_applied: bool = False
    weather_boost_applied: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def summary(self) -> str:
        parts = [
            f"{self.officers_required} officers",
            f"{self.barricades_required} barricades",
        ]
        if self.tow_trucks_required:
            parts.append(f"{self.tow_trucks_required} tow trucks")
        if self.ambulances_suggested:
            parts.append(f"{self.ambulances_suggested} ambulances")
        if self.diversion_teams:
            parts.append(f"{self.diversion_teams} diversion team(s)")
        parts.append(f"{self.shift_hours}h shift")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class ResourcePlanner:
    """
    Rule-based resource planner.  Accepts an event dict and a set of
    already-computed scores/metadata, returns a ResourcePlan.
    """

    def plan(
        self,
        event: dict,
        risk_level: str = "Medium",
        cascade_prob: float = 0.0,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        fetch_weather: bool = True,
    ) -> ResourcePlan:
        """
        Compute resource recommendation.

        Args:
            event:        Raw event dict (from UI / supervisory agent)
            risk_level:   Low/Medium/High/Critical (from risk.py)
            cascade_prob: 0.0–1.0 (from cascade_detector.py)
            lat/lon:      Coordinates for weather lookup (defaults to event lat/lon)
            fetch_weather: If False, skip weather fetch (useful for tests/offline)

        Returns:
            ResourcePlan
        """
        lat = lat or float(event.get("latitude") or 12.97)
        lon = lon or float(event.get("longitude") or 77.59)
        cause = str(event.get("event_cause") or "").lower()
        veh = str(event.get("veh_type") or "")
        requires_closure = bool(event.get("requires_road_closure", False))

        notes: list[str] = []

        # 1. Base resources from risk level
        base = _BASE_RESOURCES.get(risk_level, _BASE_RESOURCES["Medium"])
        officers, barricades, tow, ambulances, div_teams, shift_h = base
        notes.append(f"Base allocation for {risk_level} risk")

        # 2. Cause-specific adjustments
        cause_key = cause
        adj = _CAUSE_ADJUSTMENTS.get(cause_key)
        if adj is None:
            # Try case-insensitive match
            for k, v in _CAUSE_ADJUSTMENTS.items():
                if k.lower() == cause.lower():
                    adj = v
                    break
        if adj:
            do, db, dt, da, note = adj
            officers   += do
            barricades += db
            tow        += dt
            ambulances += da
            notes.append(note)

        # 3. Heavy vehicle → extra tow
        if veh.lower() in _HEAVY_VEH:
            tow += 1
            notes.append(f"Heavy vehicle ({veh}): +1 tow truck")

        # 4. Road closure
        if requires_closure:
            _, db, _, _, dd, note = _CLOSURE_ADJUSTMENT
            barricades += db
            div_teams  += dd
            notes.append(note)

        # 5. Cascade boost
        cascade_boost = False
        for threshold, extra, note in _CASCADE_OFFICER_BOOST:
            if cascade_prob >= threshold:
                officers += extra
                notes.append(note)
                cascade_boost = True
                break

        # 6. Weather
        weather_ctx: dict = {}
        weather_boost = False
        weather_multiplier = 1.0
        if fetch_weather:
            try:
                from modules.weather import get_weather_impact
                weather_ctx = get_weather_impact(lat, lon)
                sev = weather_ctx.get("severity", 0)
                weather_multiplier = weather_ctx.get("resource_multiplier", 1.0)
                boost = _WEATHER_OFFICER_BOOST.get(sev)
                if boost:
                    extra_off, note = boost
                    officers += extra_off
                    notes.append(note)
                    weather_boost = True
            except Exception:
                pass

        # 7. Apply weather multiplier (ceil to int, never reduce below base)
        import math
        if weather_multiplier > 1.0:
            officers   = max(officers, math.ceil(officers * weather_multiplier))
            barricades = max(barricades, math.ceil(barricades * weather_multiplier))

        # 8. Floor values
        officers   = max(1, officers)
        barricades = max(1, barricades)
        tow        = max(0, tow)
        ambulances = max(0, ambulances)
        div_teams  = max(0, div_teams)

        return ResourcePlan(
            officers_required=officers,
            barricades_required=barricades,
            tow_trucks_required=tow,
            ambulances_suggested=ambulances,
            diversion_teams=div_teams,
            shift_hours=shift_h,
            deployment_notes=notes,
            weather_context=weather_ctx,
            resource_multiplier=weather_multiplier,
            cascade_boost_applied=cascade_boost,
            weather_boost_applied=weather_boost,
        )

    def get_shift_schedule(self, plan: ResourcePlan, start_hour: int = None) -> list:
        """
        Break a ResourcePlan's shift into wave deployments.

        Returns list of dicts: [{wave, start_time, officers, role}]
        """
        import datetime
        if start_hour is None:
            start_hour = datetime.datetime.now().hour

        total = plan.officers_required
        shift_h = plan.shift_hours

        # Wave 1: full deployment immediately
        # Wave 2: 50% relief after half shift
        # Wave 3: 25% standby for overtime if critical
        waves = []
        wave1_off = total
        wave2_off = max(1, total // 2)
        wave2_start = (start_hour + shift_h // 2) % 24

        waves.append({
            "wave": 1,
            "start_time": f"{start_hour:02d}:00",
            "officers": wave1_off,
            "role": "Initial deployment — full strength",
        })
        waves.append({
            "wave": 2,
            "start_time": f"{wave2_start:02d}:00",
            "officers": wave2_off,
            "role": "Relief / rotation team",
        })
        if shift_h >= 8:
            wave3_start = (start_hour + shift_h) % 24
            waves.append({
                "wave": 3,
                "start_time": f"{wave3_start:02d}:00",
                "officers": max(1, total // 4),
                "role": "Overtime standby / demobilisation",
            })
        return waves
