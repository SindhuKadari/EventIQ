"""
cascade_detector.py — Detects cascading / compound event risk.

DIAGNOSIS NOTE:
  A RandomForestClassifier on the time-overlap labels scored 61.1% CV accuracy
  against a majority-class baseline of 63.1% — the ML was performing BELOW
  random. Root cause: corridor determines overlap entirely (busy corridors
  have near-100% overlap rate regardless of hour/cause), so the classifier
  added no information beyond the rate table.

REDESIGN — Three-tier approach (no ML, fully interpretable):
  Tier 1 — Real-time live check (highest priority):
            Does the new event share a corridor with any currently active event?
            If yes → cascade_severity = Low or High based on active count.
  Tier 2 — Historical corridor rate threshold:
            If cascade_rate > CRITICAL_RATE (0.85) → HIGH background risk.
            If cascade_rate > MODERATE_RATE (0.60) → MODERATE background risk.
  Tier 3 — Temporal amplifier:
            Peak hour AND high-density corridor → +1 severity level.

Thresholds derived from dataset distribution:
  - Median cascade rate across corridors ≈ 0.65
  - 75th percentile ≈ 0.88
"""

import os
import pickle
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)

DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "train.csv")
DEFAULT_CASCADE_MODEL_PATH = os.path.join(BASE_DIR, "models", "cascade_model.pkl")

# Severity thresholds (from dataset: median=0.65, p75=0.88)
CRITICAL_RATE  = 0.85   # corridor is almost always cascading
MODERATE_RATE  = 0.60   # above dataset median
PEAK_HOURS = set(list(range(7, 11)) + list(range(17, 21)))


class CascadeDetector:
    """
    Three-tier cascade risk detector. No ML — fully interpretable.

    Tier 1: Live active-event overlap check (real-time).
    Tier 2: Historical corridor rate thresholds.
    Tier 3: Temporal amplifier (peak hour × high-density corridor).
    """

    def __init__(
        self,
        data_path: str = DEFAULT_DATA_PATH,
        model_path: str = DEFAULT_CASCADE_MODEL_PATH,
    ):
        self._model_path = model_path
        self._data_path = data_path
        self._corridor_rates: dict = {}
        self._cascade_rates: dict = {}      # (corridor, hour_bucket, weekday)
        self._concurrent_corridors: set = set()
        self._load_or_build()

    # ------------------------------------------------------------------
    # Build / cache rate tables (no classifier)
    # ------------------------------------------------------------------

    def _load_or_build(self):
        if os.path.exists(self._model_path):
            with open(self._model_path, "rb") as f:
                bundle = pickle.load(f)
            self._corridor_rates = bundle["corridor_rates"]
            self._cascade_rates  = bundle["cascade_rates"]
            self._concurrent_corridors = bundle["concurrent_corridors"]
        else:
            self._build_rate_tables()

    def _build_rate_tables(self):
        df = self._load_and_label()
        if df is None:
            return

        # Overall corridor rate
        self._corridor_rates = (
            df.groupby("corridor")["is_cascade"].mean().round(4).to_dict()
        )

        # Granular rate per (corridor, hour_bucket, weekday)
        self._cascade_rates = (
            df.groupby(["corridor", "hour_bucket", "weekday"])["is_cascade"]
            .mean()
            .round(4)
            .to_dict()
        )

        self._concurrent_corridors = set(
            df[df["is_cascade"] == 1]["corridor"].unique().tolist()
        )

        os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
        with open(self._model_path, "wb") as f:
            pickle.dump(
                {
                    "corridor_rates": self._corridor_rates,
                    "cascade_rates": self._cascade_rates,
                    "concurrent_corridors": self._concurrent_corridors,
                },
                f,
            )

    def _load_and_label(self) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_csv(self._data_path)
        except Exception:
            return None

        df = df[df["corridor"].notna() & (df["corridor"] != "Non-corridor")].copy()
        df["start_dt"] = pd.to_datetime(df["start_datetime"], format="mixed", utc=True, errors="coerce")
        df["end_dt"]   = pd.to_datetime(df["end_datetime"],   format="mixed", utc=True, errors="coerce")
        df = df.dropna(subset=["start_dt", "latitude", "longitude"])
        df["end_dt"]   = df["end_dt"].fillna(df["start_dt"] + pd.Timedelta(hours=2))
        df["hour"]     = df["start_dt"].dt.hour
        df["weekday"]  = df["start_dt"].dt.weekday
        df["hour_bucket"] = (df["hour"] // 3) * 3
        df["is_cascade"] = 0

        for corridor, group in df.groupby("corridor"):
            idxs = group.index.tolist()
            if len(idxs) < 2:
                continue
            starts = group["start_dt"].values
            ends   = group["end_dt"].values
            cset   = set()
            for i in range(len(idxs)):
                for j in range(i + 1, len(idxs)):
                    if max(starts[i], starts[j]) < min(ends[i], ends[j]):
                        cset.add(idxs[i])
                        cset.add(idxs[j])
            for idx in cset:
                df.at[idx, "is_cascade"] = 1

        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cascade_probability(self, event_input: dict) -> float:
        """
        Return estimated cascade probability (0–1) from the rate table.
        Uses granular (corridor, hour_bucket, weekday) rate when available,
        falls back to corridor overall rate.
        """
        corridor    = str(event_input.get("corridor", ""))
        hour        = int(event_input.get("hour", 12))
        weekday     = int(event_input.get("weekday", 0))
        hour_bucket = (hour // 3) * 3

        granular = self._cascade_rates.get((corridor, hour_bucket, weekday))
        if granular is not None:
            return round(float(granular), 3)
        return round(float(self._corridor_rates.get(corridor, 0.0)), 3)

    def get_background_risk(self, event_input: dict) -> dict:
        """
        Tier 2 + 3: historical rate-based background risk.

        Returns:
            {severity: "None"|"Moderate"|"High"|"Critical",
             rate: float,
             is_peak_amplified: bool,
             message: str}
        """
        corridor = str(event_input.get("corridor", ""))
        hour     = int(event_input.get("hour", 12))

        rate = self.get_cascade_probability(event_input)
        is_peak = hour in PEAK_HOURS

        # Base severity from rate
        if rate >= CRITICAL_RATE:
            severity = "Critical"
        elif rate >= MODERATE_RATE:
            severity = "Moderate"
        else:
            severity = "None"

        # Tier 3 amplifier: peak + moderate → High
        peak_amplified = False
        if is_peak and severity == "Moderate":
            severity = "High"
            peak_amplified = True

        messages = {
            "None":     f"{corridor} has low historical cascade rate ({rate:.0%}). Minimal background risk.",
            "Moderate": f"{corridor} has moderate cascade rate ({rate:.0%}). Monitor adjacent corridors.",
            "High":     f"{corridor} cascade rate {rate:.0%} — elevated at peak hour. Pre-position additional units.",
            "Critical": f"CRITICAL: {corridor} cascades {rate:.0%} of the time historically. Expect compound congestion.",
        }

        return {
            "severity": severity,
            "rate": rate,
            "is_peak_amplified": peak_amplified,
            "message": messages.get(severity, ""),
        }

    def check_active_cascade(self, new_event: dict, active_events: list) -> dict:
        """
        Tier 1: Check if the new event shares a corridor with active events.

        Args:
            new_event:     Dict with at least 'corridor'.
            active_events: List of active event dicts with 'corridor'.

        Returns:
            {is_cascade, conflicting_events, cascade_severity, message}
        """
        new_corridor = str(new_event.get("corridor", ""))
        conflicting = [
            e for e in active_events
            if str(e.get("corridor", "")) == new_corridor
            and new_corridor not in ("", "Non-corridor")
        ]
        is_cascade = len(conflicting) > 0

        if not is_cascade:
            severity = "None"
            msg = "No active events on same corridor."
        elif len(conflicting) == 1:
            severity = "Low"
            msg = (
                f"1 active event already on {new_corridor}. "
                "Compound congestion possible."
            )
        else:
            severity = "High"
            msg = (
                f"{len(conflicting)} concurrent events on {new_corridor}! "
                "High cascade risk — activate corridor management protocol."
            )

        return {
            "is_cascade": is_cascade,
            "conflicting_events": conflicting,
            "cascade_severity": severity,
            "message": msg,
        }

    def assess_full_cascade_risk(self, event_input: dict, active_events: list) -> dict:
        """
        Combined Tier 1 + 2 + 3 assessment.
        Live check overrides background if it fires.
        """
        live   = self.check_active_cascade(event_input, active_events)
        bg     = self.get_background_risk(event_input)
        rate   = self.get_cascade_probability(event_input)

        # Final severity = max of live and background
        severity_rank = {"None": 0, "Low": 1, "Moderate": 2, "High": 3, "Critical": 4}
        live_sev  = live["cascade_severity"]
        bg_sev    = bg["severity"]
        final_sev = live_sev if severity_rank.get(live_sev, 0) >= severity_rank.get(bg_sev, 0) else bg_sev

        return {
            "cascade_probability": rate,
            "final_severity": final_sev,
            "live_check": live,
            "background_risk": bg,
            "summary": (
                f"Live: {live['message']} | "
                f"Background: {bg['message']}"
            ),
        }

    def get_high_risk_corridors(self, top_n: int = 10) -> list:
        """Return corridors ranked by historical cascade rate."""
        ranked = sorted(self._corridor_rates.items(), key=lambda x: x[1], reverse=True)
        return [
            {"corridor": cor, "cascade_rate": round(rate, 3)}
            for cor, rate in ranked[:top_n]
        ]

    def get_corridor_cascade_profile(self, corridor: str) -> dict:
        """Return mean cascade rate per hour bucket for a corridor."""
        profile = {}
        for hour_bucket in range(0, 24, 3):
            rates = []
            for wd in range(7):
                r = self._cascade_rates.get((corridor, hour_bucket, wd), None)
                if r is not None:
                    rates.append(r)
            label = f"{hour_bucket:02d}:00"
            profile[label] = round(float(np.mean(rates)), 3) if rates else 0.0
        return profile

