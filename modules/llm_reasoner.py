"""
llm_reasoner.py — Gemini-powered operational brief generator for EventIQ.

Takes a fully assembled event context (scores, risk, history, KG facts,
weather, resources, diversions) and produces a structured operational brief
for the traffic command supervisor.

Public API:
    generate_brief(context_dict)         -> str   (markdown brief)
    generate_brief_structured(ctx)       -> dict  (parsed sections)
    summarise_feedback_trends(trends)    -> str   (learning summary)
    explain_congestion_score(ctx)        -> str   (plain-English explanation)
"""

from __future__ import annotations

import os
import textwrap
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_MODEL_NAME = "gemini-2.0-flash"   # fast + free tier

# ── Lazy import so app starts even without the key ───────────────────────────
_genai = None
_model = None


def _get_model():
    global _genai, _model
    if _model is not None:
        return _model
    if not _GEMINI_KEY:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=_GEMINI_KEY)
        _genai = genai
        _model = genai.GenerativeModel(_MODEL_NAME)
        return _model
    except Exception:
        return None


def _call_gemini(prompt: str, temperature: float = 0.35) -> Optional[str]:
    """Send a prompt to Gemini, return text or None on failure."""
    model = _get_model()
    if model is None:
        return None
    try:
        cfg = _genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=900,
        )
        resp = model.generate_content(prompt, generation_config=cfg)
        return resp.text.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context_dict(
    event: dict,
    congestion_score: float,
    risk_level: str,
    priority: str,
    cascade_prob: float,
    cascade_severity: str,
    nearest_ps: list,
    resource_plan,              # ResourcePlan dataclass
    diversion_plan,             # DiversionPlan dataclass
    historical_profile: dict,
    kg_context: dict,
    weather_ctx: dict,
    forecast: list = None,
    timeseries: list = None,
) -> dict:
    """
    Assemble all EventIQ outputs into a single context dict for the LLM.
    This is also the object stored in the database as the full decision record.
    """
    return {
        "event": event,
        "congestion_score": round(congestion_score, 1),
        "risk_level": risk_level,
        "priority": priority,
        "cascade_prob": round(cascade_prob, 3),
        "cascade_severity": cascade_severity,
        "nearest_ps": nearest_ps[:3] if nearest_ps else [],
        "resource_plan": resource_plan.to_dict() if resource_plan else {},
        "diversion_plan": diversion_plan.to_dict() if diversion_plan else {},
        "historical_profile": historical_profile,
        "kg_context": kg_context,
        "weather": weather_ctx,
        "forecast": (forecast or [])[:4],
        "timeseries": (timeseries or [])[:6],
    }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _brief_prompt(ctx: dict) -> str:
    ev  = ctx["event"]
    rp  = ctx.get("resource_plan", {})
    dp  = ctx.get("diversion_plan", {})
    hp  = ctx.get("historical_profile", {})
    kg  = ctx.get("kg_context", {})
    wx  = ctx.get("weather", {})
    fc  = ctx.get("forecast", [])

    cause    = str(ev.get("event_cause", "")).replace("_", " ").title()
    corridor = ev.get("corridor", "Unknown corridor")
    zone     = ev.get("zone", "")
    veh      = ev.get("veh_type", "")
    closure  = "YES — road closed" if ev.get("requires_road_closure") else "No closure"
    address  = ev.get("address", "")

    risk      = ctx["risk_level"]
    score     = ctx["congestion_score"]
    priority  = ctx["priority"]
    cascade   = ctx["cascade_prob"]
    casc_sev  = ctx["cascade_severity"]

    # Police stations
    ps_lines = ""
    for ps in ctx.get("nearest_ps", []):
        ps_lines += f"  • {ps.get('name','?')} — {ps.get('distance_km',0):.1f} km\n"

    # Resources
    officers  = rp.get("officers_required", "?")
    barricades = rp.get("barricades_required", "?")
    tow       = rp.get("tow_trucks_required", 0)
    amb       = rp.get("ambulances_suggested", 0)
    shift     = rp.get("shift_hours", "?")
    rp_notes  = "; ".join(rp.get("deployment_notes", [])[:3])

    # Diversions
    best_route = ""
    dp_routes  = dp.get("routes", [])
    if dp_routes:
        r = dp_routes[0]
        t = r.get("weather_adjusted_duration_min") or r.get("duration_in_traffic_min") or r.get("duration_min", "?")
        best_route = f"{r.get('description','?')} (~{t} min)"

    # Historical
    hist_count   = hp.get("total_events", hp.get("count", "?"))
    hist_closure = hp.get("closure_rate", hp.get("road_closure_rate", "?"))
    hist_repeat  = hp.get("repeat_rate", "?")

    # KG escalation
    escalations = kg.get("escalation_chains", kg.get("escalation", []))
    esc_str = ", ".join(escalations[:3]) if escalations else "none"

    # Weather
    wx_cond = wx.get("condition", "Unknown")
    wx_temp = f"{wx.get('temperature_c','?')}°C" if wx.get("temperature_c") is not None else ""
    wx_sev  = wx.get("severity_label", "None")
    wx_rain = f"{wx.get('precipitation_mm',0)} mm rain" if wx.get("precipitation_mm", 0) > 0 else "no precipitation"

    # Forecast snippet
    fc_str = ""
    if fc:
        fc_str = "Next hours: " + ", ".join(
            f"{f.get('hour_label','?')} {f.get('condition','?')[:10]}" for f in fc[:3]
        )

    prompt = textwrap.dedent(f"""
    You are EventIQ, an AI traffic supervisory assistant for Bangalore Traffic Police.
    Generate a CONCISE operational brief (≤250 words) for the duty officer.
    Use clear sections. Be direct and actionable. Do NOT repeat information.

    ── INCIDENT ────────────────────────────────────────────────────────────
    Cause       : {cause}
    Location    : {address or corridor}  |  Corridor: {corridor}  |  Zone: {zone}
    Vehicle     : {veh}   |  Road closure: {closure}
    Priority    : {priority}   |  Risk: {risk}   |  Congestion score: {score}/100

    ── INTELLIGENCE ────────────────────────────────────────────────────────
    Cascade risk: {casc_sev} ({cascade*100:.0f}%)  |  Escalation paths: {esc_str}
    Historical ({corridor}): {hist_count} past events, closure rate {hist_closure}, repeat rate {hist_repeat}

    ── WEATHER ─────────────────────────────────────────────────────────────
    Current: {wx_cond} {wx_temp}  |  Precipitation: {wx_rain}  |  Traffic impact: {wx_sev}
    {fc_str}

    ── NEAREST POLICE STATIONS ─────────────────────────────────────────────
    {ps_lines.strip() or "No PS data available"}

    ── RESOURCE PLAN ───────────────────────────────────────────────────────
    Officers: {officers}  |  Barricades: {barricades}  |  Tow: {tow}  |  Ambulances: {amb}
    Shift: {shift}h  |  Notes: {rp_notes}

    ── BEST DIVERSION ──────────────────────────────────────────────────────
    {best_route or "No diversion computed"}

    ── GENERATE BRIEF ──────────────────────────────────────────────────────
    Structure your response EXACTLY as:
    **SITUATION**: One sentence.
    **IMMEDIATE ACTIONS** (numbered list, ≤4 items):
    **RESOURCE DEPLOYMENT**: One sentence with exact numbers.
    **DIVERSION**: One sentence.
    **WEATHER ADVISORY**: One sentence (skip if no weather impact).
    **WATCH POINTS**: Up to 2 key risks to monitor.
    """).strip()

    return prompt


def _score_explanation_prompt(ctx: dict) -> str:
    ev    = ctx["event"]
    score = ctx["congestion_score"]
    risk  = ctx["risk_level"]
    cause = str(ev.get("event_cause", "")).replace("_", " ").title()
    hp    = ctx.get("historical_profile", {})
    rp    = ctx.get("resource_plan", {})
    wx    = ctx.get("weather", {})

    prompt = textwrap.dedent(f"""
    You are EventIQ. Explain in 2-3 plain-English sentences WHY this traffic event
    received a congestion score of {score}/100 (risk: {risk}).

    Event: {cause} on {ev.get('corridor','?')}, zone {ev.get('zone','?')}.
    Road closure: {ev.get('requires_road_closure', False)}.
    Vehicle: {ev.get('veh_type','?')}.
    Historical avg events on this corridor: {hp.get('total_events', hp.get('count','?'))}.
    Weather impact: {wx.get('severity_label','None')} ({wx.get('condition','?')}).
    Resource multiplier applied: {rp.get('resource_multiplier', 1.0)}.

    Keep the explanation under 80 words. No bullet points.
    """).strip()
    return prompt


def _feedback_trends_prompt(trends: dict) -> str:
    total   = trends.get("total_feedback", 0)
    correct = trends.get("priority_accuracy_pct", 0)
    score_delta = trends.get("avg_congestion_delta", 0)
    top_wrong = trends.get("top_corridors_wrong", [])[:3]
    top_right = trends.get("top_corridors_correct", [])[:3]
    weather_miss = trends.get("weather_miss_rate_pct", 0)

    prompt = textwrap.dedent(f"""
    You are EventIQ. Based on the following post-event feedback statistics,
    write a 3-4 sentence learning summary for the command supervisor.
    Be specific, constructive, and mention what to watch for.

    Feedback records: {total}
    Priority prediction accuracy: {correct:.1f}%
    Average congestion score delta (predicted vs actual): {score_delta:+.1f} points
    Corridors with most wrong predictions: {', '.join(top_wrong) or 'none'}
    Corridors with best accuracy: {', '.join(top_right) or 'none'}
    Weather-related misses: {weather_miss:.1f}% of errors

    Keep it under 100 words. No headers.
    """).strip()
    return prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_brief(context_dict: dict) -> str:
    """
    Generate an operational brief from the assembled context dict.
    Falls back to a rule-based brief if Gemini is unavailable.

    Returns:
        Markdown-formatted brief string.
    """
    prompt = _brief_prompt(context_dict)
    result = _call_gemini(prompt)
    if result:
        return result
    # ── Fallback: structured rule-based brief ─────────────────────────────
    return _fallback_brief(context_dict)


def generate_brief_structured(context_dict: dict) -> dict:
    """
    Returns the brief as a dict with keys:
    situation, immediate_actions, resource_deployment, diversion,
    weather_advisory, watch_points, raw_text
    """
    raw = generate_brief(context_dict)
    sections = {
        "situation": "",
        "immediate_actions": [],
        "resource_deployment": "",
        "diversion": "",
        "weather_advisory": "",
        "watch_points": [],
        "raw_text": raw,
    }
    current_key = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("**SITUATION**"):
            current_key = "situation"
            sections["situation"] = stripped.replace("**SITUATION**:", "").replace("**SITUATION**", "").strip()
        elif stripped.startswith("**IMMEDIATE ACTIONS**"):
            current_key = "immediate_actions"
        elif stripped.startswith("**RESOURCE DEPLOYMENT**"):
            current_key = "resource_deployment"
            sections["resource_deployment"] = stripped.replace("**RESOURCE DEPLOYMENT**:", "").strip()
        elif stripped.startswith("**DIVERSION**"):
            current_key = "diversion"
            sections["diversion"] = stripped.replace("**DIVERSION**:", "").strip()
        elif stripped.startswith("**WEATHER ADVISORY**"):
            current_key = "weather_advisory"
            sections["weather_advisory"] = stripped.replace("**WEATHER ADVISORY**:", "").strip()
        elif stripped.startswith("**WATCH POINTS**"):
            current_key = "watch_points"
        elif stripped and current_key == "immediate_actions":
            clean = stripped.lstrip("0123456789.-) ").strip()
            if clean:
                sections["immediate_actions"].append(clean)
        elif stripped and current_key == "watch_points":
            clean = stripped.lstrip("•*-").strip()
            if clean:
                sections["watch_points"].append(clean)
        elif stripped and current_key in ("situation", "resource_deployment", "diversion", "weather_advisory"):
            if not sections[current_key]:
                sections[current_key] = stripped
    return sections


def explain_congestion_score(context_dict: dict) -> str:
    """Plain-English explanation of why the score is what it is."""
    prompt = _score_explanation_prompt(context_dict)
    result = _call_gemini(prompt, temperature=0.25)
    if result:
        return result
    # Fallback
    score = context_dict.get("congestion_score", 0)
    risk  = context_dict.get("risk_level", "?")
    ev    = context_dict.get("event", {})
    cause = str(ev.get("event_cause", "")).replace("_", " ")
    return (
        f"The congestion score of {score}/100 ({risk} risk) reflects "
        f"a {cause} event with "
        f"{'road closure, ' if ev.get('requires_road_closure') else ''}"
        f"{ev.get('veh_type','unknown')} vehicle involvement on {ev.get('corridor','?')}."
    )


def summarise_feedback_trends(trends: dict) -> str:
    """Gemini-powered feedback learning summary."""
    if not trends.get("total_feedback", 0):
        return "No feedback data available yet."
    prompt = _feedback_trends_prompt(trends)
    result = _call_gemini(prompt, temperature=0.3)
    return result or _fallback_feedback_summary(trends)


# ---------------------------------------------------------------------------
# Rule-based fallbacks (when Gemini is offline / no API key)
# ---------------------------------------------------------------------------

def _fallback_brief(ctx: dict) -> str:
    ev   = ctx["event"]
    rp   = ctx.get("resource_plan", {})
    dp   = ctx.get("diversion_plan", {})
    risk = ctx["risk_level"]
    cause = str(ev.get("event_cause", "event")).replace("_", " ").title()
    corridor = ev.get("corridor", "unknown corridor")
    officers  = rp.get("officers_required", "?")
    barricades = rp.get("barricades_required", "?")
    tow       = rp.get("tow_trucks_required", 0)
    amb       = rp.get("ambulances_suggested", 0)

    routes = dp.get("routes", [])
    diversion_str = "No diversion data."
    if routes:
        r = routes[0]
        t = r.get("weather_adjusted_duration_min") or r.get("duration_min", "?")
        diversion_str = f"Recommended: {r.get('description','?')} (~{t} min)"

    wx   = ctx.get("weather", {})
    wx_note = ""
    if wx.get("severity", 0) >= 1:
        wx_note = f"\n**WEATHER ADVISORY**: {wx.get('condition','Adverse weather')} — monitor road conditions."

    return (
        f"**SITUATION**: {cause} reported on {corridor}. Risk level: {risk}.\n\n"
        f"**IMMEDIATE ACTIONS**:\n"
        f"1. Deploy {officers} officers to {ev.get('address', corridor)}.\n"
        f"2. Set up {barricades} barricades at incident perimeter.\n"
        f"{'3. Dispatch ' + str(tow) + ' tow truck(s) for vehicle clearance.' + chr(10) if tow else ''}"
        f"{'4. Station ' + str(amb) + ' ambulance(s) on standby.' + chr(10) if amb else ''}\n"
        f"**RESOURCE DEPLOYMENT**: {officers} officers, {barricades} barricades"
        f"{', ' + str(tow) + ' tow truck(s)' if tow else ''}"
        f"{', ' + str(amb) + ' ambulance(s)' if amb else ''}.\n\n"
        f"**DIVERSION**: {diversion_str}\n"
        f"{wx_note}\n"
        f"**WATCH POINTS**: Monitor cascade spread to adjacent corridors. Update status every 30 minutes."
    )


def _fallback_feedback_summary(trends: dict) -> str:
    total   = trends.get("total_feedback", 0)
    correct = trends.get("priority_accuracy_pct", 0)
    delta   = trends.get("avg_congestion_delta", 0)
    return (
        f"Based on {total} feedback records, priority prediction accuracy is {correct:.0f}%. "
        f"Average congestion score delta is {delta:+.1f} points. "
        f"{'The model tends to over-predict congestion.' if delta < -5 else 'The model tends to under-predict congestion.' if delta > 5 else 'Predictions are well-calibrated.'}"
    )
