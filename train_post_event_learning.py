#!/usr/bin/env python3
"""
Train the post-event learning agent by retraining models with feedback data.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.post_event_learning import (
    retrain_models_from_feedback,
    get_learning_metrics,
    compute_trends,
    get_delta_cards
)

def main():
    """Train post-event learning models."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "logs", "eventiq.db")
    test_csv_path = os.path.join(base_dir, "test.csv")
    
    print("=" * 80)
    print("EventIQ Post-Event Learning Model Training")
    print("=" * 80)
    print()
    
    # Check if required files exist
    if not os.path.exists(test_csv_path):
        print(f"⚠️  test.csv not found at {test_csv_path}")
        print("   Continuing without test data...")
    else:
        print(f"✓ test.csv found: {test_csv_path}")
    
    if not os.path.exists(db_path):
        print(f"⚠️  Database not found at {db_path}")
        print("   No feedback data available for training.")
    else:
        print(f"✓ Database found: {db_path}")
    
    print()
    print("-" * 80)
    print("Starting model retraining...")
    print("-" * 80)
    print()
    
    # Run retraining
    result = retrain_models_from_feedback(
        db_path=db_path,
        test_csv_path=test_csv_path
    )
    
    print(f"Retraining Status: {result.get('status')}")
    
    if result.get('status') == 'success':
        print()
        print("📊 Retraining Results:")
        print("-" * 80)
        print(f"  • Priority Model Accuracy:        {result.get('priority_model_accuracy'):.2f}%")
        print(f"  • Congestion Model Accuracy:      {result.get('congestion_model_accuracy'):.2f}%")
        print(f"  • Feedback Records Used:          {result.get('feedback_records_used')}")
        print(f"  • Test Records:                   {result.get('test_records')}")
        print(f"  • Total Training Records:         {result.get('total_training_records')}")
        print(f"  • Improvement vs Baseline:        {result.get('improvement_pct'):+.1f}%")
        print(f"  • Model Saved At:                 {result.get('model_saved_at')}")
        print()
        
        # Get learning metrics
        print("-" * 80)
        print("📈 Overall Learning Metrics:")
        print("-" * 80)
        
        metrics = get_learning_metrics(db_path)
        print(f"  • Baseline Accuracy:              {metrics.get('baseline_accuracy_pct'):.1f}%")
        print(f"  • Current Accuracy:               {metrics.get('current_accuracy_pct'):.1f}%")
        print(f"  • Total Improvement:              {metrics.get('improvement_pct'):+.1f}%")
        print(f"  • Total Feedback Records:         {metrics.get('total_feedback_records')}")
        print(f"  • Priority Accuracy:              {metrics.get('priority_accuracy'):.1f}%" if metrics.get('priority_accuracy') else "  • Priority Accuracy:              N/A")
        print(f"  • Risk Accuracy:                  {metrics.get('risk_accuracy'):.1f}%" if metrics.get('risk_accuracy') else "  • Risk Accuracy:                  N/A")
        print()
        
        # Get trend analysis
        print("-" * 80)
        print("📉 Trend Analysis:")
        print("-" * 80)
        
        trends = compute_trends(db_path)
        
        if trends.get('weekly_accuracy_trend'):
            print("  Weekly Accuracy Trend:")
            for week_data in trends['weekly_accuracy_trend'][-4:]:  # Show last 4 weeks
                print(f"    {week_data['week']}: {week_data['accuracy_pct']:.1f}% ({week_data['count']} records)")
        
        if trends.get('top_corridors_correct'):
            print()
            print("  ✓ Best Performing Corridors:")
            for corridor in trends['top_corridors_correct']:
                acc = trends['corridor_accuracy'].get(corridor, {}).get('accuracy_pct', 0)
                count = trends['corridor_accuracy'].get(corridor, {}).get('count', 0)
                print(f"    • {corridor}: {acc:.1f}% ({count} records)")
        
        if trends.get('top_corridors_wrong'):
            print()
            print("  ✗ Corridors Needing Improvement:")
            for corridor in trends['top_corridors_wrong']:
                acc = trends['corridor_accuracy'].get(corridor, {}).get('accuracy_pct', 0)
                count = trends['corridor_accuracy'].get(corridor, {}).get('count', 0)
                if acc > 0:  # Only show if there's data
                    print(f"    • {corridor}: {acc:.1f}% ({count} records)")
        
        if trends.get('weather_miss_rate_pct', 0) > 0:
            print()
            print(f"  ⚠️  Weather-related misses:        {trends.get('weather_miss_rate_pct', 0):.1f}%")
        
        # Get delta cards
        print()
        print("-" * 80)
        print("📋 KPI Summary (for Dashboard):")
        print("-" * 80)
        
        delta_cards = get_delta_cards(db_path)
        for card in delta_cards:
            direction_emoji = "📈" if card['delta_direction'] == 'up' else ("📉" if card['delta_direction'] == 'down' else "➡️")
            print(f"  {direction_emoji} {card['label']:.<30} {card['value']}")
        
        print()
        print("=" * 80)
        print("✅ Training completed successfully!")
        print("=" * 80)
        print()
        
        # Provide recommendations based on data availability
        if result.get('feedback_records_used', 0) < 5:
            print("⚠️  Recommendations for improving model accuracy:")
            print()
            print("  To improve model performance, collect more operator feedback:")
            print("  • Encourage operators to submit feedback for each event")
            print("  • Provide actual priority corrections when predictions are wrong")
            print("  • Record actual congestion scores after event resolution")
            print("  • Target: 50+ diverse feedback records across all priority levels")
            print()
            print("  Current data summary:")
            print(f"    - Total events: {result.get('test_records')}")
            print(f"    - Feedback records: {result.get('feedback_records_used')}")
            print(f"    - Data completeness: {(result.get('feedback_records_used') / max(result.get('test_records'), 1) * 100):.1f}%")
            print()
        
    else:
        print()
        print(f"❌ Training failed: {result.get('error')}")
        print()


if __name__ == "__main__":
    main()
