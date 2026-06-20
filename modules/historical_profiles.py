"""
historical_profiles.py — Dataset-derived event profiles.

Builds rich statistical profiles from train.csv grouped by:
  - event_type + event_cause
  - corridor
  - zone
  - police_station
  - hour_bucket (0,3,6,9,12,15,18,21)
  - junction

No labels invented. Every stat is derived from actual ASTraM data.

Public API:
    get_event_profile(event_input)         → dict with historical stats
    get_corridor_profile(corridor)         → dict
    get_zone_profile(zone)                 → dict
    get_peak_hour_risk(corridor, hour)     → float (0–1)
    get_repeat_event_rate(corridor)        → float (events per day)
    get_top_junctions(corridor, n)         → list
    get_hourly_frequency(corridor)         → dict {hour: count}
    compare_to_historical(event, score)    → dict (anomaly context)
"""

import os
import pickle
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)

DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "train.csv")
DEFAULT_PROFILE_CACHE = os.path.join(BASE_DIR, "models", "historical_profiles.pkl")


class HistoricalProfiles:
    """
    Precomputed statistical profiles from the ASTraM dataset.
    All profiles are built once and cached to avoid repeated CSV reads.
    """

    def __init__(
        self,
        data_path: str = DEFAULT_DATA_PATH,
        cache_path: str = DEFAULT_PROFILE_CACHE,
    ):
        self._data_path = data_path
        self._cache_path = cache_path
        self._profiles: dict = {}
        self._load_or_build()

    # ------------------------------------------------------------------
    # Build / cache
    # ------------------------------------------------------------------

    def _load_or_build(self):
        if os.path.exists(self._cache_path):
            with open(self._cache_path, "rb") as f:
                self._profiles = pickle.load(f)
        else:
            self._build_profiles()

    def _build_profiles(self):
        df = self._load_data()
        self._profiles = {
            "corridor":          self._build_corridor_profiles(df),
            "zone":              self._build_zone_profiles(df),
            "cause":             self._build_cause_profiles(df),
            "police_station":    self._build_ps_profiles(df),
            "hourly_freq":       self._build_hourly_frequency(df),
            "junction":          self._build_junction_profiles(df),
            "closure_rate":      self._build_closure_rate(df),
            "repeat_rate":       self._build_repeat_rate(df),
            "priority_dist":     self._build_priority_distribution(df),
            "cascade_corridors": self._build_cascade_corridors(df),
            "global_stats":      self._build_global_stats(df),
        }
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "wb") as f:
            pickle.dump(self._profiles, f)

    def _load_data(self) -> pd.DataFrame:
        df = pd.read_csv(self._data_path)
        df["start_dt"] = pd.to_datetime(
            df["start_datetime"], format="mixed", utc=True, errors="coerce"
        )
        df["end_dt"] = pd.to_datetime(
            df["end_datetime"], format="mixed", utc=True, errors="coerce"
        )
        df["closed_dt"] = pd.to_datetime(
            df["closed_datetime"], format="mixed", utc=True, errors="coerce"
        )
        df["hour"] = df["start_dt"].dt.hour.fillna(12).astype(int)
        df["weekday"] = df["start_dt"].dt.weekday.fillna(0).astype(int)
        df["month"] = df["start_dt"].dt.month.fillna(1).astype(int)
        df["is_peak"] = df["hour"].apply(lambda h: int(7 <= h <= 10 or 17 <= h <= 20))
        df["is_weekend"] = (df["weekday"] >= 5).astype(int)
        df["hour_bucket"] = (df["hour"] // 3) * 3

        df["duration_min"] = (
            (df["end_dt"] - df["start_dt"]).dt.total_seconds() / 60
        ).clip(lower=0, upper=10080)

        df["close_lag_min"] = (
            (df["closed_dt"] - df["start_dt"]).dt.total_seconds() / 60
        ).clip(lower=0, upper=50000)

        df["requires_road_closure"] = df["requires_road_closure"].astype(int)
        return df

    # ------------------------------------------------------------------
    # Profile builders
    # ------------------------------------------------------------------

    def _build_corridor_profiles(self, df: pd.DataFrame) -> dict:
        profiles = {}
        for corridor, grp in df.groupby("corridor"):
            g = grp.dropna(subset=["latitude", "longitude"])
            profiles[str(corridor)] = {
                "total_events":       int(len(grp)),
                "peak_event_count":   int(grp["is_peak"].sum()),
                "peak_event_pct":     round(float(grp["is_peak"].mean() * 100), 1),
                "closure_rate":       round(float(grp["requires_road_closure"].mean() * 100), 1),
                "high_priority_pct":  round(float((grp["priority"] == "High").mean() * 100), 1),
                "common_causes":      grp["event_cause"].value_counts().head(3).to_dict(),
                "common_zones":       grp["zone"].value_counts().head(2).to_dict(),
                "weekday_dist":       grp["weekday"].value_counts().sort_index().to_dict(),
                "hourly_dist":        grp["hour"].value_counts().sort_index().to_dict(),
                "mean_duration_min":  round(float(grp["duration_min"].dropna().mean() or 0), 1),
                "median_duration_min": round(float(grp["duration_min"].dropna().median() or 0), 1),
                "unplanned_pct":      round(float((grp["event_type"] == "unplanned").mean() * 100), 1),
            }
        return profiles

    def _build_zone_profiles(self, df: pd.DataFrame) -> dict:
        profiles = {}
        for zone, grp in df.groupby("zone"):
            profiles[str(zone)] = {
                "total_events":      int(len(grp)),
                "peak_event_pct":    round(float(grp["is_peak"].mean() * 100), 1),
                "closure_rate":      round(float(grp["requires_road_closure"].mean() * 100), 1),
                "high_priority_pct": round(float((grp["priority"] == "High").mean() * 100), 1),
                "top_corridors":     grp["corridor"].value_counts().head(3).to_dict(),
                "top_causes":        grp["event_cause"].value_counts().head(3).to_dict(),
                "top_junctions":     grp["junction"].dropna().value_counts().head(3).to_dict(),
            }
        return profiles

    def _build_cause_profiles(self, df: pd.DataFrame) -> dict:
        profiles = {}
        for cause, grp in df.groupby("event_cause"):
            profiles[str(cause)] = {
                "total_events":       int(len(grp)),
                "high_priority_pct":  round(float((grp["priority"] == "High").mean() * 100), 1),
                "closure_rate":       round(float(grp["requires_road_closure"].mean() * 100), 1),
                "peak_pct":           round(float(grp["is_peak"].mean() * 100), 1),
                "mean_duration_min":  round(float(grp["duration_min"].dropna().mean() or 0), 1),
                "top_corridors":      grp["corridor"].value_counts().head(3).to_dict(),
                "top_veh_types":      grp["veh_type"].dropna().value_counts().head(3).to_dict(),
            }
        return profiles

    def _build_ps_profiles(self, df: pd.DataFrame) -> dict:
        profiles = {}
        for ps, grp in df.groupby("police_station"):
            profiles[str(ps)] = {
                "total_events":      int(len(grp)),
                "high_priority_pct": round(float((grp["priority"] == "High").mean() * 100), 1),
                "closure_rate":      round(float(grp["requires_road_closure"].mean() * 100), 1),
                "peak_pct":          round(float(grp["is_peak"].mean() * 100), 1),
                "top_causes":        grp["event_cause"].value_counts().head(3).to_dict(),
                "top_corridors":     grp["corridor"].value_counts().head(3).to_dict(),
                "mean_duration_min": round(float(grp["duration_min"].dropna().mean() or 0), 1),
            }
        return profiles

    def _build_hourly_frequency(self, df: pd.DataFrame) -> dict:
        """Per-corridor, per-hour event counts."""
        freq = {}
        for corridor, grp in df.groupby("corridor"):
            freq[str(corridor)] = (
                grp["hour"].value_counts().sort_index().to_dict()
            )
        freq["__global__"] = df["hour"].value_counts().sort_index().to_dict()
        return freq

    def _build_junction_profiles(self, df: pd.DataFrame) -> dict:
        df_j = df.dropna(subset=["junction"])
        profiles = {}
        for junc, grp in df_j.groupby("junction"):
            profiles[str(junc)] = {
                "total_events":      int(len(grp)),
                "high_priority_pct": round(float((grp["priority"] == "High").mean() * 100), 1),
                "closure_rate":      round(float(grp["requires_road_closure"].mean() * 100), 1),
                "corridor":          grp["corridor"].mode().iloc[0] if len(grp) > 0 else "",
            }
        return profiles

    def _build_closure_rate(self, df: pd.DataFrame) -> dict:
        """Road closure rates by (event_cause) and by (corridor)."""
        by_cause = df.groupby("event_cause")["requires_road_closure"].mean().round(3).to_dict()
        by_corridor = df.groupby("corridor")["requires_road_closure"].mean().round(3).to_dict()
        return {"by_cause": by_cause, "by_corridor": by_corridor}

    def _build_repeat_rate(self, df: pd.DataFrame) -> dict:
        """
        Events per day per corridor (proxy for recurrence).
        Uses date range of the dataset as denominator.
        """
        df2 = df.dropna(subset=["start_dt"])
        total_days = max(
            1,
            (df2["start_dt"].max() - df2["start_dt"].min()).days,
        )
        return (
            (df2.groupby("corridor")["id"].count() / total_days)
            .round(3)
            .to_dict()
        )

    def _build_priority_distribution(self, df: pd.DataFrame) -> dict:
        """High/Low priority split per corridor."""
        pivot = (
            df.groupby(["corridor", "priority"])["id"]
            .count()
            .unstack(fill_value=0)
            .apply(lambda r: round(r["High"] / (r.sum() or 1) * 100, 1), axis=1)
        )
        return pivot.to_dict()

    def _build_cascade_corridors(self, df: pd.DataFrame) -> dict:
        """
        For corridors with labeled time-window overlaps (from cascade detector),
        compute the fraction of events that overlap with another.
        """
        df2 = df[df["corridor"].notna() & (df["corridor"] != "Non-corridor")].copy()
        df2 = df2.dropna(subset=["start_dt"])
        df2["end_dt2"] = df2["end_dt"].fillna(df2["start_dt"] + pd.Timedelta(hours=2))
        counts = {}
        cascade_counts = {}
        for corridor, grp in df2.groupby("corridor"):
            idxs = grp.index.tolist()
            counts[str(corridor)] = len(idxs)
            cascade_set = set()
            if len(idxs) >= 2:
                starts = grp["start_dt"].values
                ends = grp["end_dt2"].values
                for i in range(len(idxs)):
                    for j in range(i + 1, len(idxs)):
                        if max(starts[i], starts[j]) < min(ends[i], ends[j]):
                            cascade_set.add(idxs[i])
                            cascade_set.add(idxs[j])
            cascade_counts[str(corridor)] = round(
                len(cascade_set) / max(1, len(idxs)), 3
            )
        return cascade_counts

    def _build_global_stats(self, df: pd.DataFrame) -> dict:
        return {
            "total_records":       int(len(df)),
            "date_range_start":    str(df["start_dt"].min()),
            "date_range_end":      str(df["start_dt"].max()),
            "unique_corridors":    int(df["corridor"].nunique()),
            "unique_zones":        int(df["zone"].nunique()),
            "unique_police_stations": int(df["police_station"].nunique()),
            "unique_junctions":    int(df["junction"].nunique()),
            "overall_closure_rate": round(float(df["requires_road_closure"].mean() * 100), 1),
            "overall_high_priority_pct": round(float((df["priority"] == "High").mean() * 100), 1),
            "peak_hour_pct":       round(float(df["is_peak"].mean() * 100), 1),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_event_profile(self, event_input: dict) -> dict:
        """
        Return a combined profile for an event using its corridor, zone, cause,
        and police station.
        """
        corridor = str(event_input.get("corridor", ""))
        zone     = str(event_input.get("zone", ""))
        cause    = str(event_input.get("event_cause", ""))
        ps       = str(event_input.get("police_station", ""))

        return {
            "corridor":       self._profiles["corridor"].get(corridor, {}),
            "zone":           self._profiles["zone"].get(zone, {}),
            "cause":          self._profiles["cause"].get(cause, {}),
            "police_station": self._profiles["police_station"].get(ps, {}),
            "repeat_rate_per_day": self._profiles["repeat_rate"].get(corridor, 0.0),
            "cascade_rate":   self._profiles["cascade_corridors"].get(corridor, 0.0),
            "priority_high_pct": self._profiles["priority_dist"].get(corridor, 0.0),
        }

    def get_corridor_profile(self, corridor: str) -> dict:
        return self._profiles["corridor"].get(corridor, {})

    def get_zone_profile(self, zone: str) -> dict:
        return self._profiles["zone"].get(zone, {})

    def get_cause_profile(self, cause: str) -> dict:
        return self._profiles["cause"].get(cause, {})

    def get_ps_profile(self, police_station: str) -> dict:
        return self._profiles["police_station"].get(police_station, {})

    def get_peak_hour_risk(self, corridor: str, hour: int) -> float:
        """
        Returns fraction (0–1) of events on this corridor that happened
        at this exact hour, relative to the busiest hour.
        """
        hourly = self._profiles["hourly_freq"].get(corridor, {})
        if not hourly:
            return 0.0
        total = sum(hourly.values())
        hour_count = hourly.get(hour, 0)
        return round(hour_count / max(1, total), 3)

    def get_repeat_event_rate(self, corridor: str) -> float:
        """Return average events per day on this corridor."""
        return self._profiles["repeat_rate"].get(corridor, 0.0)

    def get_top_junctions(self, corridor: str, n: int = 5) -> list:
        """Return top-n junctions with most events on this corridor."""
        corr_profile = self._profiles["corridor"].get(corridor, {})
        # Junction profiles don't carry corridor filter directly;
        # return global top junctions where mode corridor matches
        return [
            {"junction": j, **stats}
            for j, stats in self._profiles["junction"].items()
            if stats.get("corridor") == corridor
        ][:n]

    def get_hourly_frequency(self, corridor: str) -> dict:
        """Return {hour: count} for this corridor."""
        return self._profiles["hourly_freq"].get(corridor, {})

    def get_global_stats(self) -> dict:
        return self._profiles["global_stats"]

    def compare_to_historical(self, event_input: dict, predicted_score: float) -> dict:
        """
        Compare the current event's predicted score against historical
        patterns for the same corridor + cause to flag anomalies.
        """
        corridor = str(event_input.get("corridor", ""))
        cause    = str(event_input.get("event_cause", ""))
        hour     = int(event_input.get("hour", 12))

        corr_profile = self._profiles["corridor"].get(corridor, {})
        cause_profile = self._profiles["cause"].get(cause, {})
        cascade_rate  = self._profiles["cascade_corridors"].get(corridor, 0.0)
        repeat_rate   = self._profiles["repeat_rate"].get(corridor, 0.0)
        peak_risk     = self.get_peak_hour_risk(corridor, hour)

        # Anomaly flag: score significantly above historic closure rate proxy
        closure_rate_hist = corr_profile.get("closure_rate", 50.0)
        is_anomalous = predicted_score > (closure_rate_hist * 0.8)

        return {
            "corridor_total_events":   corr_profile.get("total_events", 0),
            "corridor_peak_pct":       corr_profile.get("peak_event_pct", 0),
            "corridor_closure_rate":   corr_profile.get("closure_rate", 0),
            "corridor_high_prio_pct":  corr_profile.get("high_priority_pct", 0),
            "cause_mean_duration_min": cause_profile.get("mean_duration_min", 0),
            "cause_closure_rate":      cause_profile.get("closure_rate", 0),
            "cascade_rate":            cascade_rate,
            "repeat_rate_per_day":     repeat_rate,
            "peak_hour_risk":          peak_risk,
            "is_anomalous":            is_anomalous,
            "common_causes_on_corridor": corr_profile.get("common_causes", {}),
        }

    def get_all_corridors(self) -> list:
        return list(self._profiles["corridor"].keys())

    def get_all_zones(self) -> list:
        return list(self._profiles["zone"].keys())

    def get_all_causes(self) -> list:
        return list(self._profiles["cause"].keys())
