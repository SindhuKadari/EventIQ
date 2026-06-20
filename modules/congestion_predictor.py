"""
congestion_predictor.py — XGBoost congestion score predictor.

Responsibilities:
  - Load the saved XGBoost model
  - Build / load label encoders and KMeans geo-cluster model from train.csv
  - Encode raw event dicts into the exact feature vector the model expects
  - predict()            → single float congestion score (0–100)
  - forecast_timeseries() → hourly congestion curve across the event window

Feature order (must match training):
  event_type, latitude, longitude, event_cause, requires_road_closure,
  authenticated, veh_type, corridor, priority, police_station, zone, junction,
  hour, weekday, month, is_weekend, is_peak_hour,
  incident_duration_minutes, event_distance_km, geo_cluster, lat_grid, lon_grid
"""

import os
import warnings
from typing import Optional

import joblib
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Paths (resolved relative to project root, one level above this file)
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)

DEFAULT_MODEL_PATH = os.path.join(BASE_DIR, "xgboost_congestion_model.pkl")
DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "train.csv")
# Exact pkl files saved at the end of training (label_encoders, KMeans, feature list)
DEFAULT_LABEL_ENCODERS_PATH = os.path.join(BASE_DIR, "label_encoders.pkl")
DEFAULT_GEO_KMEANS_PATH = os.path.join(BASE_DIR, "geo_kmeans.pkl")

# ---------------------------------------------------------------------------
# Feature specification
# ---------------------------------------------------------------------------
FEATURE_ORDER = [
    "event_type",
    "latitude",
    "longitude",
    "event_cause",
    "requires_road_closure",
    "authenticated",
    "veh_type",
    "corridor",
    "priority",
    "police_station",
    "zone",
    "junction",
    "hour",
    "weekday",
    "month",
    "is_weekend",
    "is_peak_hour",
    "incident_duration_minutes",
    "event_distance_km",
    "geo_cluster",
    "lat_grid",
    "lon_grid",
]

CATEGORICAL_FEATURES = [
    "event_type",
    "event_cause",
    "authenticated",
    "veh_type",
    "corridor",
    "priority",
    "police_station",
    "zone",
    "junction",
]

GEO_CLUSTER_N = 30  # Matches training: KMeans(n_clusters=30, random_state=42)

# The XGBoost model's raw output range on training data is 0–23.4 (due to the
# weighted target formula producing values in that range). We scale to 0–100
# so that risk thresholds (Low/Medium/High/Critical) are meaningful.
_MODEL_RAW_MAX = 24.0  # Slightly above observed max (23.37) for headroom

PEAK_HOURS = set(list(range(7, 11)) + list(range(16, 21)))  # 7–10, 16–20 (matches training)


def _is_peak(hour: int) -> int:
    return int(hour in PEAK_HOURS)


# ---------------------------------------------------------------------------
# CongestionPredictor
# ---------------------------------------------------------------------------

class CongestionPredictor:
    """
    Wraps the XGBoost congestion model with full feature engineering.

    Usage:
        predictor = CongestionPredictor()
        score = predictor.predict(event_dict)
        curve = predictor.forecast_timeseries(event_dict)
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        data_path: str = DEFAULT_DATA_PATH,
        label_encoders_path: str = DEFAULT_LABEL_ENCODERS_PATH,
        geo_kmeans_path: str = DEFAULT_GEO_KMEANS_PATH,
    ):
        self.model = joblib.load(model_path)
        self._data_path = data_path
        # Load exact encoders and KMeans produced during training — no reconstruction
        self._encoders: dict = joblib.load(label_encoders_path)
        self._kmeans = joblib.load(geo_kmeans_path)
        self._duration_median = self._compute_duration_median()

    # ------------------------------------------------------------------
    # Duration median (derived once from train.csv, same logic as training)
    # ------------------------------------------------------------------

    def _compute_duration_median(self) -> float:
        """Compute median incident duration from train.csv using training logic."""
        try:
            df = pd.read_csv(self._data_path)
            df["_start"] = pd.to_datetime(
                df["start_datetime"], format="mixed", utc=True, errors="coerce"
            )
            for tc in ["end_datetime", "resolved_datetime", "closed_datetime", "modified_datetime"]:
                if tc in df.columns:
                    _tc = pd.to_datetime(df[tc], format="mixed", utc=True, errors="coerce")
                    df["_end_t"] = _tc if "_end_t" not in df.columns else df["_end_t"].fillna(_tc)
            if "_end_t" in df.columns:
                df["_dur"] = (df["_end_t"] - df["_start"]).dt.total_seconds() / 60
                df.loc[df["_dur"] < 0, "_dur"] = float("nan")
                df["_dur"] = df["_dur"].clip(lower=0, upper=720)
                return float(df["_dur"].median() or 30.0)
        except Exception:
            pass
        return 30.0

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def _encode_categoricals(self, raw: dict) -> dict:
        """Label-encode using exact training encoders.
        Unknown/null values fall back to 'missing' class if available, else NaN
        (XGBoost handles NaN natively via its missing-value split path)."""
        out = raw.copy()
        for col in CATEGORICAL_FEATURES:
            le = self._encoders.get(col)
            if le is None:
                out[col] = float("nan")
                continue
            val = str(raw.get(col) or "")
            if val in ("", "None", "nan", "NaN"):
                val = "missing"
            if val in le.classes_:
                out[col] = int(le.transform([val])[0])
            elif "missing" in le.classes_:
                out[col] = int(le.transform(["missing"])[0])
            else:
                # Unseen category → let XGBoost handle via NaN path
                out[col] = float("nan")
        return out

    def _compute_derived(self, raw: dict) -> dict:
        """Derive temporal, spatial-grid, cluster, duration, and distance features."""
        out = raw.copy()

        # ---- Temporal features ------------------------------------------
        if "start_datetime" in raw and "hour" not in raw:
            dt = pd.to_datetime(raw["start_datetime"], utc=True)
            out["hour"] = dt.hour
            out["weekday"] = dt.weekday()
            out["month"] = dt.month

        hour = int(out.get("hour", 12))
        weekday = int(out.get("weekday", 0))
        out["hour"] = hour
        out["weekday"] = weekday
        out["month"] = int(out.get("month", 1))
        out["is_weekend"] = int(weekday >= 5)
        out["is_peak_hour"] = _is_peak(hour)

        # ---- Spatial grids: round(2) matches training exactly -----------
        lat = float(out.get("latitude", 12.97))
        lon = float(out.get("longitude", 77.59))
        out["lat_grid"] = round(lat, 2)
        out["lon_grid"] = round(lon, 2)

        # ---- Geo cluster ------------------------------------------------
        if self._kmeans is not None:
            out["geo_cluster"] = int(self._kmeans.predict([[lat, lon]])[0])
        else:
            out["geo_cluster"] = 0

        # ---- Incident duration ------------------------------------------
        # Training: fill NaN with median, clip 0–720 min.
        # We stored _duration_median at encoder-build time.
        raw_dur = out.get("incident_duration_minutes")
        if raw_dur is None or (isinstance(raw_dur, float) and (raw_dur != raw_dur)):
            out["incident_duration_minutes"] = float(getattr(self, "_duration_median", 30.0))
        else:
            out["incident_duration_minutes"] = float(max(0.0, min(720.0, float(raw_dur))))

        # ---- Event distance ---------------------------------------------
        # Training: proper Haversine, 0.0 when end coords missing/zero, clip 0–50 km.
        if out.get("event_distance_km") is None:
            end_lat = out.get("endlatitude")
            end_lon = out.get("endlongitude")
            if (end_lat and end_lon
                    and not pd.isna(end_lat) and not pd.isna(end_lon)
                    and float(end_lat) != 0.0 and float(end_lon) != 0.0):
                import math
                el, elo = float(end_lat), float(end_lon)
                R = 6371
                dlat = math.radians(el - lat)
                dlon = math.radians(elo - lon)
                a = (math.sin(dlat/2)**2
                     + math.cos(math.radians(lat)) * math.cos(math.radians(el))
                     * math.sin(dlon/2)**2)
                dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                out["event_distance_km"] = float(min(50.0, max(0.0, dist)))
            else:
                out["event_distance_km"] = 0.0

        # ---- Bool to int ------------------------------------------------
        out["requires_road_closure"] = int(
            bool(out.get("requires_road_closure", False))
        )

        return out

    def _build_feature_vector(self, raw: dict) -> np.ndarray:
        """Full pipeline: derive → encode → ordered numpy array."""
        derived = self._compute_derived(raw)
        encoded = self._encode_categoricals(derived)
        vector = [float(encoded.get(f, 0.0) or 0.0) for f in FEATURE_ORDER]
        return np.array([vector], dtype=np.float32)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, event_input: dict) -> float:
        """
        Predict congestion score for one event.

        Args:
            event_input: dict with raw event fields (see FEATURE_ORDER for keys).

        Returns:
            Congestion score scaled to [0, 100].
        """
        X = self._build_feature_vector(event_input)
        raw = float(self.model.predict(X)[0])
        # Scale from model native range (0–23.4) to 0–100 for risk thresholds
        scaled = raw * (100.0 / _MODEL_RAW_MAX)
        return float(np.clip(scaled, 0.0, 100.0))

    def forecast_timeseries(
        self,
        event_input: dict,
        duration_hours: Optional[int] = None,
    ) -> list:
        """
        Predict congestion at each hour across the event window.

        Args:
            event_input:    Raw event dict.
            duration_hours: Override event duration in hours.
                            Defaults to incident_duration_minutes / 60.

        Returns:
            List of dicts: [{hour, offset_h, score, is_peak}, ...]
        """
        base_hour = int(event_input.get("hour", 12))
        dur_min = float(
            event_input.get("incident_duration_minutes") or self._duration_median
        )
        n_hours = duration_hours or max(1, int(dur_min / 60))
        n_hours = min(n_hours, 24)  # cap at 24 h for viz

        results = []
        for offset in range(n_hours + 1):  # +1 to include the final hour
            h = (base_hour + offset) % 24
            overrides = {
                **event_input,
                "hour": h,
                "is_peak_hour": _is_peak(h),
            }
            score = self.predict(overrides)
            results.append(
                {
                    "hour": h,
                    "offset_h": offset,
                    "label": f"{h:02d}:00",
                    "score": round(score, 1),
                    "is_peak": bool(_is_peak(h)),
                }
            )
        return results

    def get_feature_importance(self) -> dict:
        """Return feature importances from the underlying XGBoost model."""
        imp = self.model.feature_importances_
        return {
            feat: round(float(val), 4)
            for feat, val in sorted(
                zip(FEATURE_ORDER, imp), key=lambda x: x[1], reverse=True
            )
        }

    def get_encoder_classes(self, feature: str) -> list:
        """Return known classes for a categorical feature."""
        le = self._encoders.get(feature)
        if le is None:
            return []
        return list(le.classes_)
