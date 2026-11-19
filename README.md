# Specification Lifecycle Management & SLA Analytics

An end-to-end workflow analytics application built using **Python, PostgreSQL, Streamlit, SQLAlchemy, Pandas, and Plotly**.

## Project Overview

This project simulates an engineering specification approval process involving multiple stakeholders, approval stages, and SLA deadlines.

The objective is to improve workflow visibility, monitor SLA compliance, identify approval bottlenecks, and prioritize high-risk specifications.

**All project data is synthetic and intended for portfolio demonstration.**

## Business Problems

- Limited visibility into specification approval progress
- Delayed identification of SLA breaches
- Approval-stage bottlenecks
- Uneven employee workloads
- Difficulty tracking workflow changes
- Lack of systematic risk prioritization

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application logic and analytics |
| PostgreSQL | Database management |
| SQLAlchemy | Database connectivity |
| Pandas | Data processing |
| Streamlit | Interactive dashboard |
| Plotly | Data visualization |

## Key Features

### Specification Lifecycle Tracking
Track specifications through Assigned, Ballot, GSA Approval, FAA Approval, DCMA Approval, Hold, and Published stages.

### SLA Monitoring
Monitor active, overdue, due-soon, and completed specifications.

### Workflow Updates and Audit Trail
Update specification stages and maintain historical records of workflow changes.

### SLA Notifications
Generate overdue and due-soon alerts with read/unread tracking and duplicate prevention.

### Workflow Bottleneck Analytics
Analyze stage-level backlogs, approval durations, overdue specifications, and employee workloads.

### Stage Aging and Risk Scoring
Estimate time spent in current stages and prioritize specifications using rule-based SLA risk scores.

### Management Action Queue
Identify specifications requiring immediate operational attention.

## Database Architecture

The application uses three PostgreSQL tables:

- `specification_tracker`
- `stage_history`
- `sla_notifications`

## Local Setup

1. Install dependencies using `pip install -r requirements.txt`.
2. Configure a PostgreSQL database named `specification_lifecycle_db`.
3. Create the required tables and load synthetic data.
4. Set the `SPEC_DB_PASSWORD` environment variable.
5. Launch the application using `streamlit run app.py`.

Database setup scripts will be added separately.

## Limitations

- Stage duration calculations use dates rather than timestamps.
- SLA risk scoring is rule-based, not a machine-learning prediction.
- Notifications require application execution and are not independently scheduled.
- Current database connectivity is configured for local development.

## Future Improvements

- Cloud deployment
- Automated notification scheduling
- Historical SLA trend reporting
- Role-based access control

## Author

GitHub: https://github.com/vumang44-data

**Project Type:** Data Analytics | Workflow Management | SLA Monitoring