"""
pages/autonomous_analysis.py — Streamlit page for autonomous learning agent analysis.

Displays AI-powered insights and recommendations for unplanned event management.
"""

import os
import sys
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.autonomous_learning_agent import (
    analyze_unplanned_events,
    get_priority_rules,
    get_corridor_risk_profile,
    get_cause_risk_profile,
    predict_priority,
)

# ─────────────────────────────────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Autonomous Analysis",
    page_icon="🤖",
    layout="wide",
)

st.markdown("# 🤖 Autonomous Learning Agent")
st.markdown("**AI-powered analysis engine for unplanned traffic events**")
st.markdown("Learns from historical data to provide actionable insights for police dispatch decisions")

# ─────────────────────────────────────────────────────────────────────────────
# Load Data
# ─────────────────────────────────────────────────────────────────────────────

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
train_csv_path = os.path.join(base_dir, "train.csv")

@st.cache_data
def load_analysis():
    """Load analysis results with caching."""
    return analyze_unplanned_events(train_csv_path)

with st.spinner("🔍 Analyzing unplanned events..."):
    result = load_analysis()

# ─────────────────────────────────────────────────────────────────────────────
# Executive Summary
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
st.markdown("## 📊 Executive Summary")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Total Events",
        f"{result.total_unplanned_events:,}",
        help="Total unplanned events in training data"
    )

with col2:
    high_pct = result.priority_distribution.get('High', 0) / result.total_unplanned_events * 100
    st.metric(
        "High Priority",
        f"{result.priority_distribution.get('High', 0):,}",
        f"{high_pct:.0f}%",
        delta_color="inverse"
    )

with col3:
    low_pct = result.priority_distribution.get('Low', 0) / result.total_unplanned_events * 100
    st.metric(
        "Low Priority",
        f"{result.priority_distribution.get('Low', 0):,}",
        f"{low_pct:.0f}%"
    )

with col4:
    st.metric(
        "Decision Rules",
        len(result.top_rules),
        help="Discovered decision patterns"
    )

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Decision Rules",
    "🛣️ Corridor Analysis",
    "📋 Cause Analysis",
    "⚡ Blind Spots",
    "🔮 Priority Predictor"
])

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: Decision Rules
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    st.markdown("### Top Decision Rules for Priority Prediction")
    st.markdown("These rules are discovered from historical patterns and ranked by reliability (accuracy × support).")
    
    for i, rule in enumerate(result.top_rules[:10], 1):
        with st.expander(
            f"**Rule {i}**: {rule.condition} → {rule.conclusion}",
            expanded=(i <= 3)
        ):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Accuracy", f"{rule.accuracy*100:.1f}%")
            with col2:
                st.metric("Support", f"{rule.support} events")
            with col3:
                st.metric("Confidence", f"{rule.confidence_pct:.0f}%")
            
            st.markdown(f"**Reasoning**: {rule.reasoning}")
    
    st.info("💡 **Key Insight**: Corridor is the dominant factor (99-100% accuracy). Named corridors → High priority; Non-corridor → Low priority.")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 2: Corridor Analysis
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    st.markdown("### Risk Profile by Corridor")
    
    # Corridor statistics
    corridor_stats = []
    for corridor, profile in result.corridor_profiles.items():
        corridor_stats.append({
            "Corridor": corridor,
            "Events": profile.total_events,
            "High%": profile.high_priority_pct,
            "Low%": profile.low_priority_pct,
            "Common Cause": profile.most_common_cause or "N/A",
        })
    
    df_corridors = pd.DataFrame(corridor_stats).sort_values("Events", ascending=False)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Interactive chart
        fig = px.bar(
            df_corridors.head(15),
            x="Corridor",
            y=["High%", "Low%"],
            barmode="group",
            title="Priority Distribution by Top 15 Corridors",
            labels={"value": "Percentage", "variable": "Priority"},
            color_discrete_map={"High%": "#ff6b6b", "Low%": "#51cf66"}
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("**Corridor Statistics**")
        st.dataframe(
            df_corridors[["Corridor", "Events", "High%"]].head(10),
            use_container_width=True,
            hide_index=True
        )
    
    st.markdown("---")
    st.markdown("### Top Risk Corridors")
    for corridor, profile in sorted(result.corridor_profiles.items(), 
                                    key=lambda x: x[1].total_events, 
                                    reverse=True)[:5]:
        with st.expander(f"🛣️ {corridor} ({profile.total_events} events)"):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("High Priority %", f"{profile.high_priority_pct:.1f}%")
            with col2:
                st.metric("Low Priority %", f"{profile.low_priority_pct:.1f}%")
            with col3:
                st.metric("Common Cause", profile.most_common_cause or "N/A")
            
            if profile.highest_risk_combination:
                st.info(f"⚠️ **Highest Risk Combination**: {profile.highest_risk_combination}")
            
            if profile.anomalies:
                for anomaly in profile.anomalies:
                    st.warning(f"🚨 {anomaly}")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 3: Cause Analysis
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    st.markdown("### Risk Profile by Event Cause")
    
    cause_stats = []
    for cause, profile in result.cause_profiles.items():
        cause_stats.append({
            "Cause": cause,
            "Events": profile.total_events,
            "High%": profile.high_priority_pct,
            "Low%": profile.low_priority_pct,
            "% of Total": profile.total_events / result.total_unplanned_events * 100,
        })
    
    df_causes = pd.DataFrame(cause_stats).sort_values("Events", ascending=False)
    
    # Pie chart
    fig_pie = px.pie(
        df_causes,
        names="Cause",
        values="Events",
        title="Event Cause Distribution",
        hole=0.3,
    )
    st.plotly_chart(fig_pie, use_container_width=True)
    
    st.markdown("---")
    st.markdown("### Cause Risk Analysis")
    
    for cause, profile in sorted(result.cause_profiles.items(), 
                                 key=lambda x: x[1].total_events, 
                                 reverse=True)[:8]:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                cause.replace("_", " ").title(),
                f"{profile.total_events}",
                f"{profile.total_events/result.total_unplanned_events*100:.1f}%"
            )
        
        with col2:
            st.markdown(f"**High Priority**: {profile.high_priority_pct:.1f}%")
            st.markdown(f"**Low Priority**: {profile.low_priority_pct:.1f}%")
        
        with col3:
            if profile.anomalies:
                st.warning(f"⚠️ {profile.anomalies[0]}")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 4: Blind Spots
# ─────────────────────────────────────────────────────────────────────────────

with tab4:
    st.markdown("### Identified Blind Spots")
    st.markdown("Scenarios where current rules may systematically fail")
    
    if result.blind_spots:
        for i, spot in enumerate(result.blind_spots, 1):
            with st.expander(f"**Blind Spot {i}**: {spot.scenario}"):
                st.markdown(f"**Expected**: {spot.expected_priority} | **Actual**: {spot.actual_priority}")
                st.metric("Mismatch Rate", f"{spot.mismatch_rate:.1f}%", f"{spot.affected_events} events")
                st.warning(f"**Recommendation**: {spot.recommendation}")
    else:
        st.info("✅ No major blind spots detected. Current rules are stable.")
    
    st.markdown("---")
    st.markdown("### Actionable Insights")
    
    for i, insight in enumerate(result.insights, 1):
        priority_colors = {
            "Critical": "🔴",
            "High": "🟠",
            "Medium": "🟡",
            "Low": "🟢"
        }
        color = priority_colors.get(insight.priority, "⚪")
        
        with st.expander(f"{color} **Insight {i}**: {insight.insight}"):
            st.markdown(f"**Recommendation**: {insight.recommended_action}")
            st.markdown(f"**Scenarios**: {', '.join(insight.affected_scenarios[:3])}")
            st.markdown(f"*Data Support: {insight.data_support}*")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 5: Priority Predictor
# ─────────────────────────────────────────────────────────────────────────────

with tab5:
    st.markdown("### Predict Priority for New Event")
    st.markdown("Use the autonomous agent to predict priority for a hypothetical event")
    
    col1, col2 = st.columns(2)
    
    with col1:
        corridor = st.selectbox(
            "Corridor",
            options=["Non-corridor"] + sorted([c for c in result.corridor_profiles.keys() if c != "Non-corridor"]),
            help="Traffic corridor where event occurred"
        )
        
        event_cause = st.selectbox(
            "Event Cause",
            options=sorted(result.cause_profiles.keys()),
            help="Primary cause of the event"
        )
    
    with col2:
        veh_type = st.selectbox(
            "Vehicle Type",
            options=sorted(result.vehicle_profiles.keys()),
            help="Type of vehicle involved"
        )
    
    if st.button("🔮 Predict Priority"):
        event = {
            "corridor": corridor,
            "event_cause": event_cause,
            "veh_type": veh_type,
        }
        
        priority, confidence, reasoning = predict_priority(event, train_csv_path)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            color = "🔴" if priority == "High" else "🟢"
            st.metric("Predicted Priority", f"{color} {priority}")
        
        with col2:
            st.metric("Confidence", f"{confidence*100:.0f}%")
        
        with col3:
            st.metric("Risk Level", "High" if confidence > 0.8 else "Medium" if confidence > 0.6 else "Low")
        
        st.info(f"**Reasoning**: {reasoning}")
        
        # Show similar historical events
        df_train = pd.read_csv(train_csv_path)
        df_similar = df_train[
            (df_train['corridor'] == corridor) &
            (df_train['event_cause'] == event_cause) &
            (df_train['veh_type'] == veh_type)
        ]
        
        if not df_similar.empty:
            st.markdown("---")
            st.markdown("### Similar Historical Events")
            st.metric(
                "Count",
                len(df_similar),
                f"High Priority: {(df_similar['priority'] == 'High').sum()} ({(df_similar['priority'] == 'High').sum()/len(df_similar)*100:.0f}%)"
            )
        else:
            st.warning("⚠️ No similar historical events found. Prediction confidence may be lower.")

st.divider()
st.markdown("*Generated by EventIQ Autonomous Learning Agent | Last updated: 2026-06-20*")
