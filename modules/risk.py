"""
risk.py — Maps XGBoost congestion scores to risk levels.
No ML. Pure threshold logic per project specification.

Risk thresholds:
    0–40   → Low
    41–65  → Medium
    66–80  → High
    81–100 → Critical
"""

RISK_COLORS = {
    "Low": "#2ecc71",
    "Medium": "#f1c40f",
    "High": "#e67e22",
    "Critical": "#e74c3c",
}

RISK_BG_COLORS = {
    "Low": "#0d2b1a",
    "Medium": "#2b220d",
    "High": "#2b1200",
    "Critical": "#2b0000",
}

RISK_ICONS = {
    "Low": "✅",
    "Medium": "⚠️",
    "High": "🔴",
    "Critical": "🚨",
}

RISK_BADGE_CSS = {
    "Low":      "background:#0d2b1a;color:#2ecc71;border:1px solid #2ecc71",
    "Medium":   "background:#2b220d;color:#f1c40f;border:1px solid #f1c40f",
    "High":     "background:#2b1200;color:#e67e22;border:1px solid #e67e22",
    "Critical": "background:#2b0000;color:#e74c3c;border:1px solid #e74c3c",
}

RISK_DESCRIPTIONS = {
    "Low":      "Normal traffic flow. Standard monitoring sufficient.",
    "Medium":   "Moderate congestion expected. Pre-position one unit.",
    "High":     "Significant disruption likely. Deploy additional manpower and barricades.",
    "Critical": "Severe gridlock risk. Activate full command protocol immediately.",
}


def get_risk_level(score: float) -> str:
    """Return risk level string for a congestion score (0–100)."""
    score = float(score)
    if score <= 40:
        return "Low"
    elif score <= 65:
        return "Medium"
    elif score <= 80:
        return "High"
    else:
        return "Critical"


def get_risk_color(risk_level: str) -> str:
    """Return hex color for a risk level."""
    return RISK_COLORS.get(risk_level, "#ffffff")


def get_risk_metadata(score: float) -> dict:
    """Return full risk metadata dict for a congestion score."""
    level = get_risk_level(score)
    return {
        "score": round(float(score), 1),
        "level": level,
        "color": RISK_COLORS[level],
        "bg_color": RISK_BG_COLORS[level],
        "icon": RISK_ICONS[level],
        "badge_css": RISK_BADGE_CSS[level],
        "description": RISK_DESCRIPTIONS[level],
    }


def score_to_percentile_label(score: float) -> str:
    """Human-readable congestion intensity label."""
    if score <= 20:
        return "Minimal"
    elif score <= 40:
        return "Light"
    elif score <= 55:
        return "Moderate"
    elif score <= 65:
        return "Heavy"
    elif score <= 80:
        return "Severe"
    else:
        return "Gridlock"
