"""
app.py — EventIQ Streamlit Command Center
AI-Powered Supervisory Traffic Command Agent for Bangalore Traffic Police
"""

import os
import sys
import json
import warnings
import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="EventIQ — Traffic Command",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "EventIQ — Gridlock Hackathon 2026"},
)

# ── Load CSS ────────────────────────────────────────────────────────────────
_CSS_PATH = os.path.join(os.path.dirname(__file__), "assets", "style.css")
if os.path.exists(_CSS_PATH):
    with open(_CSS_PATH) as _f:
        st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ── Dataset constants ────────────────────────────────────────────────────────
_EVENT_CAUSES = [
    "accident", "congestion", "construction", "debris", "Debris",
    "Fog / Low Visibility", "others", "pot_holes", "procession",
    "protest", "public_event", "road_conditions", "test_demo",
    "tree_fall", "vehicle_breakdown", "vip_movement", "water_logging",
]
_CORRIDORS = [
    "Non-corridor", "Mysore Road", "Bellary Road 1", "Bellary Road 2",
    "Bannerghata Road", "Old Madras Road", "Airport New South Road",
    "Hosur Road", "Outer Ring Road East", "Tumkur Road", "Magadi Road",
    "CBD 1", "CBD 2", "West of Chord Road", "Domlur Flyover",
    "Silk Board Junction", "KR Puram Bridge", "Bannerghatta Road New",
    "Sarjapur Road", "Hennur Road", "Kanakapura Road", "Electronic City",
]
_ZONES = [
    "Central Zone 1", "Central Zone 2", "East Zone 1", "East Zone 2",
    "North Zone 1", "North Zone 2", "South Zone 1", "South Zone 2",
    "West Zone 1", "West Zone 2",
]
_VEH_TYPES = [
    "auto", "bmtc_bus", "heavy_vehicle", "ksrtc_bus", "lcv",
    "others", "private_bus", "private_car", "taxi", "truck",
]

# ── Searchable autocomplete lists ────────────────────────────────────────────
# Police stations — exact values from train.csv (case-preserved, searchable)
_POLICE_STATIONS = sorted([
    "Adugodi", "Ashok Nagar", "Banashankari", "Banaswadi", "Basavanagudi",
    "Bellandur", "Byatarayanapura", "Chamarajpet", "Chikkabanavara", "Chikkajala",
    "City Market", "Cubbon Park", "Devanahalli Airport", "Electronic City",
    "HAL Old Airport", "HSR Layout", "Halasur", "Halasuru Gate", "Hebbala",
    "Hennuru", "High ground", "Hulimavu", "J.P. Nagar", "Jalahalli", "Jayanagara",
    "Jeevanbheemanagar", "Jnanabharathi", "K.G. Halli", "K.R. Pura", "K.S. Layout",
    "Kamakshipalya", "Kengeri", "Kodigehalli", "Madiwala", "Magadi Road",
    "Mahadevapura", "Malleshwaram", "Mico Layout", "No Police Station", "Peenya",
    "Pulikeshinagar(F.Town)", "R.T. Nagar", "Rajajinagar", "Sadashivanagar",
    "Sheshadripuram", "Shivajinagar", "Thalagattapura", "Upparpet",
    "V.V.Puram (C.Pet)", "Vijayanagara", "Whitefield", "Wilson Garden",
    "Yelahanka", "Yeshwanthpura",
], key=str.lower)

# Junctions — all 294 unique values from train.csv (case-insensitive sorted)
_JUNCTIONS = sorted([
    "17th Mn 1st Crs Aishwarya Stores Jn", "27th Cross Jayanagar(Ganapathi Temple)",
    "28thMainJayanagarJunc", "29thMainRdBTM LayoutJunc", "5thMainHSR",
    "5thMainRPC Layout-Vijayanagar", "A S CharStreet-MysoreRdJunc", "ASC Junction",
    "AdugodiJunc", "AgaraJunction", "AnandRaoJunction", "AnepalyaJunc",
    "AnilKumbleCircle", "AnjaneyaTempleJunc", "ArakereGateJunc", "Arbindo Circle",
    "Arts&CraftsCircle", "AshirwadamCircle", "Ashoknagar Junction(ShoolayCircle)",
    "AttiguppeCircleJunction", "AyyappaTempleJunc", "BDA Junctio-Koramangala",
    "BEL Circle", "BEML GateJunc(SuranjandasRd)", "BHEL Gate",
    "BM ShriJunc(CMH-100FtRd)Junc", "BMTCJunction-K H Road", "BTM16thMain-ORR Junc",
    "BagalakunteCrossJunction", "BagalurCrossJunc", "Bamboobazar(Shivajinagar)",
    "BanashankariBusStandJunc", "BangaloreBodyBuildersJunc", "Basappa Circle Junction",
    "BasavamantapaJunc-Dr RajkumarRd", "BasaweshwaraCircle",
    "Basveshwarnagar 8th main Junction", "Batrayanapura(Amrutahalli)Junction",
    "BegumMahalJunc", "Bellandur Junction, Outer ring road", "BhadrappaLayout",
    "BhashyamCircle", "BhashyamCircle-SadashivNagar", "BigBazaar(Whitefield)Junc",
    "BigBazaarJunction(OldMadrasRd)", "BilekahalliJunc", "BinnyMillJunction",
    "BiryandCircle", "BloodBankCircle", "Bommanahalli", "BrigadeMillenium",
    "BucheryJunction", "CID-CarltonHouseJunc", "CIL CrossJunction-JayamahalRd",
    "CMH Rd-AdarshTheaterJunc", "CMP GateJunc", "CashPharmacyJunction",
    "ChandraLayoutJunc-nearWaterTank", "ChandrikaJunction",
    "ChaudrayaCircle/UdayaTVCircle(CantonmentJunc)", "Chokasandra (Tumkur road)",
    "CholurpalyaJunction(MagadiRd)", "CoffeeBoardJunc", "ColesParkJunc",
    "CommandoHospitalJunc", "D'SouzaCircle", "DMRoadJunc(Basavanagudi)", "DairyCircle",
    "Delmia-Jayanagar", "Devanahalli new bus stand", "DevanahallicrossJunc",
    "DevangaHostelJunction", "Devasandra(k r puram)", "DevegowdaPetrolBunkJunc",
    "Deverabeesanahalli-ORR Junc", "DhobiGhatJunc", "DickensonRd-AdigasJunc",
    "DoddaballapuraCrossJunc", "DomlurWaterTank", "Dr RajkumarRd-10thCrossRdJunc",
    "EGL-ITPL Road Junction", "EagleBridgeJunc", "Egl Circle(Domlur)",
    "ElectronicCityFlyoverJunc", "ESIHospitalJunc", "FosterRdJunc",
    "FrazerTownJunction", "GandhiNagarJunc", "GolfCourseJunc", "GovtSoapFactoryJunc",
    "GreenglensAptJunc", "HMTBusStopJunc-TumkurRd", "HSBCBankJunc(BrigadeRd)",
    "HarlurCrossJunc", "HealingTouchHospitalJunc", "Hebbal FlyoverJunc",
    "HMT ChalJunction", "HodiJunction", "HorseleyHillsJunc", "HosurRd-BommanahalliFlyoverJunc",
    "ICICI ATM-MysoreRdJunc", "ITI ColonyJunc", "IIMB Gate Junc",
    "ITC HotelJunc(WindsorManorJunc)", "IndirangarBusStandJunc",
    "InnisfreeHotelJunc(BrigadeRd)", "JCRoadJunctionNearAnandRao",
    "JMFCCourtJunc(MysoreRd)", "JPMorganJunc(ItplRd)", "JagaraJunc",
    "JakkurCrossJunc", "JakkurJunc", "JayamahalExtJunc", "JayanagarShopping ComplexJunc",
    "JayanagarWaterTankJunc", "JunctionBrigadeRd-ResidencyRd", "KHBColony(BannerghattaRd)",
    "KPCLayoutCrossJunc", "KadenahallicrossJunction", "KalasipalyamJunc",
    "KanakanapalaCrossJunc", "KaveriBridgeJunc(Kanakapalya)", "KempegowdaBusStation",
    "KengeriJunc", "KirloskarsJunc", "KodigehalliBusStopJunc",
    "KoramangalaFireStation", "KoramangalaInnerRingRdJunc", "KramangalaJunc",
    "LalbaughWestGate", "LakshmiDevi Nagar Junc", "Lavelle Rd-MG Rd Junc",
    "LineupJunction(ByrasandraJunc)", "LothianRd Cross", "LotusHospitalJunc",
    "MCEGateJunc(OldMadrasRd)", "MESJunc(MalleswaramJunc)", "MGRoad MetroStation",
    "MS RamaiaHospitalJunc", "MadhavanparkJunction", "MadhuvanasJunc",
    "MagadiRdJunc(ChikkabidarakalluJunc)", "MajesticBusStandJunc",
    "MajesticJunc(CitizenHotelJunc)", "MalleswarmJunc(SampangiRamaJunc)",
    "MalligeswaraTempleJunc(Rajajinagar)", "MarenhalliJunc",
    "MarketRd-NandidurgaRdJunc", "MavensTechparkJunc", "MavensTechPark2Junc",
    "MinskSquareJunc", "MorgansGateJunc", "MysoreRd-MagadiRdJunc",
    "NagarbhaviCircle", "NagarbhaviJunc", "NandidurgaRdJunc(Benson Town)",
    "NatarajaCircle(KGHalli)", "NayandahalliJunc", "NearMysoreRdFlyoverJunc",
    "NetigaJunction(Byresandra)", "NewAirportRdJunc", "NewBEL Road Junc",
    "NewTippasandraJunc", "NiranjanaMurthyCircle(BanashankariJunc)",
    "NorthEndCircleJunc(Rajajinagar)", "OMBR LayoutJunc", "ORRDevarabeesanahalli",
    "OldMadrasRd-InnerbeltRdJunc", "OldMadrasRdJunc(KRPura)", "OutputJunc(Hebbal)",
    "PESUniversityJunc", "PVRCinema(OrionMall)Junc", "PadmanabhanagarkJunc",
    "PallikaranaiJunc", "PeenyaIndAreaJunc", "PintosCrossJunc",
    "PoliceBhavanaJunc(KRRd)", "PrasannaJunc(BasavanagudiJunc)",
    "PrimroseRdJunc(MG Rd-Museum Rd)", "Priyadarshini Junction(VVPuram)",
    "RMVExtJunc", "RNS MotorsJunc(YeshwanthpuraJunc)", "RV CollegeJunc",
    "RaghavendaraSwamyMuttJunc(Jayanagar)", "RailwayStationRd(NearSBC)",
    "RajajinagarlJunc(MilJunc)", "RajarajeshwariNagarJunc", "RamamurthyNagarJunc",
    "RampuraCrossJunc", "RejendranagarkJunc", "ResidencyRdJunc",
    "RicesBankJunc(MysoreRd)", "RichardsTownJunc", "RoopenaAgraharaJunc",
    "RosaryChurchJunc(DevangPet)", "SBM ColonyJunc", "SGS ColonyJunc",
    "SK GardenJunc", "SKoil RdJunc(Rajajinagar)", "SVP LayoutJunc",
    "SadashivaNagarPoliceStationJunc", "SamarthaJunc", "SandalwoodHotelJunc",
    "SatelliteRdJunc(Nayandahalli)", "SathyaSaiAshramJunc", "SatyaSaiLayout",
    "ShekarCircle(NimhansCrossJunc)", "SilkBoardJunction", "SomeshwaraCircle",
    "SomeshwaraTempleJunction(Ulsoor)", "SriRamaTempleCrossJunc",
    "StAnnesCollageJunc", "SubhashnagarJunc(YeshwanthpuraIndustrialArea)",
    "SudamaChowkJunc", "Sunder RamJunc(BrigadeRd)", "SuranjandasRdJunc(Kammanahalli)",
    "TGHalliJunc(TumkurRd)", "TilaknagarkJunction", "TinFactoryJunc(OldMadrasRd)",
    "TogorecrossJunc", "TrinityCircle", "TrinityHospitalJunc", "TulsiramamJunc",
    "UlsoorLakeJunc", "UlsoorRdJunc", "UnnatiNagarkJunc",
    "VaniVilas Rd Junc(Ananda Rao)", "VidyapeethaJunc(Rajajinagar)",
    "VidyaranyapuraCrossJunc", "VijayaBankColonyJunc", "VijayashreeNagarJunc",
    "VijaynagarJunc(KamachiHospital)", "VivekaNandaCircle", "WhitefieldMainJunc",
    "WoodlandsHotelJunc(ResidencyRd)", "YadavagirikJunc",
    "YelahankaCrossRdJunc", "YeshwanthpuraCircle",
], key=str.lower)

# Famous Bangalore landmarks for address autocomplete
_BLR_LANDMARKS = sorted([
    # Major junctions & flyovers
    "Silk Board Junction", "Hebbal Flyover", "KR Pura Bridge", "Electronic City Flyover",
    "Domlur Flyover", "Cauvery Junction (Mysore Road)", "Tin Factory Junction",
    # Malls & commercial
    "Orion Mall, Rajajinagar", "Phoenix Marketcity, Whitefield", "Forum Mall, Koramangala",
    "UB City Mall, MG Road", "Garuda Mall, MG Road", "Mantri Square, Malleshwaram",
    "Indiranagar 100 Feet Road", "Brigade Road", "MG Road, Bangalore",
    # Tech parks & IT hubs
    "ITPL, Whitefield", "Manyata Tech Park, Hebbal", "Embassy Tech Village, Bellandur",
    "RMZ Infinity, Old Madras Road", "Bagmane Tech Park, CV Raman Nagar",
    "Global Village Tech Park", "Prestige Tech Park, Outer Ring Road",
    # Hospitals
    "Manipal Hospital, HAL Airport Road", "Narayana Health City, Bommasandra",
    "Nimhans, Hosur Road", "Victoria Hospital, KR Market", "KIMS, Banashankari",
    # Educational institutions
    "IISc, Malleswaram", "IIM Bangalore, Bannerghatta Road",
    "RV College of Engineering, Mysore Road", "PESIT, Banashankari",
    # Railway & transit
    "Kempegowda Bus Station (Majestic)", "Yeshwanthpura Railway Station",
    "KR Market Metro Station", "Indiranagar Metro Station", "Banashankari Metro Station",
    "Baiyappanahalli Metro Station", "Byappanahalli Railway Station",
    "Whitefield (Kadugodi) Metro Station",
    # Famous circles & areas
    "Anil Kumble Circle", "Trinity Circle, MG Road", "Town Hall Circle",
    "Mekhri Circle, Sadashivnagar", "Chalukya Circle, Race Course Road",
    "Sankey Road, Sadashivnagar", "Palace Road, Bangalore",
    "Jayanagar 4th Block", "Koramangala 5th Block", "HSR Layout Sector 4",
    "BTM Layout", "JP Nagar", "Bannerghatta Road", "Outer Ring Road, Marathahalli",
    "Marathahalli Bridge", "Sarjapur Road Junction", "Kanakapura Road",
    "Tumkur Road", "Mysore Road, Kengeri", "Old Madras Road",
    "Hennur Road Junction", "Bellary Road, Hebbal",
    # Airports
    "Kempegowda International Airport, Devanahalli",
    "HAL Airport, Varthur Road",
], key=str.lower)

# ── Cached loaders ──────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Loading EventIQ models…")
def _get_agent():
    from modules.supervisory_agent import SupervisoryAgent
    return SupervisoryAgent()

@st.cache_data(ttl=600, show_spinner=False)
def _get_weather(lat, lon):
    from modules.weather import get_weather_impact, get_forecast
    return get_weather_impact(lat, lon), get_forecast(lat, lon, hours=6)

@st.cache_data(ttl=3600, show_spinner=False)
def _get_hotspots():
    from modules.heatmap import get_hotspot_corridors
    return get_hotspot_corridors(5)

# ── Helpers ──────────────────────────────────────────────────────────────────
def _risk_color(level: str) -> str:
    return {"Low": "#2ecc71", "Medium": "#f39c12", "High": "#e74c3c", "Critical": "#8e44ad"}.get(level, "#7f8c8d")

def _risk_emoji(level: str) -> str:
    return {"Low": "🟢", "Medium": "🟡", "High": "🔴", "Critical": "🟣"}.get(level, "⚪")

def _fmt_score(score: float) -> str:
    return f"{score:.1f}"

def _render_html(html: str):
    st.markdown(html, unsafe_allow_html=True)

def _score_gauge(score: float, risk: str) -> go.Figure:
    color = _risk_color(risk)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"suffix": "/100", "font": {"size": 28, "color": color, "family": "JetBrains Mono"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#8b949e", "tickwidth": 1},
            "bar": {"color": color, "thickness": 0.3},
            "bgcolor": "#161b22",
            "bordercolor": "#30363d",
            "steps": [
                {"range": [0, 40],   "color": "rgba(46,204,113,0.12)"},
                {"range": [40, 65],  "color": "rgba(243,156,18,0.12)"},
                {"range": [65, 80],  "color": "rgba(231,76,60,0.12)"},
                {"range": [80, 100], "color": "rgba(142,68,173,0.15)"},
            ],
            "threshold": {"line": {"color": color, "width": 3}, "thickness": 0.75, "value": score},
        },
        title={"text": f"Congestion Score<br><span style='color:{color};font-size:11px'>{risk} Risk</span>",
               "font": {"color": "#8b949e", "size": 13}},
    ))
    fig.update_layout(
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font_color="#c9d1d9", height=220, margin=dict(t=40, b=10, l=20, r=20),
    )
    return fig

def _forecast_chart(timeseries: list) -> go.Figure:
    if not timeseries:
        return None
    hours  = [t["label"] for t in timeseries]
    scores = [t["score"] for t in timeseries]
    peaks  = [t["is_peak"] for t in timeseries]

    colors = ["#e74c3c" if p else "#58a6ff" for p in peaks]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=scores,
        mode="lines+markers",
        line=dict(color="#58a6ff", width=2.5),
        marker=dict(color=colors, size=8, line=dict(color="#0d1117", width=1.5)),
        fill="tozeroy",
        fillcolor="rgba(88,166,255,0.07)",
        hovertemplate="<b>%{x}</b><br>Score: %{y:.1f}<extra></extra>",
    ))
    # Peak hour band
    fig.add_hrect(y0=65, y1=100, fillcolor="rgba(231,76,60,0.05)", line_width=0, annotation_text="High Risk Zone", annotation_position="top right")
    fig.update_layout(
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        xaxis=dict(gridcolor="#21262d", showgrid=True, title="Hour"),
        yaxis=dict(gridcolor="#21262d", showgrid=True, title="Score", range=[0, 105]),
        margin=dict(t=20, b=30, l=40, r=10),
        height=200,
        showlegend=False,
        title=dict(text="Congestion Forecast  <span style='color:#e74c3c;font-size:10px'>● peak</span>  <span style='color:#58a6ff;font-size:10px'>● off-peak</span>",
                   font=dict(size=12, color="#8b949e")),
    )
    return fig

def _accuracy_trend_chart(trend: list) -> go.Figure:
    if not trend:
        return None
    weeks  = [t["week"]         for t in trend]
    acc    = [t["accuracy_pct"] for t in trend]
    counts = [t["count"]        for t in trend]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=weeks, y=acc, mode="lines+markers",
        line=dict(color="#58a6ff", width=2),
        marker=dict(size=6),
        name="Priority Accuracy %",
        hovertemplate="Week: %{x}<br>Accuracy: %{y:.1f}%<extra></extra>",
    ))
    fig.add_hline(y=80, line_dash="dot", line_color="#2ecc71", annotation_text="80% target")
    fig.update_layout(
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        xaxis=dict(gridcolor="#21262d"),
        yaxis=dict(gridcolor="#21262d", range=[0, 105], title="Accuracy %"),
        height=220, margin=dict(t=30, b=30, l=40, r=10),
        title=dict(text="Weekly Priority Accuracy Trend", font=dict(size=12, color="#8b949e")),
    )
    return fig

def _calibration_chart(bins: list) -> go.Figure:
    if not bins:
        return None
    labels = [b["bin"]            for b in bins]
    pred   = [b["predicted_mean"] for b in bins]
    actual = [b.get("actual_mean") or 0 for b in bins]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=pred,   name="Predicted", marker_color="#58a6ff", opacity=0.8))
    fig.add_trace(go.Bar(x=labels, y=actual, name="Actual",    marker_color="#2ecc71", opacity=0.8))
    fig.update_layout(
        barmode="group",
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        font=dict(color="#8b949e", size=11),
        xaxis=dict(gridcolor="#21262d", title="Score Bin"),
        yaxis=dict(gridcolor="#21262d", title="Avg Score"),
        height=220, margin=dict(t=30, b=30, l=40, r=10),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        title=dict(text="Score Calibration (Predicted vs Actual)", font=dict(size=12, color="#8b949e")),
    )
    return fig

def _kg_graph(kg_ctx: dict):
    """Render a simple Plotly network for the KG context."""
    import networkx as nx
    G = nx.DiGraph()
    nodes = kg_ctx.get("nodes", [])
    edges = kg_ctx.get("edges", [])
    if not nodes:
        return None
    for n in nodes:
        G.add_node(n.get("id") or n.get("name"), ntype=n.get("type", "?"))
    for e in edges:
        src = e.get("source") or e.get("from")
        tgt = e.get("target") or e.get("to")
        if src and tgt:
            G.add_edge(src, tgt, rel=e.get("relation", ""))

    if len(G.nodes) == 0:
        return None

    pos = nx.spring_layout(G, seed=42, k=1.8)
    type_colors = {
        "EventCause": "#e74c3c", "Corridor": "#f39c12", "Zone": "#3498db",
        "PoliceStation": "#2ecc71", "VehicleType": "#9b59b6",
    }

    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]; x1, y1 = pos[v]
        edge_x += [x0, x1, None]; edge_y += [y0, y1, None]

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_colors = [type_colors.get(G.nodes[n].get("ntype", ""), "#58a6ff") for n in G.nodes()]
    node_labels = list(G.nodes())

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
        line=dict(color="#30363d", width=1), hoverinfo="none"))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=12, color=node_colors, line=dict(color="#0d1117", width=1.5)),
        text=node_labels, textposition="top center",
        textfont=dict(size=9, color="#c9d1d9"),
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=420, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
    )
    return fig


# ════════════════════════════════════════════════════════════════════════════
# Legend helpers
# ════════════════════════════════════════════════════════════════════════════

def _render_risk_legend():
    """Inline horizontal colour legend for risk levels."""
    _render_html("""
    <div class='legend-box'>
        <span class='legend-title'>Risk Level:</span>
        <span class='legend-item' style='background:rgba(46,204,113,0.12);border-color:#2ecc71'>
            <span class='legend-dot' style='background:#2ecc71'></span>Low (0–40)
        </span>
        <span class='legend-item' style='background:rgba(243,156,18,0.12);border-color:#f39c12'>
            <span class='legend-dot' style='background:#f39c12'></span>Medium (41–65)
        </span>
        <span class='legend-item' style='background:rgba(231,76,60,0.12);border-color:#e74c3c'>
            <span class='legend-dot' style='background:#e74c3c'></span>High (66–80)
        </span>
        <span class='legend-item' style='background:rgba(142,68,173,0.15);border-color:#8e44ad'>
            <span class='legend-dot' style='background:#8e44ad'></span>Critical (81–100)
        </span>
    </div>""")


def _render_route_legend():
    """Route card colour legend."""
    _render_html("""
    <div class='legend-box'>
        <span class='legend-title'>Diversion Routes:</span>
        <span class='legend-item' style='border-color:#2ecc71'>
            <span class='legend-swatch' style='background:#2ecc71'></span>✅ Recommended
        </span>
        <span class='legend-item' style='border-color:#f39c12'>
            <span class='legend-swatch' style='background:#f39c12'></span>⚡ Alternate
        </span>
        <span class='legend-item' style='border-color:#e74c3c'>
            <span class='legend-swatch' style='background:#e74c3c;opacity:0.6'></span>🚫 Blocked
        </span>
    </div>""")


def _render_heatmap_legend():
    """Hex heatmap density colour legend."""
    _render_html("""
    <div class='heatmap-legend'>
        <span class='legend-title'>Hex Density:</span>
        <span class='legend-item'><span class='hex-swatch' style='background:#2ecc71'></span>Low</span>
        <span class='legend-item'><span class='hex-swatch' style='background:#f1c40f'></span>Moderate</span>
        <span class='legend-item'><span class='hex-swatch' style='background:#e67e22'></span>High</span>
        <span class='legend-item'><span class='hex-swatch' style='background:#e74c3c'></span>Severe</span>
        <span class='legend-item'><span class='hex-swatch' style='background:#8e44ad'></span>Critical</span>
        <span style='color:#8b949e;font-size:0.72rem;margin-left:8px'>Each cell = aggregated event weight in that area</span>
    </div>""")


def _render_event_detail_panel(ev: dict):
    if not ev:
        return

    status = str(ev.get("status", "active")).title()
    risk   = str(ev.get("risk_level", "Low"))
    score  = ev.get("congestion_score", 0)
    created_at = ev.get("created_at", "—")[:19]
    updated_at = ev.get("updated_at", "—")[:19]
    address = ev.get("address") or ev.get("input_json", {}).get("address") if isinstance(ev.get("input_json"), dict) else ev.get("address")
    address = address or "—"
    police_station = ev.get("police_station") or ev.get("input_json", {}).get("police_station") if isinstance(ev.get("input_json"), dict) else ev.get("police_station")
    police_station = police_station or "—"
    junction = ev.get("junction") or ev.get("input_json", {}).get("junction") if isinstance(ev.get("input_json"), dict) else ev.get("junction")
    junction = junction or "—"
    duration = ev.get("incident_duration_minutes") or ev.get("input_json", {}).get("incident_duration_minutes") if isinstance(ev.get("input_json"), dict) else ev.get("incident_duration_minutes")
    duration = f"{duration} min" if duration not in (None, "", 0) else "Unknown"
    coords = f"{ev.get('latitude', '—')}, {ev.get('longitude', '—')}"

    st.markdown(f"""
    <div class='event-detail-panel'>
      <div class='event-detail-header'>
        <div>
          <div style='font-size:1rem;font-weight:700;color:#c9d1d9'>Event {ev.get('id', '—')} Details</div>
          <div style='font-size:0.88rem;color:#8b949e;margin-top:4px'>Submitted {created_at} · Last updated {updated_at}</div>
        </div>
        <div style='text-align:right'>
          <div class='risk-badge risk-{risk.lower()}' style='font-size:0.9rem;padding:6px 14px'>{risk} Risk</div>
          <div style='margin-top:6px;font-size:0.88rem;color:#58a6ff'>Score {score:.1f}</div>
          <div style='margin-top:4px;font-size:0.85rem;color:#8b949e'>{status}</div>
        </div>
      </div>
      <div class='event-detail-grid'>
        <div><span class='event-detail-label'>Cause</span><div class='event-detail-value'>{ev.get('event_cause', '—')}</div></div>
        <div><span class='event-detail-label'>Type</span><div class='event-detail-value'>{ev.get('event_type', '—')}</div></div>
        <div><span class='event-detail-label'>Address / Landmark</span><div class='event-detail-value'>{address}</div></div>
        <div><span class='event-detail-label'>Police Station</span><div class='event-detail-value'>{police_station}</div></div>
        <div><span class='event-detail-label'>Junction</span><div class='event-detail-value'>{junction}</div></div>
        <div><span class='event-detail-label'>Corridor</span><div class='event-detail-value'>{ev.get('corridor', '—')}</div></div>
        <div><span class='event-detail-label'>Zone</span><div class='event-detail-value'>{ev.get('zone', '—')}</div></div>
        <div><span class='event-detail-label'>Duration</span><div class='event-detail-value'>{duration}</div></div>
        <div><span class='event-detail-label'>Coordinates</span><div class='event-detail-value'>{coords}</div></div>
        <div><span class='event-detail-label'>Authentication</span><div class='event-detail-value'>{ev.get('authenticated', '—')}</div></div>
        <div><span class='event-detail-label'>Road Closure</span><div class='event-detail-value'>{'Yes' if ev.get('requires_road_closure') else 'No'}</div></div>
        <div><span class='event-detail-label'>Priority</span><div class='event-detail-value'>{ev.get('priority') or 'Auto'}</div></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _generate_html_report(d) -> str:
    """Generate a self-contained HTML incident report for download / print-to-PDF."""
    risk_colors = {"Low": "#2ecc71", "Medium": "#f39c12", "High": "#e74c3c", "Critical": "#8e44ad"}
    rc = risk_colors.get(d.risk_level, "#7f8c8d")
    ev = d.event or {}
    rp = d.resource_plan
    dp = d.diversion_plan
    wx = d.weather_ctx or {}
    ts_str = str(d.timestamp)[:19]
    now_str = datetime.datetime.now().strftime("%d %b %Y  %H:%M:%S")

    def _s(v, default="—"):
        return str(v) if v not in (None, "", "None") else default

    # Diversion rows
    div_rows = ""
    if dp and dp.routes:
        for r in dp.routes:
            tag = "✅ Recommended" if r.is_recommended else "⚡ Alternate"
            t = r.weather_adjusted_duration_min or r.duration_in_traffic_min or r.duration_min
            div_rows += f"""
            <tr>
                <td style="color:{'#2ecc71' if r.is_recommended else '#f39c12'}">{tag}</td>
                <td>{r.description}</td>
                <td>Via {r.via}</td>
                <td>{r.distance_km} km</td>
                <td>{t} min</td>
                <td>+{r.delay_vs_normal_min} min</td>
            </tr>"""
    else:
        div_rows = "<tr><td colspan='6' style='color:#888'>No diversion data available</td></tr>"

    # Resource rows
    res_rows = ""
    if rp:
        items = [
            ("👮 Officers", rp.officers_required),
            ("🚧 Barricades", rp.barricades_required),
            ("🚛 Tow Trucks", rp.tow_trucks_required),
            ("🚑 Ambulances", rp.ambulances_suggested),
            ("🔀 Diversion Teams", rp.diversion_teams),
            (f"⏱ Shift Length", f"{rp.shift_hours}h"),
        ]
        for label, val in items:
            res_rows += f"<tr><td>{label}</td><td><b>{val}</b></td></tr>"

    # Timeseries rows
    ts_rows = ""
    if d.timeseries:
        for t in d.timeseries:
            peak_tag = " 🔴" if t.get("is_peak") else ""
            ts_rows += f"<tr><td>{t['label']}</td><td>{t['score']:.1f}{peak_tag}</td></tr>"

    # PS list
    ps_list = ", ".join(
        f"{ps.get('name', '')} ({ps.get('distance_km', 0):.1f} km)"
        for ps in (d.nearest_ps or [])[:4]
    ) or "—"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>EventIQ Incident Report — {ts_str}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; color: #c9d1d9;
         margin: 0; padding: 24px; font-size: 13px; }}
  .page {{ max-width: 960px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg,#161b22,#1a1f2e); border:1px solid #30363d;
             border-left: 5px solid {rc}; border-radius:10px; padding:20px 28px;
             margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; }}
  .logo {{ font-size:1.5rem; font-weight:700; color:#58a6ff; }}
  .subtitle {{ font-size:0.8rem; color:#8b949e; margin-top:3px; }}
  .risk-badge {{ background:{rc}22; border:1px solid {rc}; border-radius:20px;
                 padding:6px 16px; color:{rc}; font-weight:700; font-size:1rem; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px; }}
  .kpi {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
          padding:14px 18px; text-align:center; }}
  .kpi-val {{ font-size:1.6rem; font-weight:700; font-family:monospace; color:{rc}; }}
  .kpi-lbl {{ font-size:0.68rem; color:#8b949e; text-transform:uppercase; letter-spacing:0.8px; margin-top:4px; }}
  .section {{ background:#161b22; border:1px solid #21262d; border-radius:8px;
              padding:16px 20px; margin-bottom:16px; }}
  .section-title {{ font-size:0.72rem; font-weight:600; color:#58a6ff; text-transform:uppercase;
                    letter-spacing:1px; margin-bottom:12px; padding-bottom:6px;
                    border-bottom:1px solid #21262d; }}
  .brief {{ background:#0d1117; border-left:3px solid #58a6ff; border-radius:4px;
            padding:12px 16px; font-size:0.88rem; line-height:1.7; color:#c9d1d9; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.83rem; }}
  th {{ background:#21262d; color:#8b949e; font-size:0.7rem; text-transform:uppercase;
        letter-spacing:0.5px; padding:7px 10px; text-align:left; }}
  td {{ padding:7px 10px; border-bottom:1px solid #21262d; color:#c9d1d9; }}
  tr:last-child td {{ border-bottom:none; }}
  .detail-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
  .detail-item {{ display:flex; justify-content:space-between; padding:5px 0;
                  border-bottom:1px solid #21262d; font-size:0.83rem; }}
  .detail-label {{ color:#8b949e; }}
  .detail-value {{ color:#e6edf3; font-weight:500; }}
  .footer {{ text-align:center; color:#484f58; font-size:0.75rem; margin-top:24px;
             padding-top:16px; border-top:1px solid #21262d; }}
  .alert {{ background:rgba(231,76,60,0.12); border:1px solid rgba(231,76,60,0.4);
            border-radius:6px; padding:10px 14px; color:#e74c3c; margin-bottom:16px; font-weight:500; }}
  @media print {{
    body {{ background:#fff; color:#111; }}
    .header {{ background:#f5f5f5; border-color:#ccc; }}
    .section {{ background:#fafafa; border-color:#ddd; }}
    .kpi {{ background:#f5f5f5; border-color:#ddd; }}
    .kpi-val {{ color:{rc}; }}
    .brief {{ background:#f9f9f9; }}
    th {{ background:#eee; color:#555; }}
    td {{ color:#333; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div>
      <div class="logo">🚦 EventIQ</div>
      <div class="subtitle">AI-Powered Traffic Incident Report · Bangalore Traffic Police</div>
      <div class="subtitle">Generated: {now_str} &nbsp;|&nbsp; Event ID: {_s(d.event_id)}</div>
    </div>
    <div class="risk-badge">{d.risk_level.upper()} RISK</div>
  </div>

  {'<div class="alert">🔴 CRITICAL EVENT — Immediate multi-agency response required. Activate cascade containment protocol.</div>' if d.risk_level == "Critical" else ''}

  <!-- KPIs -->
  <div class="kpis">
    <div class="kpi">
      <div class="kpi-val">{d.congestion_score:.1f}</div>
      <div class="kpi-lbl">Congestion Score /100</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{d.risk_level}</div>
      <div class="kpi-lbl">Risk Level</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{_s(d.priority)}</div>
      <div class="kpi-lbl">Priority</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{d.cascade_prob*100:.0f}%</div>
      <div class="kpi-lbl">Cascade Risk · {_s(d.cascade_severity)}</div>
    </div>
  </div>

  <!-- Event Details -->
  <div class="section">
    <div class="section-title">📌 Event Details</div>
    <div class="detail-grid">
      <div>
        <div class="detail-item"><span class="detail-label">Type</span><span class="detail-value">{_s(ev.get('event_type'))}</span></div>
        <div class="detail-item"><span class="detail-label">Cause</span><span class="detail-value">{_s(ev.get('event_cause'))}</span></div>
        <div class="detail-item"><span class="detail-label">Location</span><span class="detail-value">{_s(ev.get('address', f"{ev.get('latitude','?')}, {ev.get('longitude','?')}"))}</span></div>
        <div class="detail-item"><span class="detail-label">Coordinates</span><span class="detail-value">{_s(ev.get('latitude'))} N, {_s(ev.get('longitude'))} E</span></div>
        <div class="detail-item"><span class="detail-label">Duration</span><span class="detail-value">{_s(ev.get('incident_duration_minutes'))} min</span></div>
      </div>
      <div>
        <div class="detail-item"><span class="detail-label">Corridor</span><span class="detail-value">{_s(ev.get('corridor'))}</span></div>
        <div class="detail-item"><span class="detail-label">Zone</span><span class="detail-value">{_s(ev.get('zone'))}</span></div>
        <div class="detail-item"><span class="detail-label">Junction</span><span class="detail-value">{_s(ev.get('junction'))}</span></div>
        <div class="detail-item"><span class="detail-label">Road Closure</span><span class="detail-value">{'Yes' if ev.get('requires_road_closure') else 'No'}</span></div>
        <div class="detail-item"><span class="detail-label">Nearest Stations</span><span class="detail-value">{ps_list}</span></div>
      </div>
    </div>
  </div>

  <!-- AI Brief -->
  <div class="section">
    <div class="section-title">🤖 AI Operational Brief</div>
    <div class="brief">{d.brief or 'Not available'}</div>
  </div>

  <!-- Weather -->
  <div class="section">
    <div class="section-title">🌤 Weather Context</div>
    <table>
      <tr><th>Condition</th><th>Temperature</th><th>Precipitation</th><th>Wind</th><th>Impact</th><th>Resource Multiplier</th></tr>
      <tr>
        <td>{_s(wx.get('condition'))}</td>
        <td>{_s(wx.get('temperature_c'))}°C</td>
        <td>{_s(wx.get('precipitation_mm'))} mm</td>
        <td>{_s(wx.get('wind_kmh'))} km/h</td>
        <td>{_s(wx.get('severity_label'))}</td>
        <td>×{wx.get('resource_multiplier', 1.0):.2f}</td>
      </tr>
    </table>
  </div>

  <!-- Resources -->
  <div class="section">
    <div class="section-title">👮 Resource Deployment Plan</div>
    {'<table><tr><th>Resource</th><th>Quantity</th></tr>' + res_rows + '</table>' if rp else '<p style="color:#8b949e">Not available</p>'}
    {f'<p style="margin-top:10px;font-size:0.8rem;color:#8b949e">Notes: {chr(10).join(rp.deployment_notes)}</p>' if rp and rp.deployment_notes else ''}
  </div>

  <!-- Diversions -->
  <div class="section">
    <div class="section-title">🛣️ Diversion Routes</div>
    <table>
      <tr><th>Type</th><th>Description</th><th>Via</th><th>Distance</th><th>Duration</th><th>Delay</th></tr>
      {div_rows}
    </table>
  </div>

  <!-- Congestion Forecast -->
  <div class="section">
    <div class="section-title">📈 Congestion Forecast</div>
    <table>
      <tr><th>Hour</th><th>Predicted Score</th></tr>
      {ts_rows if ts_rows else '<tr><td colspan="2" style="color:#888">No forecast data</td></tr>'}
    </table>
  </div>

  <div class="footer">
    EventIQ · Gridlock Hackathon 2026 · Bangalore Traffic Police · Processed in {d.processing_time_ms:.0f}ms · {ts_str}
  </div>
</div>
</body></html>"""
    return html


# ════════════════════════════════════════════════════════════════════════════
# Top Navbar (replaces sidebar)
# ════════════════════════════════════════════════════════════════════════════
def render_top_navbar():
    """Compact status bar at the top — replaces the sidebar."""
    now = datetime.datetime.now()
    weather, _ = _get_weather(12.97, 77.59)
    agent = _get_agent()
    active = agent.get_active_events()
    n_active = len(active)

    sev_color = {"None": "#2ecc71", "Low": "#f39c12",
                 "Moderate": "#e67e22", "Severe": "#e74c3c"}.get(
        weather.get("severity_label", "None"), "#7f8c8d")
    temp = weather.get("temperature_c")
    temp_str = f"{temp}°C" if temp is not None else "--"
    dot_col = "#e74c3c" if n_active else "#2ecc71"
    dot_anim = "animation:blink 2s infinite;" if n_active else ""

    hotspots = _get_hotspots()
    hotspot_html = " &nbsp;·&nbsp; ".join(
        f"<span style='color:#c9d1d9'>{h['corridor'][:18]}</span>"
        f"<span style='color:#8b949e;font-family:monospace;font-size:0.7rem'> ({h['event_count']})</span>"
        for h in hotspots[:3]
    )

    _render_html(f"""
    <div class='top-navbar'>
        <div>
            <div class='top-navbar-logo'>🚦 EventIQ</div>
            <div class='top-navbar-tagline'>AI Traffic Command · Bangalore · Gridlock Hackathon 2026</div>
        </div>
        <div class='top-navbar-items'>
            <div class='navbar-pill'>🕐 {now.strftime('%a %d %b  %H:%M')}</div>
            <div class='navbar-pill' style='border-left:2px solid {sev_color};padding-left:10px'>
                🌤&nbsp;<b>{weather.get('condition', '--')}</b>&nbsp;{temp_str}
                &nbsp;<span style='color:{sev_color}'>{weather.get('severity_label','None')}</span>
            </div>
            <div class='navbar-pill'>
                <span style='display:inline-block;width:8px;height:8px;border-radius:50%;
                    background:{dot_col};{dot_anim}'></span>&nbsp;
                {n_active} Active Event{'s' if n_active != 1 else ''}
            </div>
            <div class='navbar-pill' style='color:#8b949e'>
                🔥 Hotspots: {hotspot_html}
            </div>
        </div>
    </div>""")


def render_sidebar():
    """Legacy sidebar — collapsed by default, kept for reference."""
    with st.sidebar:
        st.caption("EventIQ · Gridlock Hackathon 2026")


# ════════════════════════════════════════════════════════════════════════════
# Tab 1: New Event
# ════════════════════════════════════════════════════════════════════════════
def render_new_event_tab():
    st.markdown("### 🤖 TRAFFIC EVENT")
    _render_risk_legend()

    with st.form("event_form", clear_on_submit=False):

        # ── Row 1: Event identity + location ─────────────────────────────
        c1, c2, c3, c4 = st.columns([1, 2, 1.4, 1.4])
        event_type  = c1.selectbox("Event Type", ["unplanned", "planned"])
        event_cause = c2.selectbox("Event Cause", _EVENT_CAUSES)
        lat = c3.number_input("Latitude",  value=12.9716, format="%.4f", step=0.0001)
        lon = c4.number_input("Longitude", value=77.5946, format="%.4f", step=0.0001)

        # ── Row 2: Address + Corridor + Zone ─────────────────────────────
        ca, cb, cc = st.columns([3, 2, 1.5])
        address = ca.selectbox(
            "📍 Address / Landmark",
            options=[""] + _BLR_LANDMARKS,
            index=0,
            help="Start typing to filter. Select a known Bangalore landmark or leave blank to use coordinates.",
        )
        corridor = cb.selectbox("Corridor", _CORRIDORS)
        zone     = cc.selectbox("Zone",     _ZONES)

        # ── Row 3: Police Station + Junction + Veh Type + Duration ────────
        cp, cj, cv, cd = st.columns([2, 2.5, 1.5, 1.2])
        police_station = cp.selectbox(
            "🚔 Police Station",
            options=_POLICE_STATIONS,
            index=_POLICE_STATIONS.index("Cubbon Park") if "Cubbon Park" in _POLICE_STATIONS else 0,
            help="Type to filter — all 54 Bangalore police stations",
        )
        junction = cj.selectbox(
            "🔀 Junction",
            options=_JUNCTIONS,
            index=_JUNCTIONS.index("AnilKumbleCircle") if "AnilKumbleCircle" in _JUNCTIONS else 0,
            help="Type to filter — 294 junctions from dataset",
        )
        veh_type = cv.selectbox("Vehicle Type", _VEH_TYPES, index=2)
        dur      = cd.number_input("Duration (min)", min_value=0, max_value=720, value=0,
                                   help="0 = unknown")

        # ── Row 4: Flags + Priority + Submit ─────────────────────────────
        cf1, cf2, cf3, cf4 = st.columns([1.2, 1.2, 1.5, 1])
        requires_closure  = cf1.checkbox("🚧 Road Closure Required", value=False)
        authenticated     = cf2.radio("Authenticated", ["yes", "no"], horizontal=True)
        priority_override = cf3.selectbox(
            "Priority Override",
            ["Auto (ML)", "High", "Low"],
            help="Auto lets the ML model decide. Override only if you have confirmed intel.",
        )
        cf4.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
        submitted = cf4.form_submit_button("🚨 Analyse", use_container_width=True, type="primary")

        # ── Optional end location ─────────────────────────────────────────
        with st.expander("📍 End Location — for route/linear events (optional)"):
            ce1, ce2 = st.columns(2)
            end_lat = ce1.number_input("End Latitude",  value=0.0, format="%.4f", step=0.0001)
            end_lon = ce2.number_input("End Longitude", value=0.0, format="%.4f", step=0.0001)

    if submitted:
        # Resolve address: use landmark if selected, else coordinates string
        resolved_address = address if address else f"{lat:.4f}, {lon:.4f}"

        event = {
            "event_type":            event_type,
            "event_cause":           event_cause,
            "latitude":              lat,
            "longitude":             lon,
            "endlatitude":           end_lat if end_lat else None,
            "endlongitude":          end_lon if end_lon else None,
            "address":               resolved_address,
            "corridor":              corridor,
            "zone":                  zone,
            "veh_type":              veh_type,
            "police_station":        police_station,
            "junction":              junction,
            "requires_road_closure": requires_closure,
            "authenticated":         authenticated,
            "priority":              None if priority_override == "Auto (ML)" else priority_override,
            "incident_duration_minutes": dur if dur > 0 else None,
        }

        with st.status("🚦 Running EventIQ analysis…", expanded=True) as status:
            st.write("🔍 Parsing event parameters…")
            st.write("🧠 Running congestion predictor…")
            st.write("🌤 Fetching real-time weather…")
            st.write("👮 Planning resource deployment…")
            st.write("🛣️ Computing diversion routes…")
            st.write("💡 Generating AI operational brief…")
            agent = _get_agent()
            active_evts = agent.get_active_events()
            d = agent.run(event, active_events=active_evts, save=True)
            st.write("💾 Saving to database…")
            status.update(label="✅ Analysis complete!", state="complete", expanded=False)

        st.session_state["last_decision"] = d
        st.session_state["show_decision"] = True

        risk  = d.risk_level
        score = d.congestion_score
        if risk == "Critical":
            st.toast(f"🔴 CRITICAL ALERT: Score {score:.0f}/100 — Deploy all resources immediately!", icon="🚨")
        elif risk == "High":
            st.toast(f"⚠️ HIGH RISK: Score {score:.0f}/100 — Pre-position relief teams.", icon="⚠️")
        elif risk == "Medium":
            st.toast(f"🟡 MEDIUM RISK: Score {score:.0f}/100 — Monitor and prepare response.", icon="🟡")
        else:
            st.toast(f"✅ LOW RISK: Score {score:.0f}/100 — Standard monitoring applies.", icon="✅")
        if d.cascade_prob >= 0.6:
            st.toast(f"⛓️ CASCADE WARNING: {d.cascade_prob*100:.0f}% spread risk to adjacent corridors!", icon="⛓️")

        st.rerun()

    # ── Results below form ────────────────────────────────────────────────────
    st.divider()
    if not st.session_state.get("show_decision"):
        _render_html("""
        <div style='background:#0d1117;border:1px dashed #30363d;border-radius:12px;
                    padding:48px 20px;text-align:center;color:#8b949e'>
            <div style='font-size:2.5rem;margin-bottom:12px'>🚦</div>
            <div style='font-size:1rem;font-weight:500;color:#c9d1d9'>EventIQ Command Center</div>
            <div style='margin-top:8px;font-size:0.85rem'>
                Fill in the form above and click <b style='color:#58a6ff'>🚨 Analyse</b>
                to see the AI decision</div>
        </div>""")
        return

    d = st.session_state["last_decision"]
    render_decision_panel(d)


def render_decision_panel(d):
    """Full decision output for a completed EventDecision."""
    risk_col = _risk_color(d.risk_level)
    risk_em  = _risk_emoji(d.risk_level)

    # ── Download report button (always visible) ───────────────────────────────
    dl_col, _, info_col = st.columns([2, 4, 2])
    report_html = _generate_html_report(d)
    ts_label = str(d.timestamp)[:16].replace(" ", "_").replace(":", "-")
    dl_col.download_button(
        label="📥 Download Report",
        data=report_html,
        file_name=f"eventiq_report_{ts_label}.html",
        mime="text/html",
        use_container_width=True,
        help="Download HTML report — open in browser and print (Ctrl+P) to save as PDF",
    )
    info_col.caption(f"⚡ {d.processing_time_ms:.0f} ms · ID {d.event_id or '—'}")

    # ── 4 KPI metrics ────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Congestion Score", f"{d.congestion_score:.1f}", help="0–100 scaled score")
    m2.metric("Risk Level", f"{risk_em} {d.risk_level}")
    m3.metric("Priority", d.priority,
              delta=f"{d.priority_proba.get(d.priority, 0)*100:.0f}% conf" if d.priority_proba else None)
    cascade_pct = f"{d.cascade_prob*100:.0f}%"
    m4.metric("Cascade Risk", f"{cascade_pct}",
              delta=d.cascade_severity,
              delta_color="inverse" if d.cascade_severity in ("High","Critical") else "normal")

    # Alert banners
    if d.risk_level == "Critical":
        st.markdown("""<div class='alert-banner'>
            🔴 CRITICAL EVENT — Immediate multi-agency response required.
            Activate cascade containment protocol.</div>""", unsafe_allow_html=True)
    elif d.risk_level == "High" and d.cascade_prob >= 0.5:
        st.markdown("""<div class='alert-banner warning'>
            ⚠ HIGH RISK + MODERATE CASCADE — Monitor adjacent corridors.
            Pre-position relief teams.</div>""", unsafe_allow_html=True)
    elif d.risk_level == "High":
        st.markdown("""<div class='alert-banner warning'>
            ⚠ HIGH RISK — Coordinate response with nearest police station.</div>""",
            unsafe_allow_html=True)

    # ── Tabs: Brief | Resources | Diversion | Forecast | Shift | KG | Feedback
    t1, t2, t3, t4, t5, t6, t7 = st.tabs(
        ["📄 Brief", "👮 Resources", "🛣️ Diversion", "📈 Forecast",
         "⏰ Shift Plan", "🧠 Knowledge", "💬 Feedback"]
    )

    # ── Brief ────────────────────────────────────────────────────────────────
    with t1:
        c_gauge, c_brief = st.columns([1, 2])
        with c_gauge:
            st.plotly_chart(_score_gauge(d.congestion_score, d.risk_level),
                            use_container_width=True, config={"displayModeBar": False})
            # Weather
            wx = d.weather_ctx
            if wx:
                sev_c = {"None":"#2ecc71","Low":"#f39c12","Moderate":"#e67e22","Severe":"#e74c3c"}.get(
                    wx.get("severity_label","None"), "#7f8c8d")
                temp  = wx.get("temperature_c")
                st.markdown(f"""
                <div style='background:#161b22;border:1px solid #30363d;border-left:3px solid {sev_c};
                            border-radius:6px;padding:8px 10px;font-size:0.8rem;margin-top:4px'>
                    🌤 <b>{wx.get("condition","--")}</b>
                    {"  " + str(temp) + "°C" if temp is not None else ""}<br>
                    Impact: <span style='color:{sev_c}'>{wx.get("severity_label","None")}</span>
                    &nbsp; Mult: ×{wx.get("resource_multiplier",1.0)}
                </div>""", unsafe_allow_html=True)

            # Nearest PS
            st.markdown("<div style='font-size:0.75rem;color:#8b949e;margin:10px 0 4px;"
                        "text-transform:uppercase;letter-spacing:0.8px'>Nearest Stations</div>",
                        unsafe_allow_html=True)
            for ps in d.nearest_ps[:3]:
                st.markdown(f"<span class='ps-pill'>🚔 {ps.get('name','')} "
                            f"({ps.get('distance_km',0):.1f} km)</span>",
                            unsafe_allow_html=True)

        with c_brief:
            st.markdown("<div style='font-size:0.78rem;color:#8b949e;text-transform:uppercase;"
                        "letter-spacing:0.8px;margin-bottom:8px'>AI Operational Brief</div>",
                        unsafe_allow_html=True)
            st.markdown(f"<div class='brief-box'>{d.brief}</div>",
                        unsafe_allow_html=True)

            if d.score_explanation:
                with st.expander("Why this score?", expanded=False):
                    st.markdown(f"<div style='font-size:0.85rem;color:#c9d1d9;line-height:1.6'>"
                                f"{d.score_explanation}</div>", unsafe_allow_html=True)

            # Historical context
            hp = d.historical_profile
            if hp:
                comp = hp.get("comparison", {})
                with st.expander("Historical Profile", expanded=False):
                    c_h1, c_h2, c_h3 = st.columns(3)
                    c_h1.metric("Past Events", hp.get("total_events", hp.get("count", "?")))
                    c_h2.metric("Closure Rate", f"{float(hp.get('road_closure_rate', hp.get('closure_rate', 0)) or 0)*100:.0f}%")
                    c_h3.metric("Repeat Rate",  f"{float(hp.get('repeat_rate', 0) or 0)*100:.0f}%")
                    if comp:
                        st.caption(f"Comparison: score is {comp.get('vs_mean','?')} vs corridor mean.")

    # ── Resources ────────────────────────────────────────────────────────────
    with t2:
        rp = d.resource_plan
        if rp:
            c_r1, c_r2 = st.columns(2)
            with c_r1:
                st.markdown("#### Deployment Summary")
                rows = [
                    ("👮", "Officers",       rp.officers_required,   "#58a6ff"),
                    ("🚧", "Barricades",     rp.barricades_required, "#f39c12"),
                    ("🚛", "Tow Trucks",     rp.tow_trucks_required, "#e74c3c"),
                    ("🚑", "Ambulances",     rp.ambulances_suggested,"#e74c3c"),
                    ("🔀", "Diversion Teams",rp.diversion_teams,     "#2ecc71"),
                    ("⏱",  "Shift Length",  f"{rp.shift_hours}h",    "#9b59b6"),
                ]
                for icon, label, val, col in rows:
                    st.markdown(f"""
                    <div style='display:flex;justify-content:space-between;align-items:center;
                                padding:8px 0;border-bottom:1px solid #21262d'>
                        <span>{icon} <span style='color:#8b949e;font-size:0.85rem'>{label}</span></span>
                        <span style='font-size:1.2rem;font-weight:700;color:{col};
                                     font-family:monospace'>{val}</span>
                    </div>""", unsafe_allow_html=True)

                if rp.weather_boost_applied:
                    st.info(f"🌧 Weather multiplier ×{rp.resource_multiplier:.2f} applied")
                if rp.cascade_boost_applied:
                    st.warning("🔗 Cascade boost applied — inter-corridor coordination officers included")

            with c_r2:
                st.markdown("#### Deployment Notes")
                for note in rp.deployment_notes:
                    st.markdown(f"• {note}")

                # Weather forecast for shift
                if d.weather_forecast:
                    st.markdown("#### Weather Over Shift")
                    wf_df = pd.DataFrame(d.weather_forecast)[
                        ["hour_label", "temperature_c", "precipitation_mm",
                         "precipitation_prob_pct", "condition"]
                    ].rename(columns={
                        "hour_label": "Hour", "temperature_c": "Temp (°C)",
                        "precipitation_mm": "Rain (mm)",
                        "precipitation_prob_pct": "Rain Prob %",
                        "condition": "Condition",
                    })
                    st.dataframe(wf_df, hide_index=True, use_container_width=True)
        else:
            st.info("Resource plan not available.")

    # ── Diversion ────────────────────────────────────────────────────────────
    with t3:
        dp = d.diversion_plan
        if dp:
            _render_route_legend()
            from modules.diversion_planner import get_diversion_summary
            st.info(get_diversion_summary(dp))
            for route in dp.routes:
                t = route.weather_adjusted_duration_min or route.duration_in_traffic_min or route.duration_min
                card_class = "recommended" if route.is_recommended else "alternate"
                label_text = "✅ RECOMMENDED" if route.is_recommended else "⚡ ALTERNATE"
                label_col  = "#2ecc71" if route.is_recommended else "#f39c12"
                st.markdown(f"""
                <div class='route-card {card_class}' style='margin-bottom:10px'>
                    <div class='route-label' style='color:{label_col}'>{label_text}</div>
                    <div class='route-desc'>{route.description}</div>
                    <div class='route-meta'>
                        Via {route.via} &nbsp;|&nbsp;
                        ~{t} min &nbsp;|&nbsp;
                        {route.distance_km} km &nbsp;|&nbsp;
                        +{route.delay_vs_normal_min} min delay
                        {" &nbsp;|&nbsp; 🌧 weather-adjusted" if route.weather_adjusted_duration_min else ""}
                    </div>
                </div>""", unsafe_allow_html=True)
            if dp.notes:
                for note in dp.notes:
                    st.caption(f"ℹ {note}")
        else:
            st.info("Diversion plan not available.")

    # ── Forecast ─────────────────────────────────────────────────────────────
    with t4:
        if d.timeseries:
            fig = _forecast_chart(d.timeseries)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            df_ts = pd.DataFrame(d.timeseries)[["label", "score", "is_peak"]]
            df_ts["is_peak"] = df_ts["is_peak"].apply(lambda x: "🔴 Yes" if x else "No")
            df_ts.columns = ["Hour", "Score", "Peak Hour"]
            st.dataframe(df_ts, hide_index=True, use_container_width=True)
        else:
            st.info("No timeseries data available.")

    # ── Shift Plan ────────────────────────────────────────────────────────────
    with t5:
        rp = d.resource_plan
        if rp:
            now_h = datetime.datetime.now().hour
            agent = _get_agent()
            waves = agent._get_resource().get_shift_schedule(rp, start_hour=now_h)
            st.markdown("#### 24h Wave Deployment Plan")
            for w in waves:
                st.markdown(f"""
                <div class='wave-card'>
                    <div class='wave-time'>{w["start_time"]}</div>
                    <div>
                        <span class='wave-officers'>Wave {w["wave"]} &nbsp; {w["officers"]} officers</span>
                        <div class='wave-role'>{w["role"]}</div>
                    </div>
                </div>""", unsafe_allow_html=True)

            # Gantt-style severity timeline
            st.markdown("#### Congestion Severity Timeline")
            if d.timeseries:
                ts = d.timeseries
                ts_df = pd.DataFrame(ts)
                fig_g = go.Figure()
                for _, row in ts_df.iterrows():
                    score = row["score"]
                    risk  = "Critical" if score >= 80 else "High" if score >= 65 else "Medium" if score >= 40 else "Low"
                    col   = _risk_color(risk)
                    fig_g.add_trace(go.Bar(
                        x=[row["label"]], y=[score],
                        marker_color=col, showlegend=False,
                        hovertemplate=f"<b>{row['label']}</b><br>Score: {score}<extra></extra>",
                    ))
                fig_g.update_layout(
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#8b949e", size=11),
                    xaxis=dict(gridcolor="#21262d"),
                    yaxis=dict(gridcolor="#21262d", range=[0, 105]),
                    height=180, margin=dict(t=10, b=30, l=40, r=10), barmode="stack",
                )
                st.plotly_chart(fig_g, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Shift plan not available.")

    # ── Knowledge Graph ───────────────────────────────────────────────────────
    with t6:
        kg = d.kg_context
        if kg:
            fig_kg = _kg_graph(kg)
            if fig_kg:
                st.plotly_chart(fig_kg, use_container_width=True, config={"displayModeBar": False})
            esc = kg.get("escalation_chains", kg.get("escalation", []))
            if esc:
                st.markdown(f"**Escalation Path:** {' → '.join(esc)}")
            related = kg.get("related_nodes", [])
            if related:
                st.markdown(f"**Related Nodes:** " + "  ".join(
                    f"`{n.get('name', n.get('id','?'))}`" for n in related[:8]
                ))
        else:
            st.info("Knowledge graph context not available.")

    # ── Feedback ──────────────────────────────────────────────────────────────
    with t7:
        if d.event_id:
            st.markdown("#### Post-Event Operator Feedback")
            st.caption("Submit after the event is resolved to improve future predictions.")
            with st.form("feedback_form"):
                fc1, fc2 = st.columns(2)
                actual_priority   = fc1.selectbox("Actual Priority",   ["High", "Low"])
                actual_risk       = fc2.selectbox("Actual Risk Level",  ["Low", "Medium", "High", "Critical"])
                actual_congestion = st.slider("Actual Congestion Score (0–100)", 0, 100, int(d.congestion_score))
                weather_factor    = st.checkbox("Weather was a major factor in this event")
                outcome           = st.text_area("Outcome Notes (optional)",
                                                 placeholder="What happened, how was it resolved…", height=80)
                fb_submit = st.form_submit_button("Submit Feedback", type="primary")

            if fb_submit and d.event_id:
                try:
                    agent = _get_agent()
                    agent._get_storage().save_feedback(d.event_id, {
                        "actual_priority":   actual_priority,
                        "actual_risk":       actual_risk,
                        "actual_congestion": actual_congestion,
                        "weather_was_factor": int(weather_factor),
                        "outcome":           outcome,
                    })
                    agent.close_event(d.event_id)
                    st.toast("✅ Feedback saved — event closed. Thank you!", icon="✅")
                    st.success("Feedback saved and event marked closed.")
                except Exception as e:
                    st.toast(f"❌ Failed to save feedback: {e}", icon="❌")
                    st.error(f"Failed to save feedback: {e}")
        else:
            st.info("Event must be saved to the database before feedback can be recorded.")


# ════════════════════════════════════════════════════════════════════════════
# Tab 2: Live Map
# ════════════════════════════════════════════════════════════════════════════
def render_map_tab():
    st.markdown("### 🗺️ Live Situation Map")

    # ── Live status bar ───────────────────────────────────────────────────────
    agent = _get_agent()
    active = agent.get_active_events()
    n_active = len(active)
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    dot_col = "#e74c3c" if n_active else "#2ecc71"

    lc1, lc2, lc3, lc4 = st.columns([3, 2, 2, 1])
    lc1.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;padding:6px 0'>"
        f"<span style='width:10px;height:10px;border-radius:50%;background:{dot_col};"
        f"display:inline-block;animation:blink 2s infinite'></span>"
        f"<span style='font-size:0.85rem;color:#c9d1d9'>"
        f"<b>LIVE</b> — {n_active} active event(s) &nbsp;·&nbsp; Last updated: {now_str}"
        f"</span></div>",
        unsafe_allow_html=True,
    )
    if lc4.button("🔄 Refresh", use_container_width=True):
        st.toast("🔄 Map data refreshed!", icon="🗺️")
        st.rerun()

    # ── Note about map behaviour ──────────────────────────────────────────────
    st.caption(
        "ℹ️ The Event Map renders each submitted event with risk-coloured pins and diversion routes. "
        "The Hex Heatmap aggregates 8,158 historical events + live events into density cells. "
        "Click 🔄 Refresh to pull the latest active events."
    )

    # ── Filter bar ────────────────────────────────────────────────────────────
    f1, f2, f3 = st.columns([1, 1, 1])
    cause_f = f1.selectbox("Filter Cause", ["All"] + _EVENT_CAUSES, label_visibility="visible")
    hour_f  = f2.selectbox("Filter Hour",  ["All"] + [str(h) for h in range(24)],
                            label_visibility="visible")
    f3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    weather, _ = _get_weather(12.97, 77.59)
    cause_filter = None if cause_f == "All" else cause_f
    hour_filter  = None if hour_f == "All" else int(hour_f)

    map_tab, heat_tab = st.tabs(["📍 Event Map", "⬡ Hex Heatmap"])

    with map_tab:
        # ── Risk legend ───────────────────────────────────────────────────────
        _render_html("""
        <div class='legend-box'>
            <span class='legend-title'>Pin Colour:</span>
            <span class='legend-item' style='border-color:#2ecc71'>
                <span class='legend-dot' style='background:#2ecc71'></span>Low Risk
            </span>
            <span class='legend-item' style='border-color:#f39c12'>
                <span class='legend-dot' style='background:#f39c12'></span>Medium Risk
            </span>
            <span class='legend-item' style='border-color:#e74c3c'>
                <span class='legend-dot' style='background:#e74c3c'></span>High Risk
            </span>
            <span class='legend-item' style='border-color:#8e44ad'>
                <span class='legend-dot' style='background:#8e44ad'></span>Critical Risk
            </span>
            <span class='legend-item' style='border-color:#2ecc71'>
                <span class='legend-swatch' style='background:#2ecc71'></span>Recommended Route
            </span>
            <span class='legend-item' style='border-color:#f39c12'>
                <span class='legend-swatch' style='background:#f39c12'></span>Alternate Route
            </span>
            <span class='legend-item' style='border-color:#e74c3c'>
                <span class='legend-swatch' style='background:#e74c3c;opacity:0.5'></span>Blocked Corridor
            </span>
        </div>""")

        d = st.session_state.get("last_decision")
        if d:
            from modules.maps import build_event_map
            try:
                from streamlit_folium import st_folium
                fmap = build_event_map(
                    event=d.event,
                    risk_level=d.risk_level,
                    diversion_plan=d.diversion_plan,
                    nearest_ps=d.nearest_ps,
                    weather_ctx=d.weather_ctx,
                )
                st_folium(fmap, use_container_width=True, height=500)
            except ImportError:
                st.markdown(build_event_map(d.event, d.risk_level,
                    d.diversion_plan, d.nearest_ps, d.weather_ctx)._repr_html_(),
                    unsafe_allow_html=True)
        else:
            st.info("Submit an event in the 🚨 New Event tab to see it on the map.")

    with heat_tab:
        _render_heatmap_legend()
        from modules.heatmap import build_hex_heatmap
        try:
            from streamlit_folium import st_folium
            hmap = build_hex_heatmap(
                active_events=active,
                cause_filter=cause_filter,
                hour_filter=hour_filter,
                weather_ctx=weather,
            )
            st_folium(hmap, use_container_width=True, height=520)
        except ImportError:
            from modules.heatmap import build_hex_heatmap_html
            html = build_hex_heatmap_html(
                active_events=active,
                cause_filter=cause_filter,
                hour_filter=hour_filter,
                weather_ctx=weather,
            )
            st.components.v1.html(html, height=520)


# ════════════════════════════════════════════════════════════════════════════
# Tab 3: Active Events
# ════════════════════════════════════════════════════════════════════════════
def render_active_events_tab():
    st.markdown("### 📟 Active Events")
    agent  = _get_agent()
    active = agent.get_active_events()
    recent = agent.get_recent_events(30)

    if not recent:
        st.info("No events in the database yet. Submit an event to get started.")
        return

    # Summary bar
    if recent:
        df_r = pd.DataFrame(recent)
        col_s = st.columns(4)
        col_s[0].metric("Total Logged",   len(recent))
        col_s[1].metric("Active",         len([e for e in recent if e.get("status") == "active"]))
        col_s[2].metric("Critical Risk",  len([e for e in recent if e.get("risk_level") == "Critical"]))
        col_s[3].metric("Avg Score",      f"{df_r['congestion_score'].mean():.1f}" if "congestion_score" in df_r else "?")

    st.divider()

    selected_id = st.session_state.get("selected_event_id")

    for ev in recent[:15]:
        risk    = ev.get("risk_level", "Low")
        risk_c  = _risk_color(risk)
        risk_em = _risk_emoji(risk)
        cause   = str(ev.get("event_cause") or ev.get("event_type") or "event").replace("_", " ").title()
        corr    = ev.get("corridor", "")
        status  = ev.get("status", "active")
        score   = ev.get("congestion_score", 0)
        ts      = ev.get("created_at", "")[:16]
        event_id = ev.get("id")

        dot = '<span class="status-dot dot-active"></span>' if status == "active" else \
              '<span class="status-dot dot-closed"></span>'

        # Layout: [checkbox] [event tile (clickable)]
        col_cb, col_tile = st.columns([0.75, 5.25])
        
        with col_cb:
            if status == "active":
                is_completed = st.checkbox("✓", key=f"complete_{event_id}", value=False, label_visibility="collapsed")
                if is_completed:
                    agent.close_event(event_id)
                    st.session_state.pop("selected_event_id", None)
                    st.rerun()
        
        with col_tile:
            # Check if this event is selected — if so, show detail panel in place of tile
            if selected_id == event_id:
                selected_event = agent.get_event_by_id(event_id)
                if selected_event:
                    # Back button to flip back to tile
                    if st.button("← Back to Events", key=f"detail_back_{event_id}", use_container_width=True, help="Close details"):
                        st.session_state.pop("selected_event_id", None)
                        st.rerun()
                    
                    # Detail panel replaces tile
                    _render_event_detail_panel(selected_event)
            else:
                # Clickable tile — triggers detail view (flip to details)
                if st.button("", key=f"tile_click_{event_id}", use_container_width=True, help="Click to view details"):
                    st.session_state["selected_event_id"] = event_id
                    st.rerun()
                
                # Tile visual
                st.markdown(f"""
                <div class='event-tile {risk.lower()}'>
                    <div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px'>
                        <div>
                            {dot}<b style='color:#e6edf3'>{cause}</b>
                            <span class='risk-badge risk-{risk.lower()}' style='margin-left:8px'>{risk_em} {risk}</span>
                        </div>
                        <div style='font-family:monospace;color:{risk_c};font-size:1.1rem'>{score:.1f}</div>
                    </div>
                    <div style='font-size:0.8rem;color:#8b949e;margin-top:6px'>
                        {corr or 'No corridor'} &nbsp;·&nbsp; ID {event_id} &nbsp;·&nbsp; {ts}
                    </div>
                </div>""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# Tab 4: Analytics
# ════════════════════════════════════════════════════════════════════════════
def render_analytics_tab():
    st.markdown("### 📊 Post-Event Analytics & Learning")

    from modules.post_event_learning import (
        compute_trends, get_delta_cards, get_recent_deltas,
        get_learning_metrics, retrain_models_from_feedback
    )
    from modules.llm_reasoner import summarise_feedback_trends

    trends = compute_trends()
    cards  = get_delta_cards()

    # KPI delta cards
    c_cards = st.columns(len(cards))
    for i, card in enumerate(cards):
        c_cards[i].metric(
            label=card["label"],
            value=card["value"],
            help=card.get("help"),
        )

    st.divider()

    # Learning metrics & retraining section
    st.markdown("#### 🧠 Model Learning & Improvement")
    learning_metrics = get_learning_metrics()
    
    lm_cols = st.columns(4)
    lm_cols[0].metric(
        "Baseline Accuracy",
        f"{learning_metrics['baseline_accuracy_pct']:.0f}%",
        help="Initial model accuracy (corridor lookup)"
    )
    lm_cols[1].metric(
        "Current Accuracy",
        f"{learning_metrics['current_accuracy_pct']:.1f}%",
        help="Accuracy after feedback incorporation"
    )
    improvement = learning_metrics['improvement_pct']
    lm_cols[2].metric(
        "Improvement",
        f"{improvement:+.1f}%",
        help="Percentage improvement over baseline",
        delta_color="off" if improvement < 0 else "normal"
    )
    lm_cols[3].metric(
        "Training Records",
        learning_metrics['total_feedback_records'],
        help="Feedback records used for improvement"
    )
    
    # Retrain button
    col_retrain, col_spacer = st.columns([1, 4])
    with col_retrain:
        if st.button("🔄 Retrain Models", key="retrain_btn", use_container_width=True, help="Retrain models using test.csv + feedback data"):
            with st.spinner("Retraining models from test.csv + feedback..."):
                test_csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.csv")
                retrain_result = retrain_models_from_feedback(test_csv_path=test_csv_path)
                
                if retrain_result['status'] == 'success':
                    st.success(f"""
                    ✅ Models retrained successfully!
                    
                    - **Priority Model Accuracy**: {retrain_result.get('priority_model_accuracy', 0):.1f}%
                    - **Feedback Records Used**: {retrain_result.get('feedback_records_used', 0)}
                    - **Test Records**: {retrain_result.get('test_records', 0)}
                    - **Total Training**: {retrain_result.get('total_training_records', 0)} records
                    - **Improvement**: {retrain_result.get('improvement_pct', 0):+.1f}%
                    
                    Models saved and ready for deployment.
                    """)
                else:
                    st.error(f"❌ Retraining failed: {retrain_result.get('error', 'Unknown error')}")

    st.divider()

    if trends["total_feedback"] == 0:
        st.info("No feedback records yet. Submit events and add feedback to see analytics.")

        # Still show KPI summary from storage
        agent = _get_agent()
        kpi = agent.get_kpi_summary()
        if kpi:
            st.markdown("#### Database KPI Summary")
            ck1, ck2, ck3, ck4 = st.columns(4)
            ck1.metric("Total Events", kpi.get("total_events", 0))
            ck2.metric("Active Events", kpi.get("active_events", 0))
            avg_s = kpi.get("avg_congestion_score")
            ck3.metric("Avg Congestion", f"{avg_s:.1f}" if avg_s else "N/A")
            ck4.metric("High Priority %", f"{kpi.get('high_priority_pct', 0):.0f}%")
        return

    # AI summary
    with st.expander("🤖 AI Learning Summary", expanded=True):
        summary = summarise_feedback_trends(trends)
        st.markdown(f"<div class='brief-box'>{summary}</div>", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)

    # Accuracy trend
    with col_a:
        fig_t = _accuracy_trend_chart(trends.get("weekly_accuracy_trend", []))
        if fig_t:
            st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})

    # Score calibration
    with col_b:
        fig_c = _calibration_chart(trends.get("score_calibration_bins", []))
        if fig_c:
            st.plotly_chart(fig_c, use_container_width=True, config={"displayModeBar": False})

    # Per-corridor breakdown
    corr_acc = trends.get("corridor_accuracy", {})
    if corr_acc:
        st.markdown("#### Per-Corridor Priority Accuracy")
        rows = [{"Corridor": k, "Accuracy %": v["accuracy_pct"], "Events": v["count"]}
                for k, v in sorted(corr_acc.items(), key=lambda x: -x[1]["accuracy_pct"])]
        df_corr = pd.DataFrame(rows)
        fig_bar = px.bar(df_corr, x="Corridor", y="Accuracy %", color="Accuracy %",
                         color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
                         range_color=[0, 100], height=240)
        fig_bar.update_layout(paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                               font=dict(color="#8b949e", size=10),
                               xaxis_tickangle=-30, margin=dict(t=20, b=60, l=40, r=10),
                               coloraxis_showscale=False)
        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})

    # Recent deltas table
    deltas = get_recent_deltas(n=15)
    if deltas:
        st.markdown("#### Recent Predicted vs Actual")
        df_d = pd.DataFrame(deltas)[[
            "event_id", "corridor", "cause", "predicted_priority", "actual_priority",
            "predicted_score", "actual_score", "score_delta", "correct", "created_at"
        ]].rename(columns={
            "event_id": "ID", "predicted_priority": "Pred Priority",
            "actual_priority": "Actual Priority", "predicted_score": "Pred Score",
            "actual_score": "Actual Score", "score_delta": "Δ Score",
            "correct": "Correct", "created_at": "Time",
        })
        st.dataframe(df_d, hide_index=True, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# Tab 5: What-If Simulator
# ════════════════════════════════════════════════════════════════════════════
def render_whatif_tab():
    st.markdown("### 🔬 What-If Simulator")
    st.caption("Adjust scenario parameters and instantly see how the congestion score changes.")

    d = st.session_state.get("last_decision")
    base_event = d.event.copy() if d else {
        "event_type": "unplanned", "event_cause": "accident",
        "latitude": 12.97, "longitude": 77.59,
        "corridor": "Mysore Road", "zone": "Central Zone 2",
        "veh_type": "heavy_vehicle", "police_station": "Cubbon Park",
        "junction": "AnilKumbleCircle", "authenticated": "yes",
        "requires_road_closure": True,
    }

    c_ctrl, c_out = st.columns([2, 3])

    with c_ctrl:
        st.markdown("#### Adjust Parameters")
        sim_cause   = st.selectbox("Event Cause",  _EVENT_CAUSES,
                                    index=_EVENT_CAUSES.index(base_event.get("event_cause","accident")))
        sim_closure = st.checkbox("Road Closure", value=bool(base_event.get("requires_road_closure", True)))
        sim_veh     = st.selectbox("Vehicle Type", _VEH_TYPES,
                                    index=_VEH_TYPES.index(base_event.get("veh_type","heavy_vehicle"))
                                    if base_event.get("veh_type") in _VEH_TYPES else 2)
        sim_hour    = st.slider("Hour of Day", 0, 23, int(base_event.get("hour", 8)))
        sim_corr    = st.selectbox("Corridor", _CORRIDORS,
                                    index=_CORRIDORS.index(base_event.get("corridor","Mysore Road"))
                                    if base_event.get("corridor") in _CORRIDORS else 1)
        run_sim = st.button("⚡ Run Simulation", type="primary", use_container_width=True)

    with c_out:
        if run_sim or "sim_result" in st.session_state:
            if run_sim:
                sim_event = {**base_event,
                    "event_cause": sim_cause, "requires_road_closure": sim_closure,
                    "veh_type": sim_veh, "hour": sim_hour, "corridor": sim_corr,
                }
                from modules.congestion_predictor import CongestionPredictor
                from modules.risk import get_risk_level, get_risk_metadata
                cp = _get_agent()._get_congestion()
                sim_score = cp.predict(sim_event)
                sim_risk  = get_risk_level(sim_score)
                sim_ts    = cp.forecast_timeseries(sim_event)
                st.session_state["sim_result"] = (sim_score, sim_risk, sim_ts, sim_event)

            sim_score, sim_risk, sim_ts, sim_event = st.session_state["sim_result"]
            base_score = d.congestion_score if d else sim_score
            delta = sim_score - base_score

            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Simulated Score", f"{sim_score:.1f}",
                       delta=f"{delta:+.1f}" if d else None,
                       delta_color="inverse")
            sc2.metric("Risk Level", f"{_risk_emoji(sim_risk)} {sim_risk}")
            sc3.metric("vs Baseline", f"{delta:+.1f} pts" if d else "N/A")

            st.plotly_chart(_score_gauge(sim_score, sim_risk),
                            use_container_width=True, config={"displayModeBar": False})

            if sim_ts:
                st.plotly_chart(_forecast_chart(sim_ts),
                                use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Adjust parameters and click **Run Simulation**.")


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════
def main():
    # Init session state
    if "show_decision" not in st.session_state:
        st.session_state["show_decision"] = False

    render_top_navbar()

    # Main tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🚨 New Event",
        "🗺️ Live Map",
        "📟 Active Events",
        "📊 Analytics",
        "🔬 What-If",
    ])

    with tab1:
        render_new_event_tab()

    with tab2:
        render_map_tab()

    with tab3:
        render_active_events_tab()

    with tab4:
        render_analytics_tab()

    with tab5:
        render_whatif_tab()


if __name__ == "__main__":
    main()
