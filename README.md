# EventIQ: AI-Powered Traffic Command System

EventIQ is an AI-powered traffic management system designed to assist traffic police and city command centers in handling planned and unplanned traffic events.  
It predicts congestion, assigns incident priority, recommends resources, and supports better real-time decision-making.

## Key Features

- Real-time traffic event monitoring
- Congestion score prediction
- Incident priority classification
- Resource allocation support
- Diversion route recommendation
- Event hotspot visualization
- Feedback-based continuous learning
- Interactive Streamlit dashboard

## Tech Stack

- Python
- Streamlit
- Pandas, NumPy
- Scikit-learn
- XGBoost
- SQLite
- Plotly / Maps
- Machine Learning Models

## Project Structure

```bash
EventIQ/
├── app.py
├── run_autonomous_agent.py
├── train_post_event_learning.py
├── train.csv
├── test.csv
├── modules/
│   ├── supervisory_agent.py
│   ├── congestion_predictor.py
│   ├── priority_predictor.py
│   ├── resource_planner.py
│   ├── diversion_planner.py
│   └── storage.py
├── pages/
├── assets/
├── models/
└── requirements.txt
