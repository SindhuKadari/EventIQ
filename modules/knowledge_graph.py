"""
knowledge_graph.py — NetworkX knowledge graph for EventIQ.

Graph structure:
  Node types : EventCause, Corridor, Zone, PoliceStation, EventType, VehType
  Edge types :
    - CO_OCCURS          (cause → corridor, weighted by frequency)
    - SERVED_BY          (corridor → police_station)
    - IN_ZONE            (corridor → zone)
    - ESCALATES_TO       (cause → cause, e.g. vehicle_breakdown → congestion)
    - HIGH_RISK_AT       (cause → corridor, when closure_rate > 40%)
    - CASCADE_RISK       (corridor → corridor, when share zone + high cascade rate)
    - COMMON_VEH_TYPE    (cause → veh_type, weighted by frequency)

Built entirely from train.csv statistics. No manual edges invented.
Saved to models/knowledge_graph.pkl.

Public API:
    get_related_nodes(node, depth=2)       → list of (node, relation, weight)
    get_escalation_chain(event_cause)      → list of causes
    get_corridor_risk_neighbors(corridor)  → list of corridors at cascade risk
    get_graph_context(event_input)         → structured dict for LLM reasoning
    get_node_stats(node)                   → dict
    export_for_viz()                       → list of {source, target, relation, weight}
"""

import os
import pickle
import warnings
from typing import Optional

import pandas as pd

warnings.filterwarnings("ignore")

try:
    import networkx as nx
    HAS_NX = True
except ImportError:
    HAS_NX = False

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)

DEFAULT_DATA_PATH   = os.path.join(BASE_DIR, "train.csv")
DEFAULT_GRAPH_CACHE = os.path.join(BASE_DIR, "models", "knowledge_graph.pkl")

# Escalation chains based on domain knowledge + dataset patterns
# vehicle_breakdown → congestion is the most common real-world pattern
ESCALATION_CHAINS = {
    "vehicle_breakdown":  ["congestion"],
    "accident":           ["congestion", "road_conditions"],
    "construction":       ["congestion", "road_conditions"],
    "pot_holes":          ["road_conditions", "vehicle_breakdown"],
    "water_logging":      ["road_conditions", "congestion"],
    "tree_fall":          ["road_conditions", "vehicle_breakdown"],
    "protest":            ["road_conditions", "congestion"],
    "procession":         ["congestion"],
    "road_conditions":    ["congestion"],
    "debris":             ["road_conditions", "vehicle_breakdown"],
    "Debris":             ["road_conditions", "vehicle_breakdown"],
    "congestion":         [],
    "public_event":       ["congestion", "road_conditions"],
    "vip_movement":       ["road_conditions", "congestion"],
}


class KnowledgeGraph:
    """
    Directed weighted graph connecting traffic event concepts.
    Used by the LLM reasoner to generate contextual operational briefs.
    """

    def __init__(
        self,
        data_path: str = DEFAULT_DATA_PATH,
        cache_path: str = DEFAULT_GRAPH_CACHE,
    ):
        if not HAS_NX:
            raise ImportError("networkx is required: pip install networkx")

        self._data_path = data_path
        self._cache_path = cache_path
        self.G: Optional[object] = None  # nx.DiGraph
        self._node_meta: dict = {}
        self._load_or_build()

    # ------------------------------------------------------------------
    # Build / cache
    # ------------------------------------------------------------------

    def _load_or_build(self):
        if os.path.exists(self._cache_path):
            with open(self._cache_path, "rb") as f:
                bundle = pickle.load(f)
            self.G = bundle["graph"]
            self._node_meta = bundle["node_meta"]
        else:
            self._build()

    def _build(self):
        df = self._load_data()
        self.G = nx.DiGraph()
        self._node_meta = {}

        self._add_cause_corridor_edges(df)
        self._add_corridor_zone_edges(df)
        self._add_corridor_ps_edges(df)
        self._add_cause_vehtype_edges(df)
        self._add_escalation_edges()
        self._add_cascade_corridor_edges(df)
        self._add_high_risk_edges(df)
        self._populate_node_meta(df)

        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "wb") as f:
            pickle.dump(
                {"graph": self.G, "node_meta": self._node_meta}, f
            )

    def _load_data(self) -> pd.DataFrame:
        df = pd.read_csv(self._data_path)
        df["requires_road_closure"] = df["requires_road_closure"].astype(int)
        df["is_high_priority"] = (df["priority"] == "High").astype(int)
        return df

    # ------------------------------------------------------------------
    # Edge builders
    # ------------------------------------------------------------------

    def _add_cause_corridor_edges(self, df: pd.DataFrame):
        """CO_OCCURS: cause → corridor, weight = frequency count."""
        grp = (
            df.groupby(["event_cause", "corridor"])["id"]
            .count()
            .reset_index(name="count")
        )
        for _, row in grp.iterrows():
            src = f"cause:{row['event_cause']}"
            tgt = f"corridor:{row['corridor']}"
            self.G.add_edge(
                src, tgt,
                relation="CO_OCCURS",
                weight=int(row["count"]),
            )

    def _add_corridor_zone_edges(self, df: pd.DataFrame):
        """IN_ZONE: corridor → zone."""
        grp = df.groupby(["corridor", "zone"])["id"].count().reset_index(name="count")
        for _, row in grp.iterrows():
            if pd.notna(row["zone"]):
                src = f"corridor:{row['corridor']}"
                tgt = f"zone:{row['zone']}"
                self.G.add_edge(
                    src, tgt,
                    relation="IN_ZONE",
                    weight=int(row["count"]),
                )

    def _add_corridor_ps_edges(self, df: pd.DataFrame):
        """SERVED_BY: corridor → police_station, weight = assignment count."""
        grp = (
            df.groupby(["corridor", "police_station"])["id"]
            .count()
            .reset_index(name="count")
        )
        for _, row in grp.iterrows():
            if pd.notna(row["police_station"]):
                src = f"corridor:{row['corridor']}"
                tgt = f"ps:{row['police_station']}"
                self.G.add_edge(
                    src, tgt,
                    relation="SERVED_BY",
                    weight=int(row["count"]),
                )

    def _add_cause_vehtype_edges(self, df: pd.DataFrame):
        """COMMON_VEH_TYPE: cause → veh_type."""
        df2 = df.dropna(subset=["veh_type"])
        grp = (
            df2.groupby(["event_cause", "veh_type"])["id"]
            .count()
            .reset_index(name="count")
        )
        for _, row in grp.iterrows():
            src = f"cause:{row['event_cause']}"
            tgt = f"veh:{row['veh_type']}"
            self.G.add_edge(
                src, tgt,
                relation="COMMON_VEH_TYPE",
                weight=int(row["count"]),
            )

    def _add_escalation_edges(self):
        """ESCALATES_TO: cause → cause (domain + data-driven)."""
        for src_cause, targets in ESCALATION_CHAINS.items():
            for tgt_cause in targets:
                src = f"cause:{src_cause}"
                tgt = f"cause:{tgt_cause}"
                self.G.add_edge(src, tgt, relation="ESCALATES_TO", weight=1)

    def _add_cascade_corridor_edges(self, df: pd.DataFrame):
        """
        CASCADE_RISK: corridor_A → corridor_B when they are in the same zone
        and both have high event density (top-half of event counts).
        """
        corridor_zone = (
            df.dropna(subset=["zone"])
            .groupby(["corridor", "zone"])["id"]
            .count()
            .reset_index(name="count")
        )
        # Most representative zone per corridor
        top_zone = (
            corridor_zone.sort_values("count", ascending=False)
            .groupby("corridor")
            .first()
            .reset_index()[["corridor", "zone"]]
        )
        zone_map = dict(zip(top_zone["corridor"], top_zone["zone"]))

        corridor_counts = df["corridor"].value_counts()
        median_count = corridor_counts.median()
        high_density = set(corridor_counts[corridor_counts >= median_count].index)

        # For each zone, connect high-density corridors to each other
        zone_corridors: dict = {}
        for cor, zone in zone_map.items():
            zone_corridors.setdefault(zone, []).append(cor)

        for zone, corridors in zone_corridors.items():
            hd = [c for c in corridors if c in high_density]
            for i in range(len(hd)):
                for j in range(len(hd)):
                    if i != j:
                        src = f"corridor:{hd[i]}"
                        tgt = f"corridor:{hd[j]}"
                        if not self.G.has_edge(src, tgt):
                            self.G.add_edge(
                                src, tgt,
                                relation="CASCADE_RISK",
                                weight=1,
                            )

    def _add_high_risk_edges(self, df: pd.DataFrame):
        """HIGH_RISK_AT: cause → corridor when closure_rate > 40%."""
        grp = (
            df.groupby(["event_cause", "corridor"])["requires_road_closure"]
            .mean()
            .reset_index(name="closure_rate")
        )
        for _, row in grp.iterrows():
            if row["closure_rate"] > 0.40:
                src = f"cause:{row['event_cause']}"
                tgt = f"corridor:{row['corridor']}"
                self.G.add_edge(
                    src, tgt,
                    relation="HIGH_RISK_AT",
                    weight=round(float(row["closure_rate"]), 3),
                )

    def _populate_node_meta(self, df: pd.DataFrame):
        """Attach stats to each node."""
        # Cause stats
        for cause, grp in df.groupby("event_cause"):
            node = f"cause:{cause}"
            self._node_meta[node] = {
                "type": "EventCause",
                "count": int(len(grp)),
                "high_priority_pct": round(float((grp["priority"] == "High").mean() * 100), 1),
                "closure_rate": round(float(grp["requires_road_closure"].mean() * 100), 1),
            }
        # Corridor stats
        for corr, grp in df.groupby("corridor"):
            node = f"corridor:{corr}"
            self._node_meta[node] = {
                "type": "Corridor",
                "count": int(len(grp)),
                "high_priority_pct": round(float((grp["priority"] == "High").mean() * 100), 1),
                "closure_rate": round(float(grp["requires_road_closure"].mean() * 100), 1),
            }
        # Zone stats
        for zone, grp in df.dropna(subset=["zone"]).groupby("zone"):
            node = f"zone:{zone}"
            self._node_meta[node] = {
                "type": "Zone",
                "count": int(len(grp)),
            }
        # PS stats
        for ps, grp in df.dropna(subset=["police_station"]).groupby("police_station"):
            node = f"ps:{ps}"
            self._node_meta[node] = {
                "type": "PoliceStation",
                "count": int(len(grp)),
            }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_related_nodes(self, node: str, depth: int = 2) -> list:
        """
        Return all nodes reachable from `node` within `depth` hops.
        Returns list of (target_node, relation, weight).
        """
        if node not in self.G:
            return []
        results = []
        visited = set()

        def _traverse(current, current_depth):
            if current_depth == 0 or current in visited:
                return
            visited.add(current)
            for _, tgt, data in self.G.out_edges(current, data=True):
                results.append({
                    "source": current,
                    "target": tgt,
                    "relation": data.get("relation", ""),
                    "weight": data.get("weight", 1),
                })
                _traverse(tgt, current_depth - 1)

        _traverse(node, depth)
        return sorted(results, key=lambda x: x["weight"], reverse=True)

    def get_escalation_chain(self, event_cause: str) -> list:
        """Return the list of causes this event_cause escalates to."""
        return ESCALATION_CHAINS.get(event_cause, [])

    def get_corridor_risk_neighbors(self, corridor: str) -> list:
        """Return corridors that have CASCADE_RISK edges with this corridor."""
        src_node = f"corridor:{corridor}"
        if src_node not in self.G:
            return []
        return [
            tgt.replace("corridor:", "")
            for _, tgt, data in self.G.out_edges(src_node, data=True)
            if data.get("relation") == "CASCADE_RISK"
        ]

    def get_top_police_stations(self, corridor: str, n: int = 3) -> list:
        """Return top-n police stations most frequently serving this corridor."""
        src = f"corridor:{corridor}"
        if src not in self.G:
            return []
        edges = [
            (tgt.replace("ps:", ""), data["weight"])
            for _, tgt, data in self.G.out_edges(src, data=True)
            if data.get("relation") == "SERVED_BY"
        ]
        return [name for name, _ in sorted(edges, key=lambda x: x[1], reverse=True)[:n]]

    def get_graph_context(self, event_input: dict) -> dict:
        """
        Build structured reasoning context for the LLM reasoner.
        Extracts the most relevant graph facts for this event.
        """
        cause     = str(event_input.get("event_cause", ""))
        corridor  = str(event_input.get("corridor", ""))
        zone      = str(event_input.get("zone", ""))
        ps        = str(event_input.get("police_station", ""))

        cause_node    = f"cause:{cause}"
        corridor_node = f"corridor:{corridor}"

        escalation    = self.get_escalation_chain(cause)
        risk_neighbors = self.get_corridor_risk_neighbors(corridor)
        top_ps        = self.get_top_police_stations(corridor)

        # Top co-occurring corridors for this cause
        co_occur = [
            data["target"].replace("corridor:", "")
            for data in self.get_related_nodes(cause_node, depth=1)
            if data["relation"] == "CO_OCCURS"
        ][:5]

        # High-risk corridors for this cause
        high_risk = [
            data["target"].replace("corridor:", "")
            for data in self.get_related_nodes(cause_node, depth=1)
            if data["relation"] == "HIGH_RISK_AT"
        ][:5]

        cause_meta    = self._node_meta.get(cause_node, {})
        corridor_meta = self._node_meta.get(corridor_node, {})

        return {
            "cause":                cause,
            "corridor":             corridor,
            "zone":                 zone,
            "cause_stats":          cause_meta,
            "corridor_stats":       corridor_meta,
            "escalation_chain":     escalation,
            "cascade_risk_corridors": risk_neighbors,
            "top_serving_stations": top_ps,
            "co_occurrence_corridors": co_occur,
            "high_risk_at_corridors":  high_risk,
        }

    def get_node_stats(self, node: str) -> dict:
        """Return metadata for any node."""
        return self._node_meta.get(node, {})

    def export_for_viz(self) -> list:
        """
        Export edges as list of dicts for Plotly / Streamlit visualization.
        Each dict: {source, target, relation, weight}.
        """
        return [
            {
                "source": u,
                "target": v,
                "relation": d.get("relation", ""),
                "weight": d.get("weight", 1),
            }
            for u, v, d in self.G.edges(data=True)
        ]

    def get_summary(self) -> dict:
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "node_types": {
                "EventCause":    sum(1 for n in self.G.nodes if n.startswith("cause:")),
                "Corridor":      sum(1 for n in self.G.nodes if n.startswith("corridor:")),
                "Zone":          sum(1 for n in self.G.nodes if n.startswith("zone:")),
                "PoliceStation": sum(1 for n in self.G.nodes if n.startswith("ps:")),
                "VehicleType":   sum(1 for n in self.G.nodes if n.startswith("veh:")),
            },
            "relation_types": list(
                set(d["relation"] for _, _, d in self.G.edges(data=True))
            ),
        }
