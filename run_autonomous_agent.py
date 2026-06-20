#!/usr/bin/env python3
"""
run_autonomous_agent.py — Command-line interface for autonomous learning agent.

Generates comprehensive analysis reports for unplanned traffic events.
"""

import os
import sys
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.autonomous_learning_agent import (
    analyze_unplanned_events,
    generate_weekly_report,
    save_analysis_result,
    predict_priority,
)

def main():
    parser = argparse.ArgumentParser(
        description="EventIQ Autonomous Learning Agent for Unplanned Events"
    )
    parser.add_argument(
        "--train-csv",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "train.csv"),
        help="Path to train.csv"
    )
    parser.add_argument(
        "--report-type",
        choices=["full", "summary", "json"],
        default="full",
        help="Report format"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (optional)"
    )
    parser.add_argument(
        "--predict",
        type=str,
        help='Predict priority for event (JSON string, e.g., \'{"corridor":"Mysore Road", "event_cause":"accident", "veh_type":"car"}\')'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("EventIQ Autonomous Learning Agent")
    print("AI-powered Analysis Engine for Unplanned Traffic Events")
    print("=" * 80)
    print()
    
    # Predict mode
    if args.predict:
        print("🔮 Predicting Priority for Event...")
        try:
            event = json.loads(args.predict)
            priority, confidence, reasoning = predict_priority(event, args.train_csv)
            print(f"\n✓ Prediction Result:")
            print(f"  • Priority: {priority}")
            print(f"  • Confidence: {confidence*100:.0f}%")
            print(f"  • Reasoning: {reasoning}")
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON: {e}")
            sys.exit(1)
        return
    
    # Analysis mode
    print(f"📊 Analyzing {os.path.basename(args.train_csv)}...")
    
    try:
        result = analyze_unplanned_events(args.train_csv)
        print(f"✓ Analysis complete!")
        print(f"  • Events analyzed: {result.total_unplanned_events:,}")
        print(f"  • Rules discovered: {len(result.top_rules)}")
        print(f"  • Blind spots identified: {len(result.blind_spots)}")
        print(f"  • Insights generated: {len(result.insights)}")
        print()
        
        # Generate report
        if args.report_type == "json":
            print("💾 Generating JSON report...")
            output_path = args.output or os.path.join(
                os.path.dirname(__file__),
                f"analysis_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            save_analysis_result(result, output_path)
            print(f"✓ Saved to: {output_path}")
            
        else:  # full or summary
            report = generate_weekly_report(args.train_csv)
            
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(report)
                print(f"📄 Report saved to: {args.output}")
            else:
                print(report)
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
