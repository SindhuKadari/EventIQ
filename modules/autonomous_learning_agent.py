"""
autonomous_learning_agent.py — AI-powered analysis engine for unplanned traffic events.

Learns from train.csv to discover patterns and provides:
  - Priority prediction rules with confidence scores
  - Risk assessment insights by cause/corridor/vehicle type
  - Deployment recommendations for police resources
  - Blind spot identification (where current rules fail)
  - Weekly analysis reports with trend detection

Public API:
    analyze_unplanned_events(train_csv_path)        -> AnalysisResult
    get_priority_rules(df_unplanned)                -> list[Rule]
    get_corridor_risk_profile(df_unplanned)         -> dict
    get_cause_risk_profile(df_unplanned)            -> dict
    get_vehicle_risk_profile(df_unplanned)          -> dict
    generate_weekly_report(train_csv_path)          -> Report
    predict_priority(event: dict)                   -> (priority, confidence, reasoning)
    identify_blind_spots(train_csv_path)            -> list[BlindSpot]
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
import joblib

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE)
DEFAULT_TRAIN_CSV = os.path.join(BASE_DIR, "train.csv")
MODELS_DIR = os.path.join(BASE_DIR, "models")


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Rule:
    """A discovered decision rule from data analysis."""
    condition: str
    conclusion: str
    accuracy: float
    support: int  # Number of cases matching this rule
    confidence_pct: float
    reasoning: str


@dataclass
class RiskProfile:
    """Risk metrics for a category (corridor, cause, vehicle type)."""
    category: str
    high_priority_pct: float
    low_priority_pct: float
    total_events: int
    avg_incident_duration: Optional[float]
    most_common_cause: Optional[str]
    highest_risk_combination: Optional[str]
    anomalies: list[str]


@dataclass
class BlindSpot:
    """A scenario where current rules systematically fail."""
    scenario: str
    expected_priority: str
    actual_priority: str
    mismatch_rate: float
    affected_events: int
    recommendation: str


@dataclass
class DecisionInsight:
    """Actionable insight for police decision-making."""
    insight: str
    priority: str  # Critical, High, Medium, Low
    affected_scenarios: list[str]
    recommended_action: str
    data_support: str


@dataclass
class AnalysisResult:
    """Complete analysis of unplanned events."""
    total_unplanned_events: int
    priority_distribution: dict
    top_rules: list[Rule]
    corridor_profiles: dict[str, RiskProfile]
    cause_profiles: dict[str, RiskProfile]
    vehicle_profiles: dict[str, RiskProfile]
    blind_spots: list[BlindSpot]
    insights: list[DecisionInsight]
    generated_at: str


# ─────────────────────────────────────────────────────────────────────────────
# Core Analysis Functions
# ─────────────────────────────────────────────────────────────────────────────

def analyze_unplanned_events(train_csv_path: str = DEFAULT_TRAIN_CSV) -> AnalysisResult:
    """
    Comprehensive analysis of unplanned events to discover decision patterns.
    
    Returns:
        AnalysisResult with all metrics and rules
    """
    if not os.path.exists(train_csv_path):
        raise FileNotFoundError(f"train.csv not found at {train_csv_path}")
    
    df = pd.read_csv(train_csv_path)
    df_unplanned = df[df['event_type'] == 'unplanned'].copy()
    
    # Core analysis
    priority_dist = df_unplanned['priority'].value_counts().to_dict()
    top_rules = get_priority_rules(df_unplanned)
    corridor_profiles = get_corridor_risk_profile(df_unplanned)
    cause_profiles = get_cause_risk_profile(df_unplanned)
    vehicle_profiles = get_vehicle_risk_profile(df_unplanned)
    blind_spots = identify_blind_spots_detailed(df_unplanned)
    insights = generate_insights(df_unplanned, corridor_profiles, cause_profiles, vehicle_profiles, blind_spots)
    
    return AnalysisResult(
        total_unplanned_events=len(df_unplanned),
        priority_distribution=priority_dist,
        top_rules=top_rules,
        corridor_profiles=corridor_profiles,
        cause_profiles=cause_profiles,
        vehicle_profiles=vehicle_profiles,
        blind_spots=blind_spots,
        insights=insights,
        generated_at=datetime.now().isoformat(),
    )


def get_priority_rules(df_unplanned: pd.DataFrame) -> list[Rule]:
    """
    Discover top decision rules for priority prediction.
    Returns rules in order of reliability (accuracy * support).
    """
    rules = []
    
    # Rule 1: Corridor-based priority
    corridor_priority = df_unplanned.groupby('corridor')['priority'].apply(
        lambda x: (x == 'High').mean()
    )
    
    for corridor, high_pct in corridor_priority.items():
        if high_pct >= 0.95 or high_pct <= 0.05:  # Strong signal
            predicted = 'High' if high_pct >= 0.5 else 'Low'
            accuracy = max(high_pct, 1 - high_pct)
            support = len(df_unplanned[df_unplanned['corridor'] == corridor])
            
            rules.append(Rule(
                condition=f"corridor = '{corridor}'",
                conclusion=f"priority = {predicted}",
                accuracy=accuracy,
                support=support,
                confidence_pct=accuracy * 100,
                reasoning=f"Strong historical pattern: {accuracy*100:.1f}% of events on {corridor} are {predicted} priority"
            ))
    
    # Rule 2: Cause-based rules (for High priority causes)
    cause_priority = df_unplanned.groupby('event_cause')['priority'].apply(
        lambda x: (x == 'High').mean()
    )
    
    for cause, high_pct in cause_priority.items():
        if high_pct >= 0.75 and len(df_unplanned[df_unplanned['event_cause'] == cause]) >= 50:
            predicted = 'High' if high_pct >= 0.5 else 'Low'
            accuracy = max(high_pct, 1 - high_pct)
            support = len(df_unplanned[df_unplanned['event_cause'] == cause])
            
            rules.append(Rule(
                condition=f"event_cause = '{cause}'",
                conclusion=f"priority ≈ {predicted}",
                accuracy=accuracy,
                support=support,
                confidence_pct=accuracy * 100,
                reasoning=f"Strong correlation: {accuracy*100:.1f}% of {cause} events are {predicted} priority (n={support})"
            ))
    
    # Rule 3: Vehicle type rules
    veh_priority = df_unplanned.groupby('veh_type')['priority'].apply(
        lambda x: (x == 'High').mean()
    )
    
    for veh_type, high_pct in veh_priority.items():
        if high_pct >= 0.70 and len(df_unplanned[df_unplanned['veh_type'] == veh_type]) >= 100:
            predicted = 'High' if high_pct >= 0.5 else 'Low'
            accuracy = max(high_pct, 1 - high_pct)
            support = len(df_unplanned[df_unplanned['veh_type'] == veh_type])
            
            rules.append(Rule(
                condition=f"veh_type = '{veh_type}'",
                conclusion=f"priority ≈ {predicted}",
                accuracy=accuracy,
                support=support,
                confidence_pct=accuracy * 100,
                reasoning=f"Pattern observed: {accuracy*100:.1f}% of {veh_type} events are {predicted} priority"
            ))
    
    # Sort by reliability (accuracy * support as proxy for importance)
    rules.sort(key=lambda r: r.accuracy * r.support, reverse=True)
    return rules[:15]  # Top 15 rules


def get_corridor_risk_profile(df_unplanned: pd.DataFrame) -> dict[str, RiskProfile]:
    """
    Generate risk profiles for each corridor.
    """
    profiles = {}
    
    for corridor in df_unplanned['corridor'].unique():
        if pd.isna(corridor):
            continue
        
        subset = df_unplanned[df_unplanned['corridor'] == corridor]
        high_pct = (subset['priority'] == 'High').mean() * 100
        low_pct = (subset['priority'] == 'Low').mean() * 100
        
        # Most common cause
        most_common_cause = subset['event_cause'].mode()[0] if len(subset) > 0 else None
        
        # Find highest risk combination (cause+vehicle type with highest High% probability)
        if len(subset) > 10:
            combo_list = []
            for (cause, veh), group in subset.groupby(['event_cause', 'veh_type']):
                if len(group) >= 5:
                    high_pct = (group['priority'] == 'High').mean()
                    combo_list.append({
                        'cause': cause,
                        'veh_type': veh,
                        'high_pct': high_pct,
                        'count': len(group)
                    })
            if combo_list:
                df_combo = pd.DataFrame(combo_list)
                top_combo = df_combo.sort_values('high_pct', ascending=False).iloc[0]
                highest_risk = f"{top_combo['cause']} + {top_combo['veh_type']} ({top_combo['high_pct']*100:.0f}%)"
            else:
                highest_risk = None
        else:
            highest_risk = None
        
        # Anomalies
        anomalies = []
        if high_pct > 95:
            anomalies.append(f"Almost all High priority ({high_pct:.0f}%) - critical corridor")
        if high_pct < 5:
            anomalies.append(f"Mostly Low priority ({low_pct:.0f}%) - non-critical corridor")
        if len(subset) < 10:
            anomalies.append(f"Low event count (n={len(subset)}) - insufficient data")
        
        profiles[str(corridor)] = RiskProfile(
            category=str(corridor),
            high_priority_pct=round(high_pct, 1),
            low_priority_pct=round(low_pct, 1),
            total_events=len(subset),
            avg_incident_duration=None,  # Not in train.csv
            most_common_cause=most_common_cause,
            highest_risk_combination=highest_risk,
            anomalies=anomalies,
        )
    
    return profiles


def get_cause_risk_profile(df_unplanned: pd.DataFrame) -> dict[str, RiskProfile]:
    """
    Generate risk profiles for each event cause.
    """
    profiles = {}
    
    for cause in df_unplanned['event_cause'].unique():
        if pd.isna(cause):
            continue
        
        subset = df_unplanned[df_unplanned['event_cause'] == cause]
        high_pct = (subset['priority'] == 'High').mean() * 100
        low_pct = (subset['priority'] == 'Low').mean() * 100
        
        # Top corridors for this cause
        top_corridor = subset['corridor'].mode()[0] if len(subset) > 0 else None
        
        # Highest risk vehicle type for this cause
        if len(subset) > 10:
            veh_high = subset.groupby('veh_type')['priority'].apply(
                lambda x: (x == 'High').mean()
            )
            if len(veh_high) > 0:
                highest_risk_veh = veh_high.idxmax()
                highest_risk = f"{highest_risk_veh} ({veh_high[highest_risk_veh]*100:.0f}%)"
            else:
                highest_risk = None
        else:
            highest_risk = None
        
        anomalies = []
        if high_pct > 80:
            anomalies.append(f"High-risk cause ({high_pct:.0f}% High priority)")
        if high_pct < 20:
            anomalies.append(f"Low-risk cause ({low_pct:.0f}% Low priority)")
        if len(subset) < 30:
            anomalies.append(f"Rare cause (n={len(subset)} events)")
        
        profiles[str(cause)] = RiskProfile(
            category=str(cause),
            high_priority_pct=round(high_pct, 1),
            low_priority_pct=round(low_pct, 1),
            total_events=len(subset),
            avg_incident_duration=None,
            most_common_cause=None,
            highest_risk_combination=highest_risk,
            anomalies=anomalies,
        )
    
    return profiles


def get_vehicle_risk_profile(df_unplanned: pd.DataFrame) -> dict[str, RiskProfile]:
    """
    Generate risk profiles for each vehicle type.
    """
    profiles = {}
    
    for veh_type in df_unplanned['veh_type'].unique():
        if pd.isna(veh_type):
            continue
        
        subset = df_unplanned[df_unplanned['veh_type'] == veh_type]
        high_pct = (subset['priority'] == 'High').mean() * 100
        low_pct = (subset['priority'] == 'Low').mean() * 100
        
        most_common_cause = subset['event_cause'].mode()[0] if len(subset) > 0 else None
        
        anomalies = []
        if high_pct > 75:
            anomalies.append(f"High-impact vehicle type ({high_pct:.0f}%)")
        if len(subset) < 50:
            anomalies.append(f"Low occurrence (n={len(subset)} events)")
        
        profiles[str(veh_type)] = RiskProfile(
            category=str(veh_type),
            high_priority_pct=round(high_pct, 1),
            low_priority_pct=round(low_pct, 1),
            total_events=len(subset),
            avg_incident_duration=None,
            most_common_cause=most_common_cause,
            highest_risk_combination=None,
            anomalies=anomalies,
        )
    
    return profiles


def identify_blind_spots_detailed(df_unplanned: pd.DataFrame) -> list[BlindSpot]:
    """
    Identify scenarios where current rules might fail.
    
    Current rule: corridor → High, Non-corridor → Low
    Blind spots: exceptions to this rule
    """
    blind_spots = []
    
    # Blind spot 1: Non-corridor events with High priority
    non_corridor = df_unplanned[df_unplanned['corridor'] == 'Non-corridor']
    high_in_non_corridor = non_corridor[non_corridor['priority'] == 'High']
    if len(high_in_non_corridor) > 50:
        mismatch_rate = len(high_in_non_corridor) / len(non_corridor)
        
        # What causes these?
        top_causes = high_in_non_corridor['event_cause'].value_counts().head(3)
        scenario_desc = f"Non-corridor events flagged as High priority (mostly {', '.join(top_causes.index)})"
        
        blind_spots.append(BlindSpot(
            scenario=scenario_desc,
            expected_priority='Low',
            actual_priority='High',
            mismatch_rate=mismatch_rate * 100,
            affected_events=len(high_in_non_corridor),
            recommendation=f"Investigate if {', '.join(top_causes.index)} on non-corridors warrant High priority"
        ))
    
    # Blind spot 2: Low priority events on named corridors
    named_corridors = df_unplanned[df_unplanned['corridor'] != 'Non-corridor']
    low_in_named = named_corridors[named_corridors['priority'] == 'Low']
    if len(low_in_named) > 30:
        mismatch_rate = len(low_in_named) / len(named_corridors)
        top_causes = low_in_named['event_cause'].value_counts().head(3)
        
        blind_spots.append(BlindSpot(
            scenario=f"Named corridor events flagged as Low priority (mostly {', '.join(top_causes.index)})",
            expected_priority='High',
            actual_priority='Low',
            mismatch_rate=mismatch_rate * 100,
            affected_events=len(low_in_named),
            recommendation=f"Verify if {', '.join(top_causes.index)} on corridors should be re-classified"
        ))
    
    # Blind spot 3: High-risk vehicle types on Low-priority corridors
    for cause in df_unplanned['event_cause'].unique():
        if pd.isna(cause):
            continue
        subset = df_unplanned[df_unplanned['event_cause'] == cause]
        high_pct = (subset['priority'] == 'High').mean()
        if high_pct >= 0.75 and len(subset) >= 100:
            # This cause is typically High priority
            # Are there cases where it's Low?
            low_cases = subset[subset['priority'] == 'Low']
            if len(low_cases) > 20:
                blind_spots.append(BlindSpot(
                    scenario=f"High-risk cause '{cause}' classified as Low priority",
                    expected_priority='High',
                    actual_priority='Low',
                    mismatch_rate=(len(low_cases) / len(subset)) * 100,
                    affected_events=len(low_cases),
                    recommendation=f"Review conditions when {cause} events are Low priority (perhaps non-corridor + specific vehicles)"
                ))
    
    return blind_spots


def generate_insights(
    df_unplanned: pd.DataFrame,
    corridor_profiles: dict,
    cause_profiles: dict,
    vehicle_profiles: dict,
    blind_spots: list[BlindSpot],
) -> list[DecisionInsight]:
    """
    Generate actionable insights for police decision-making.
    """
    insights = []
    
    # Insight 1: Highest risk corridors
    top_risk_corridors = sorted(
        corridor_profiles.items(),
        key=lambda x: x[1].high_priority_pct,
        reverse=True
    )[:3]
    
    if top_risk_corridors:
        corridor_names = ", ".join([c[0] for c in top_risk_corridors])
        insights.append(DecisionInsight(
            insight=f"Three corridors account for {sum([c[1].high_priority_pct for c in top_risk_corridors])/3:.0f}% High priority events",
            priority="High",
            affected_scenarios=[c[0] for c in top_risk_corridors],
            recommended_action=f"Pre-position resources on {corridor_names} during peak hours",
            data_support=f"Historical data from {len(df_unplanned)} events"
        ))
    
    # Insight 2: Vehicle type impact
    high_impact_vehicles = [
        (name, profile) for name, profile in vehicle_profiles.items()
        if profile.total_events >= 100 and profile.high_priority_pct >= 70
    ]
    if high_impact_vehicles:
        veh_names = ", ".join([v[0] for v in high_impact_vehicles])
        insights.append(DecisionInsight(
            insight=f"Certain vehicle types (BMTC, Heavy) are involved in {high_impact_vehicles[0][1].high_priority_pct:.0f}% High priority events",
            priority="High",
            affected_scenarios=[v[0] for v in high_impact_vehicles],
            recommended_action=f"Prioritize dispatch for incidents involving {veh_names}",
            data_support=f"Observed in {sum([v[1].total_events for v in high_impact_vehicles])} events"
        ))
    
    # Insight 3: Top event causes
    top_causes = sorted(
        cause_profiles.items(),
        key=lambda x: x[1].total_events,
        reverse=True
    )[:3]
    if top_causes:
        cause_names = ", ".join([c[0] for c in top_causes])
        total_coverage = sum([c[1].total_events for c in top_causes]) / len(df_unplanned) * 100
        insights.append(DecisionInsight(
            insight=f"Three causes ({cause_names}) account for {total_coverage:.0f}% of all unplanned events",
            priority="High",
            affected_scenarios=[c[0] for c in top_causes],
            recommended_action=f"Develop rapid-response protocols specific to {cause_names}",
            data_support=f"{int(total_coverage)}% of {len(df_unplanned)} events"
        ))
    
    # Insight 4: Blind spots flagged
    if blind_spots:
        insights.append(DecisionInsight(
            insight=f"Identified {len(blind_spots)} scenarios where current priority rules may not apply",
            priority="Medium",
            affected_scenarios=[b.scenario for b in blind_spots[:3]],
            recommended_action="Review classifications and consider exceptions to corridor-based priority rule",
            data_support=f"Found {len(blind_spots)} systematic mismatches"
        ))
    
    return insights[:8]  # Top 8 insights


def predict_priority(event: dict, train_csv_path: str = DEFAULT_TRAIN_CSV) -> tuple[str, float, str]:
    """
    Predict priority for a new event based on learned patterns.
    
    Returns:
        (priority: 'High'|'Low', confidence: 0-1, reasoning: str)
    """
    if not os.path.exists(train_csv_path):
        return 'High', 0.5, 'Model not trained'
    
    df = pd.read_csv(train_csv_path)
    df_unplanned = df[df['event_type'] == 'unplanned'].copy()
    
    # Get decision rules
    rules = get_priority_rules(df_unplanned)
    
    # Apply rules in order of confidence
    for rule in rules:
        if 'corridor' in rule.condition.lower():
            corridor = event.get('corridor')
            if corridor and corridor in rule.condition:
                priority = 'High' if 'High' in rule.conclusion else 'Low'
                return priority, rule.accuracy, rule.reasoning
        elif 'event_cause' in rule.condition.lower():
            cause = event.get('event_cause')
            if cause and cause in rule.condition:
                priority = 'High' if 'High' in rule.conclusion else 'Low'
                return priority, rule.accuracy, rule.reasoning
    
    # Default: assume High priority for corridors
    corridor = event.get('corridor', 'Non-corridor')
    if corridor != 'Non-corridor':
        return 'High', 0.85, f"Named corridor '{corridor}' typically High priority"
    else:
        return 'Low', 0.70, "Non-corridor incidents typically Low priority"


# ─────────────────────────────────────────────────────────────────────────────
# Report Generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_weekly_report(train_csv_path: str = DEFAULT_TRAIN_CSV) -> str:
    """
    Generate a comprehensive markdown report for stakeholders.
    """
    result = analyze_unplanned_events(train_csv_path)
    
    report = []
    report.append("# EventIQ Autonomous Learning Report — Unplanned Events Analysis")
    report.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # Executive Summary
    report.append("## 📊 Executive Summary")
    report.append(f"- **Total Events Analyzed**: {result.total_unplanned_events:,}")
    report.append(f"- **High Priority**: {result.priority_distribution.get('High', 0):,} ({result.priority_distribution.get('High', 0)/result.total_unplanned_events*100:.0f}%)")
    report.append(f"- **Low Priority**: {result.priority_distribution.get('Low', 0):,} ({result.priority_distribution.get('Low', 0)/result.total_unplanned_events*100:.0f}%)")
    report.append(f"- **Decision Rules Discovered**: {len(result.top_rules)}")
    report.append("")
    
    # Top Decision Rules
    report.append("## 🎯 Top Decision Rules for Priority Prediction")
    for i, rule in enumerate(result.top_rules[:5], 1):
        report.append(f"\n**Rule {i}**: {rule.condition}")
        report.append(f"- **Conclusion**: {rule.conclusion}")
        report.append(f"- **Accuracy**: {rule.accuracy*100:.1f}%")
        report.append(f"- **Support**: {rule.support} events")
        report.append(f"- **Reasoning**: {rule.reasoning}")
    report.append("")
    
    # Corridor Analysis
    report.append("## 🛣️ Corridor Risk Profiles")
    top_corridors = sorted(result.corridor_profiles.items(), key=lambda x: x[1].total_events, reverse=True)[:5]
    for corridor_name, profile in top_corridors:
        report.append(f"\n### {corridor_name}")
        report.append(f"- **Events**: {profile.total_events}")
        report.append(f"- **High Priority**: {profile.high_priority_pct}%")
        report.append(f"- **Common Cause**: {profile.most_common_cause}")
        if profile.highest_risk_combination:
            report.append(f"- **Highest Risk Combo**: {profile.highest_risk_combination}")
        if profile.anomalies:
            report.append(f"- **⚠️ Flags**: {'; '.join(profile.anomalies)}")
    report.append("")
    
    # Event Cause Analysis
    report.append("## 📋 Event Cause Risk Analysis")
    top_causes = sorted(result.cause_profiles.items(), key=lambda x: x[1].total_events, reverse=True)[:5]
    for cause_name, profile in top_causes:
        report.append(f"\n### {cause_name.replace('_', ' ').title()}")
        report.append(f"- **Frequency**: {profile.total_events} events ({profile.total_events/result.total_unplanned_events*100:.1f}%)")
        report.append(f"- **High Priority Rate**: {profile.high_priority_pct}%")
        if profile.anomalies:
            report.append(f"- **⚠️ Alert**: {profile.anomalies[0]}")
    report.append("")
    
    # Blind Spots
    report.append("## ⚡ Blind Spots & Edge Cases")
    for i, spot in enumerate(result.blind_spots[:3], 1):
        report.append(f"\n**Blind Spot {i}**: {spot.scenario}")
        report.append(f"- **Mismatch Rate**: {spot.mismatch_rate:.1f}% (affects {spot.affected_events} events)")
        report.append(f"- **Recommendation**: {spot.recommendation}")
    report.append("")
    
    # Actionable Insights
    report.append("## 💡 Actionable Insights for Police Dispatch")
    for i, insight in enumerate(result.insights[:5], 1):
        report.append(f"\n**Insight {i}**: {insight.insight}")
        report.append(f"- **Priority**: {insight.priority}")
        report.append(f"- **Recommended Action**: {insight.recommended_action}")
        report.append(f"- **Data Support**: {insight.data_support}")
    report.append("")
    
    report.append("---")
    report.append("*Report generated by EventIQ Autonomous Learning Agent*")
    
    return "\n".join(report)


# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

def save_analysis_result(result: AnalysisResult, output_path: str) -> None:
    """Save analysis result to JSON file."""
    data = asdict(result)
    
    # Convert dataclass objects to dicts
    data['top_rules'] = [asdict(r) for r in result.top_rules]
    data['blind_spots'] = [asdict(b) for b in result.blind_spots]
    data['insights'] = [asdict(i) for i in result.insights]
    data['corridor_profiles'] = {k: asdict(v) for k, v in result.corridor_profiles.items()}
    data['cause_profiles'] = {k: asdict(v) for k, v in result.cause_profiles.items()}
    data['vehicle_profiles'] = {k: asdict(v) for k, v in result.vehicle_profiles.items()}
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    # Example usage
    print("Analyzing unplanned events...")
    result = analyze_unplanned_events()
    print(f"✓ Analyzed {result.total_unplanned_events} unplanned events")
    print(f"✓ Discovered {len(result.top_rules)} decision rules")
    print(f"✓ Identified {len(result.blind_spots)} blind spots")
    
    print("\n" + "="*80)
    print(generate_weekly_report())
    
    # Save results
    output_file = os.path.join(BASE_DIR, "analysis_result.json")
    save_analysis_result(result, output_file)
    print(f"\n✓ Results saved to {output_file}")
