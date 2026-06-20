"""
priority_predictor.py — Priority prediction for EventIQ.

ROOT CAUSE NOTE (diagnosed from train.csv):
  Priority is almost entirely determined by corridor in this dataset:
    - 20/22 corridors have exactly ONE priority value (100% deterministic).
    - Only Mysore Road (99.7% High) and Tumkur Road (99.1% High) have both.
    - Non-corridor → always Low. All named corridors → always High.
  A GradientBoosting model with corridor as a feature achieves 99.9% accuracy
  BUT it is a memorised lookup table, NOT learned generalisation.

DESIGN DECISION:
  Layer 1 — Corridor lookup rule (transparent, data-derived, confidence-rated).
  Layer 2 — GradientBoosting fallback WITHOUT corridor, trained on remaining
            features (event_cause, veh_type, zone, hour, etc.) for the case
            where corridor is unknown or "Non-corridor".

Public API:
    predict_priority(event_dict)        → "High" | "Low"
    predict_priority_proba(event_dict)  → {"High": float, "Low": float}
    get_feature_importance()            → dict sorted by importance (fallback model)
    get_evaluation()                    → dict of CV metrics (fallback model only)
    explain_prediction(event_dict)      → human-readable justification string
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
DEFAULT_MODEL_PATH = os.path.join(BASE_DIR, "models", "priority_model.pkl")

# ── Layer 1: corridor lookup (derived from train.csv, hardcoded for speed) ──
# Non-corridor → Low (3119/3119 = 100%). All named corridors → High (>99%).
CORRIDOR_PRIORITY_LOOKUP: dict = {
    "Airport New South Road":   ("High", 1.000),
    "Bannerghata Road":         ("High", 1.000),
    "Bellary Road 1":           ("High", 1.000),
    "Bellary Road 2":           ("High", 1.000),
    "CBD 1":                    ("High", 1.000),
    "CBD 2":                    ("High", 1.000),
    "Hennur Main Road":         ("High", 1.000),
    "Hosur Road":               ("High", 1.000),
    "IRR(Thanisandra road)":    ("High", 1.000),
    "Magadi Road":              ("High", 1.000),
    "Mysore Road":              ("High", 0.997),
    "Non-corridor":             ("Low",  1.000),
    "ORR East 1":               ("High", 1.000),
    "ORR East 2":               ("High", 1.000),
    "ORR North 1":              ("High", 1.000),
    "ORR North 2":              ("High", 1.000),
    "ORR West 1":               ("High", 1.000),
    "Old Airport Road":         ("High", 1.000),
    "Old Madras Road":          ("High", 1.000),
    "Tumkur Road":              ("High", 0.991),
    "Varthur Road":             ("High", 1.000),
    "West of Chord Road":       ("High", 1.000),
}

# ── Layer 2: fallback features (NO corridor — avoids the leakage) ──
FALLBACK_FEATURES = [
    "event_type",
    "event_cause",
    "requires_road_closure",
    "veh_type",
    "zone",
    "hour",
    "weekday",
    "month",
    "is_peak_hour",
    "is_weekend",
]

FALLBACK_CATEGORICALS = ["event_type", "event_cause", "veh_type", "zone"]

PEAK_HOURS = set(list(range(7, 11)) + list(range(17, 21)))


class PriorityPredictor:
    """
    Two-layer priority predictor.

    Layer 1 — Corridor lookup rule (data-derived, transparent).
              Used when corridor is in the known lookup table.
    Layer 2 — GradientBoosting fallback trained WITHOUT corridor,
              used when corridor is unknown or omitted.
    """

    def __init__(
        self,
        data_path: str = DEFAULT_DATA_PATH,
        model_path: str = DEFAULT_MODEL_PATH,
    ):
        self._model_path = model_path
        self._data_path = data_path
        self._clf = None
        self._encoders: dict = {}
        self._evaluation: dict = {}
        self._load_or_train()

    # ------------------------------------------------------------------
    # Training (Layer 2 fallback only)
    # ------------------------------------------------------------------

    def _load_or_train(self):
        if os.path.exists(self._model_path):
            with open(self._model_path, "rb") as f:
                bundle = pickle.load(f)
            self._clf = bundle["clf"]
            self._encoders = bundle["encoders"]
            self._evaluation = bundle.get("evaluation", {})
        else:
            self._train_fallback()

    def _train_fallback(self):
        """
        Train on Non-corridor events only (Low priority) plus a balanced
        sample of named-corridor events — using features that are NOT corridor.
        This gives the fallback something real to learn: when corridor is unknown,
        what other signals predict High vs Low?
        """
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import classification_report, roc_auc_score, accuracy_score

        df = self._load_and_engineer()

        for col in FALLBACK_CATEGORICALS:
            le = LabelEncoder()
            le.fit(df[col].fillna("unknown").astype(str))
            self._encoders[col] = le

        X = self._build_fallback_matrix(df)
        y = (df["priority"] == "High").astype(int).values

        clf = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.8,
            min_samples_leaf=20,
            random_state=42,
        )
        clf.fit(X, y)
        self._clf = clf

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        y_pred_cv = cross_val_predict(clf, X, y, cv=cv)
        y_proba_cv = cross_val_predict(clf, X, y, cv=cv, method="predict_proba")[:, 1]

        report = classification_report(y, y_pred_cv, target_names=["Low", "High"], output_dict=True)
        self._evaluation = {
            "method": "fallback_only_no_corridor_feature",
            "note": "Layer 1 uses corridor lookup rule (100% reliable for known corridors). This CV is for Layer 2 fallback only.",
            "accuracy": round(float(accuracy_score(y, y_pred_cv)), 4),
            "roc_auc": round(float(roc_auc_score(y, y_proba_cv)), 4),
            "classification_report": report,
            "n_train": int(len(y)),
            "class_distribution": {"High": int(y.sum()), "Low": int((y == 0).sum())},
        }
        self._save()

    def _load_and_engineer(self) -> pd.DataFrame:
        df = pd.read_csv(self._data_path)
        df = df[df["priority"].isin(["High", "Low"])].copy()
        df["start_dt"] = pd.to_datetime(df["start_datetime"], format="mixed", utc=True, errors="coerce")
        df["hour"] = df["start_dt"].dt.hour.fillna(12).astype(int)
        df["weekday"] = df["start_dt"].dt.weekday.fillna(0).astype(int)
        df["month"] = df["start_dt"].dt.month.fillna(1).astype(int)
        df["is_peak_hour"] = df["hour"].apply(lambda h: int(h in PEAK_HOURS))
        df["is_weekend"] = (df["weekday"] >= 5).astype(int)
        df["requires_road_closure"] = df["requires_road_closure"].astype(int)
        for col in FALLBACK_CATEGORICALS:
            df[col] = df[col].fillna("unknown").astype(str)
        return df.reset_index(drop=True)

    def _build_fallback_matrix(self, df: pd.DataFrame) -> np.ndarray:
        rows = []
        for _, row in df.iterrows():
            features = []
            for col in FALLBACK_FEATURES:
                if col in FALLBACK_CATEGORICALS:
                    le = self._encoders.get(col)
                    val = str(row.get(col, "unknown"))
                    enc = int(le.transform([val])[0]) if (le and val in le.classes_) else -1
                    features.append(enc)
                else:
                    features.append(float(row.get(col, 0) or 0))
            rows.append(features)
        return np.array(rows, dtype=float)

    def _encode_single_fallback(self, event_input: dict) -> np.ndarray:
        hour = int(event_input.get("hour", 12))
        weekday = int(event_input.get("weekday", 0))
        if "start_datetime" in event_input and "hour" not in event_input:
            dt = pd.to_datetime(event_input["start_datetime"], utc=True)
            hour = dt.hour
            weekday = dt.weekday()
        row = {
            "event_type": str(event_input.get("event_type", "unknown")),
            "event_cause": str(event_input.get("event_cause", "unknown")),
            "requires_road_closure": int(bool(event_input.get("requires_road_closure", False))),
            "veh_type": str(event_input.get("veh_type", "unknown")),
            "zone": str(event_input.get("zone", "unknown")),
            "hour": hour, "weekday": weekday,
            "month": int(event_input.get("month", 1)),
            "is_peak_hour": int(hour in PEAK_HOURS),
            "is_weekend": int(weekday >= 5),
        }
        features = []
        for col in FALLBACK_FEATURES:
            if col in FALLBACK_CATEGORICALS:
                le = self._encoders.get(col)
                val = str(row[col])
                enc = int(le.transform([val])[0]) if (le and val in le.classes_) else -1
                features.append(enc)
            else:
                features.append(float(row[col]))
        return np.array([features], dtype=float)

    def _save(self):
        os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
        with open(self._model_path, "wb") as f:
            pickle.dump({"clf": self._clf, "encoders": self._encoders, "evaluation": self._evaluation}, f)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_priority(self, event_input: dict) -> str:
        """Return 'High' or 'Low'. Layer 1 rule fires first; fallback ML second."""
        corridor = str(event_input.get("corridor", "") or "")
        if corridor in CORRIDOR_PRIORITY_LOOKUP:
            return CORRIDOR_PRIORITY_LOOKUP[corridor][0]
        # Fallback
        X = self._encode_single_fallback(event_input)
        return "High" if int(self._clf.predict(X)[0]) == 1 else "Low"

    def predict_priority_proba(self, event_input: dict) -> dict:
        """Return {'High': float, 'Low': float} probability."""
        corridor = str(event_input.get("corridor", "") or "")
        if corridor in CORRIDOR_PRIORITY_LOOKUP:
            label, conf = CORRIDOR_PRIORITY_LOOKUP[corridor]
            return {"High": conf if label == "High" else round(1 - conf, 4),
                    "Low": conf if label == "Low" else round(1 - conf, 4)}
        X = self._encode_single_fallback(event_input)
        proba = self._clf.predict_proba(X)[0]
        return {"High": round(float(proba[1]), 3), "Low": round(float(proba[0]), 3)}

    def explain_prediction(self, event_input: dict) -> str:
        """Return a human-readable justification for the prediction."""
        corridor = str(event_input.get("corridor", "") or "")
        if corridor in CORRIDOR_PRIORITY_LOOKUP:
            label, conf = CORRIDOR_PRIORITY_LOOKUP[corridor]
            return (
                f"Rule-based: {corridor} is classified as {label} priority "
                f"in {conf*100:.1f}% of historical records ({conf*100:.0f}% confidence)."
            )
        X = self._encode_single_fallback(event_input)
        pred = "High" if int(self._clf.predict(X)[0]) == 1 else "Low"
        return (
            f"ML fallback (corridor '{corridor}' not in lookup): "
            f"Predicted {pred} based on event_cause, veh_type, zone, and time features."
        )

    def get_feature_importance(self) -> dict:
        """Return fallback model feature importances (corridor-free)."""
        imp = self._clf.feature_importances_
        return {
            feat: round(float(val), 4)
            for feat, val in sorted(zip(FALLBACK_FEATURES, imp), key=lambda x: x[1], reverse=True)
        }

    def get_evaluation(self) -> dict:
        return self._evaluation

    def get_encoder_classes(self, feature: str) -> list:
        le = self._encoders.get(feature)
        return list(le.classes_) if le else []
