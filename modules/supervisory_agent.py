"""
supervisory_agent.py — Full pipeline orchestrator for EventIQ.

Takes a raw event dict and runs every module in sequence, returning
a fully populated EventDecision dataclass. Also persists to SQLite.

Usage:
    agent = SupervisoryAgent()
    decision = agent.run(event_dict)
"""

from __future__ import annotations

import time
import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# EventDecision dataclass
# ---------------------------------------------------------------------------

@dataclass
class EventDecision:
    """Complete decision record produced by the supervisory pipeline."""
    event: dict
    event_id: Optional[int]                 # DB row ID (None if not saved)

    # Core ML outputs
    congestion_score: float
    risk_level: str
    risk_metadata: dict
    priority: str
    priority_proba: dict

    # Cascade intelligence
    cascade_prob: float
    cascade_severity: str
    cascade_detail: dict

    # Deployment recommendations
    nearest_ps: list
    resource_plan: object                   # ResourcePlan
    diversion_plan: object                  # DiversionPlan

    # Context data
    historical_profile: dict
    kg_context: dict
    weather_ctx: dict
    weather_forecast: list

    # Forecast & explanation
    timeseries: list
    brief: str
    brief_structured: dict
    score_explanation: str
    context_dict: dict

    # Meta
    processing_time_ms: float
    timestamp: str

    def to_storage_dict(self) -> dict:
        """Flatten for EventStorage.log_event()."""
        ev = self.event
        rp = self.resource_plan
        dp = self.diversion_plan

        import json
        return {
            "event_id":         ev.get("event_id", f"eq-{int(time.time())}"),
            "event_type":       ev.get("event_type", ""),
            "event_cause":      ev.get("event_cause", ""),
            "corridor":         ev.get("corridor", ""),
            "zone":             ev.get("zone", ""),
            "police_station":   ev.get("police_station", ""),
            "lat":              float(ev.get("latitude") or 0),
            "lon":              float(ev.get("longitude") or 0),
            "priority_actual":  ev.get("priority", self.priority),
            "priority_pred":    self.priority,
            "congestion_score": self.congestion_score,
            "risk_level":       self.risk_level,
            "cascade_prob":     self.cascade_prob,
            "cascade_severity": self.cascade_severity,
            "nearest_ps":       json.dumps([p.get("name") for p in self.nearest_ps[:3]]),
            "resource_plan":    json.dumps(rp.to_dict() if rp else {}),
            "diversion_plan":   json.dumps(dp.to_dict() if dp else {}),
            "llm_brief":        self.brief,
            "input_json":       json.dumps(ev),
            "status":           "active",
        }


# ---------------------------------------------------------------------------
# SupervisoryAgent
# ---------------------------------------------------------------------------

class SupervisoryAgent:
    """
    Orchestrates the full EventIQ pipeline for a single event.

    Modules are loaded lazily and cached as instance attributes so the
    agent can be re-used across multiple Streamlit reruns without
    reloading models.
    """

    def __init__(self):
        self._congestion   = None
        self._priority     = None
        self._cascade      = None
        self._resource     = None
        self._diversion    = None
        self._history      = None
        self._kg           = None
        self._storage      = None

    # ── lazy loaders ────────────────────────────────────────────────────────

    def _get_congestion(self):
        if self._congestion is None:
            from modules.congestion_predictor import CongestionPredictor
            self._congestion = CongestionPredictor()
        return self._congestion

    def _get_priority(self):
        if self._priority is None:
            from modules.priority_predictor import PriorityPredictor
            self._priority = PriorityPredictor()
        return self._priority

    def _get_cascade(self):
        if self._cascade is None:
            from modules.cascade_detector import CascadeDetector
            self._cascade = CascadeDetector()
        return self._cascade

    def _get_resource(self):
        if self._resource is None:
            from modules.resource_planner import ResourcePlanner
            self._resource = ResourcePlanner()
        return self._resource

    def _get_diversion(self):
        if self._diversion is None:
            from modules.diversion_planner import DiversionPlanner
            self._diversion = DiversionPlanner()
        return self._diversion

    def _get_history(self):
        if self._history is None:
            from modules.historical_profiles import HistoricalProfiles
            self._history = HistoricalProfiles()
        return self._history

    def _get_kg(self):
        if self._kg is None:
            from modules.knowledge_graph import KnowledgeGraph
            self._kg = KnowledgeGraph()
        return self._kg

    def _get_storage(self):
        if self._storage is None:
            from modules.storage import EventStorage
            self._storage = EventStorage()
        return self._storage

    # ── pipeline ────────────────────────────────────────────────────────────

    def run(
        self,
        event: dict,
        active_events: list = None,
        save: bool = True,
    ) -> EventDecision:
        """
        Run the full EventIQ pipeline for one event.

        Args:
            event:         Raw event dict from UI form
            active_events: Currently active events (for cascade overlap check)
            save:          Whether to persist to SQLite

        Returns:
            EventDecision with all outputs populated
        """
        t0 = time.time()
        active_events = active_events or []
        lat  = float(event.get("latitude")  or 12.97)
        lon  = float(event.get("longitude") or 77.59)

        # ── 1. Congestion score ──────────────────────────────────────────────
        try:
            congestion_score = self._get_congestion().predict(event)
        except Exception:
            congestion_score = 0.0

        # ── 2. Risk level ────────────────────────────────────────────────────
        from modules.risk import get_risk_level, get_risk_metadata
        risk_level    = get_risk_level(congestion_score)
        risk_metadata = get_risk_metadata(congestion_score)

        # ── 3. Priority ──────────────────────────────────────────────────────
        try:
            priority       = self._get_priority().predict_priority(event)
            priority_proba = self._get_priority().predict_priority_proba(event)
        except Exception:
            priority       = event.get("priority", "High")
            priority_proba = {"High": 0.5, "Low": 0.5}

        # ── 4. Cascade risk ──────────────────────────────────────────────────
        try:
            cascade_detail = self._get_cascade().assess_full_cascade_risk(event, active_events)
            cascade_prob   = float(cascade_detail.get("cascade_probability", 0.0))
            cascade_severity = str(cascade_detail.get("severity", "Low"))
        except Exception:
            cascade_prob     = 0.0
            cascade_severity = "Low"
            cascade_detail   = {}

        # ── 5. Nearest police stations ───────────────────────────────────────
        try:
            from modules.ps_proximity import rank_by_availability
            nearest_ps = rank_by_availability(lat, lon, active_events=active_events, top_n=5)
        except Exception:
            nearest_ps = []

        # ── 6. Weather ───────────────────────────────────────────────────────
        try:
            from modules.weather import get_weather_impact, get_forecast
            weather_ctx      = get_weather_impact(lat, lon)
            weather_forecast = get_forecast(lat, lon, hours=6)
        except Exception:
            weather_ctx      = {}
            weather_forecast = []

        # ── 7. Resources ─────────────────────────────────────────────────────
        try:
            resource_plan = self._get_resource().plan(
                event,
                risk_level=risk_level,
                cascade_prob=cascade_prob,
                lat=lat, lon=lon,
                fetch_weather=False,   # already fetched above
            )
            # Apply weather multiplier from our fresh weather_ctx
            if weather_ctx:
                import math
                mult = weather_ctx.get("resource_multiplier", 1.0)
                if mult > 1.0:
                    resource_plan.officers_required   = max(resource_plan.officers_required,
                                                            math.ceil(resource_plan.officers_required * mult))
                    resource_plan.barricades_required = max(resource_plan.barricades_required,
                                                            math.ceil(resource_plan.barricades_required * mult))
                    resource_plan.resource_multiplier = mult
                    if weather_ctx.get("severity", 0) >= 1:
                        from modules.resource_planner import _WEATHER_OFFICER_BOOST
                        boost = _WEATHER_OFFICER_BOOST.get(weather_ctx["severity"])
                        if boost and not resource_plan.weather_boost_applied:
                            resource_plan.officers_required += boost[0]
                            resource_plan.deployment_notes.append(boost[1])
                            resource_plan.weather_boost_applied = True
                        resource_plan.weather_context = weather_ctx
        except Exception:
            resource_plan = None

        # ── 8. Diversion ─────────────────────────────────────────────────────
        try:
            diversion_plan = self._get_diversion().plan_diversions(event, weather_ctx=weather_ctx)
        except Exception:
            diversion_plan = None

        # ── 9. Historical profile ────────────────────────────────────────────
        try:
            corridor = event.get("corridor", "")
            hist     = self._get_history()
            historical_profile = hist.get_corridor_profile(corridor) if corridor else {}
            historical_profile["comparison"] = hist.compare_to_historical(event, congestion_score)
        except Exception:
            historical_profile = {}

        # ── 10. Knowledge graph ──────────────────────────────────────────────
        try:
            kg_context = self._get_kg().get_graph_context(event)
        except Exception:
            kg_context = {}

        # ── 11. Timeseries forecast ──────────────────────────────────────────
        try:
            dur = event.get("incident_duration_minutes")
            duration_hours = int(float(dur) / 60) if dur else None
            timeseries = self._get_congestion().forecast_timeseries(event, duration_hours=duration_hours)
        except Exception:
            timeseries = []

        # ── 12. LLM brief ────────────────────────────────────────────────────
        try:
            from modules.llm_reasoner import build_context_dict, generate_brief, generate_brief_structured, explain_congestion_score
            context_dict = build_context_dict(
                event=event,
                congestion_score=congestion_score,
                risk_level=risk_level,
                priority=priority,
                cascade_prob=cascade_prob,
                cascade_severity=cascade_severity,
                nearest_ps=nearest_ps,
                resource_plan=resource_plan,
                diversion_plan=diversion_plan,
                historical_profile=historical_profile,
                kg_context=kg_context,
                weather_ctx=weather_ctx,
                forecast=weather_forecast,
                timeseries=timeseries,
            )
            brief            = generate_brief(context_dict)
            brief_structured = generate_brief_structured(context_dict)
            score_explanation = explain_congestion_score(context_dict)
        except Exception:
            context_dict      = {}
            brief             = f"**SITUATION**: {event.get('event_cause','Event')} on {event.get('corridor','?')}. Risk: {risk_level}."
            brief_structured  = {}
            score_explanation = f"Score {congestion_score:.1f}/100 — {risk_level} risk."

        processing_time_ms = (time.time() - t0) * 1000
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        decision = EventDecision(
            event=event,
            event_id=None,
            congestion_score=congestion_score,
            risk_level=risk_level,
            risk_metadata=risk_metadata,
            priority=priority,
            priority_proba=priority_proba,
            cascade_prob=cascade_prob,
            cascade_severity=cascade_severity,
            cascade_detail=cascade_detail,
            nearest_ps=nearest_ps,
            resource_plan=resource_plan,
            diversion_plan=diversion_plan,
            historical_profile=historical_profile,
            kg_context=kg_context,
            weather_ctx=weather_ctx,
            weather_forecast=weather_forecast,
            timeseries=timeseries,
            brief=brief,
            brief_structured=brief_structured,
            score_explanation=score_explanation,
            context_dict=context_dict,
            processing_time_ms=round(processing_time_ms, 1),
            timestamp=timestamp,
        )

        # ── 13. Persist ──────────────────────────────────────────────────────
        if save:
            try:
                storage = self._get_storage()
                event_id = storage.log_event(decision.to_storage_dict())
                decision.event_id = event_id
            except Exception:
                pass

        return decision

    def get_active_events(self) -> list:
        """Return active events from storage."""
        try:
            return self._get_storage().get_active_events()
        except Exception:
            return []

    def get_recent_events(self, n: int = 20) -> list:
        """Return recent events from storage."""
        try:
            return self._get_storage().get_recent_events(n)
        except Exception:
            return []

    def get_event_by_id(self, event_id: int):
        """Return a single event record by ID."""
        try:
            return self._get_storage().get_event_by_id(event_id)
        except Exception:
            return None

    def close_event(self, event_id: int) -> None:
        try:
            self._get_storage().set_event_status(event_id, "closed")
        except Exception:
            pass

    def get_kpi_summary(self) -> dict:
        try:
            return self._get_storage().get_kpi_summary()
        except Exception:
            return {}
