import os
import uuid
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

st.set_page_config(page_title="Specification Lifecycle Tracker", page_icon="📋", layout="wide")
st.title("Specification Lifecycle Management")
st.caption("SLA Monitoring | Approval Workflow | Notifications | Bottleneck Analytics | Risk Scoring")

@st.cache_resource
def get_engine():
    db_url = URL.create(
        drivername="postgresql+psycopg", username="postgres",
        password=os.environ["SPEC_DB_PASSWORD"], host="localhost", port=5432,
        database="specification_lifecycle_db"
    )
    return create_engine(db_url, pool_pre_ping=True)

try:
    engine = get_engine()
    with engine.connect() as conn:
        spec_df = pd.read_sql(text("SELECT * FROM specification_tracker ORDER BY specification_id"), conn)
        history_df = pd.read_sql(text("""
            SELECT history_id, specification_id, previous_stage, new_stage,
                   updated_date, updated_by, comment
            FROM stage_history
            ORDER BY updated_date DESC, history_id DESC
        """), conn)
        notifications_df = pd.read_sql(text("""
            SELECT notification_id, specification_id, notification_type,
                   notification_date, message, is_read, created_at
            FROM sla_notifications ORDER BY notification_id DESC
        """), conn)
except Exception as exc:
    st.error(f"Database connection or query failed: {exc}")
    st.stop()

if spec_df.empty:
    st.warning("No specifications found in the database.")
    st.stop()

TODAY = pd.Timestamp.now().normalize()
spec_df["due_date"] = pd.to_datetime(spec_df["due_date"], errors="coerce")
spec_df["completion_date"] = pd.to_datetime(spec_df["completion_date"], errors="coerce")
history_df["updated_date"] = pd.to_datetime(history_df["updated_date"], errors="coerce")
notifications_df["notification_date"] = pd.to_datetime(notifications_df["notification_date"], errors="coerce")

st.sidebar.header("SLA Settings")
warning_days = st.sidebar.slider("Due Soon Warning Window (Days)", 1, 30, 7)
st.sidebar.caption("Risk scoring thresholds are illustrative and configurable in the Python code.")

# SLA status is based on the completion date and due date.
completed = spec_df["completion_date"].notna()
missing_due = spec_df["due_date"].isna()
days_remaining = (spec_df["due_date"] - TODAY).dt.days
spec_df["days_remaining"] = days_remaining
spec_df["days_overdue"] = (TODAY - spec_df["due_date"]).dt.days.clip(lower=0).fillna(0).astype(int)
spec_df["sla_status"] = "On Track"
spec_df.loc[~completed & missing_due, "sla_status"] = "Missing Due Date"
spec_df.loc[~completed & ~missing_due & (days_remaining < 0), "sla_status"] = "Overdue"
spec_df.loc[~completed & ~missing_due & days_remaining.between(0, warning_days), "sla_status"] = "Due Soon"
spec_df.loc[completed, "sla_status"] = "Completed"

# Stage age is inferred only when the latest known transition matches the current stage.
# Dates alone cannot distinguish the order of multiple same-day transitions reliably.
def stage_age_map(hist):
    result = {}
    if hist.empty:
        return result
    valid = hist.dropna(subset=["updated_date"]).copy()
    for spec_id, group in valid.groupby("specification_id"):
        group = group.sort_values(["updated_date", "history_id"])
        last = group.iloc[-1]
        result[str(spec_id)] = (str(last["new_stage"]), last["updated_date"].normalize())
    return result

last_transition = stage_age_map(history_df)

def get_stage_age(row):
    record = last_transition.get(str(row["specification_id"]))
    if record is None or record[0] != str(row["current_stage"]):
        return pd.NA
    age = (TODAY - record[1]).days
    return age if age >= 0 else pd.NA

spec_df["stage_age_days"] = spec_df.apply(get_stage_age, axis=1).astype("Int64")

# Transparent, rule-based prioritization; not a predictive ML model.
def score_risk(row):
    if row["current_stage"] == "Published" or pd.notna(row["completion_date"]):
        return pd.Series([0, "Completed", "Already published/completed"])

    remaining = row["days_remaining"]
    if pd.isna(remaining):
        deadline_points = 40
        deadline_reason = "Due date missing"
    elif remaining < 0:
        overdue_days = abs(int(remaining))
        deadline_points = min(60, 40 + 5 * overdue_days)
        deadline_reason = f"Overdue by {overdue_days} day(s)"
    elif remaining <= 2:
        deadline_points = 40
        deadline_reason = f"Due in {int(remaining)} day(s)"
    elif remaining <= 7:
        deadline_points = 25
        deadline_reason = f"Due in {int(remaining)} day(s)"
    elif remaining <= 14:
        deadline_points = 10
        deadline_reason = f"Due in {int(remaining)} day(s)"
    else:
        deadline_points = 0
        deadline_reason = "Deadline more than 14 days away"

    age = row["stage_age_days"]
    if pd.isna(age):
        age_points = 0
        age_reason = "Stage age unknown"
    else:
        age_points = min(30, int(age) * 2)
        age_reason = f"In current stage for {int(age)} day(s)"

    hold_points = 10 if row["current_stage"] == "Hold" else 0
    score = min(100, deadline_points + age_points + hold_points)
    if score >= 75:
        level = "Critical"
    elif score >= 50:
        level = "High"
    elif score >= 25:
        level = "Medium"
    else:
        level = "Low"
    reason = f"{deadline_reason}; {age_reason}"
    if hold_points:
        reason += "; currently on Hold"
    return pd.Series([score, level, reason])

spec_df[["risk_score", "risk_level", "risk_reason"]] = spec_df.apply(score_risk, axis=1)
spec_df["risk_score"] = spec_df["risk_score"].astype(int)

if "update_success" in st.session_state:
    st.success(st.session_state.pop("update_success"))
if "notification_success" in st.session_state:
    st.success(st.session_state.pop("notification_success"))

st.header("Management Overview")
metrics = st.columns(5)
metrics[0].metric("Total Specifications", len(spec_df))
metrics[1].metric("Active", int((~completed).sum()))
metrics[2].metric("Overdue", int((spec_df["sla_status"] == "Overdue").sum()))
metrics[3].metric("Due Soon", int((spec_df["sla_status"] == "Due Soon").sum()))
metrics[4].metric("Completed", int(completed.sum()))

left, right = st.columns(2)
with left:
    stage_counts = spec_df["current_stage"].value_counts().rename_axis("Stage").reset_index(name="Count")
    fig = px.bar(stage_counts, x="Stage", y="Count", color="Stage", title="Specifications by Current Stage")
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
with right:
    sla_counts = spec_df["sla_status"].value_counts().rename_axis("Status").reset_index(name="Count")
    st.plotly_chart(px.pie(sla_counts, names="Status", values="Count", hole=0.4,
                           title="SLA Status Distribution"), use_container_width=True)

st.divider()
st.header("Specification Tracker")
selected_stage_filter = st.selectbox(
    "Filter by Stage", ["All"] + sorted(spec_df["current_stage"].dropna().unique().tolist()),
    key="tracker_stage_filter"
)
filtered_df = spec_df if selected_stage_filter == "All" else spec_df[spec_df["current_stage"] == selected_stage_filter]
st.dataframe(filtered_df, use_container_width=True, hide_index=True)

st.divider()
st.header("Update Specification Stage")
stage_options = ["Assigned", "Ballot", "GSA Approval", "FAA Approval", "DCMA Approval", "Hold", "Published"]
spec_ids = sorted(spec_df["specification_id"].astype(str).tolist())
if st.session_state.get("selected_spec") not in spec_ids:
    st.session_state["selected_spec"] = spec_ids[0]
selected_spec = st.selectbox("Select Specification", spec_ids, key="selected_spec")
selected_row = spec_df.loc[spec_df["specification_id"].astype(str) == selected_spec].iloc[0]
old_stage = selected_row["current_stage"]
st.info(f"Current Stage: {old_stage}")
st.write(f"Assigned To: {selected_row['assigned_to']}")
st.write("Completion Date:", selected_row["completion_date"].strftime("%Y-%m-%d")
         if pd.notna(selected_row["completion_date"]) else "Not completed")
if st.session_state.get("stage_spec_context") != selected_spec:
    st.session_state["stage_spec_context"] = selected_spec
    st.session_state["new_stage_selection"] = old_stage if old_stage in stage_options else stage_options[0]
new_stage = st.selectbox("Select New Stage", stage_options, key="new_stage_selection")
comment = st.text_area("Update Comment", placeholder="Enter reason for stage change", key="stage_comment")
updated_by = st.text_input("Updated By", placeholder="Enter your name", key="stage_updated_by")
if new_stage == old_stage:
    st.warning("Please select a different stage.")
if st.button("Update Stage", type="primary"):
    if new_stage == old_stage:
        st.error("Please select a different stage.")
    elif not updated_by.strip():
        st.error("Please enter your name.")
    elif not comment.strip():
        st.error("Please enter an update comment.")
    else:
        try:
            history_id = "H-" + uuid.uuid4().hex[:16]  # 18 characters; VARCHAR(20)
            with engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE specification_tracker
                    SET current_stage = :new_stage,
                        completion_date = CASE
                            WHEN :publish_flag = 1 THEN COALESCE(completion_date, CURRENT_DATE)
                            WHEN :reopen_flag = 1 THEN NULL
                            ELSE completion_date END
                    WHERE specification_id = :spec_id AND current_stage = :old_stage
                """), {
                    "new_stage": new_stage,
                    "publish_flag": int(new_stage == "Published"),
                    "reopen_flag": int(old_stage == "Published" and new_stage != "Published"),
                    "spec_id": selected_spec, "old_stage": old_stage
                })
                if result.rowcount != 1:
                    raise ValueError("Stage update failed or record changed; refresh and retry.")
                conn.execute(text("""
                    INSERT INTO stage_history (
                        history_id, specification_id, previous_stage, new_stage,
                        updated_date, updated_by, comment
                    ) VALUES (
                        :history_id, :spec_id, :old_stage, :new_stage,
                        CURRENT_DATE, :updated_by, :comment
                    )
                """), {
                    "history_id": history_id, "spec_id": selected_spec,
                    "old_stage": old_stage, "new_stage": new_stage,
                    "updated_by": updated_by.strip(), "comment": comment.strip()
                })
            st.session_state["update_success"] = f"{selected_spec} updated from {old_stage} to {new_stage}."
            st.rerun()
        except Exception as exc:
            st.error(f"Update failed: {exc}")

st.divider()
st.header("Specification Stage History")
st.caption("Audit trail of specification stage transitions")
selected_history = history_df[history_df["specification_id"].astype(str) == selected_spec]
st.metric("Recorded Stage Transitions", len(selected_history))
st.dataframe(selected_history[["previous_stage", "new_stage", "updated_date", "updated_by", "comment"]],
             use_container_width=True, hide_index=True)
with st.expander("View Complete Stage History"):
    st.dataframe(history_df, use_container_width=True, hide_index=True)
with st.expander("Stage History Verification"):
    orphans = history_df[~history_df["specification_id"].isin(spec_df["specification_id"])]
    if orphans.empty:
        st.success("No orphan stage history records found.")
    else:
        st.error("History records reference missing specifications.")
        st.dataframe(orphans)
    st.caption("This verifies references, not whether every historical transition is recorded.")

st.divider()
st.header("SLA Notifications")
st.caption("Generate due-soon and overdue notifications and track read status.")

def generate_notifications():
    created = 0
    with engine.begin() as conn:
        for _, row in spec_df.iterrows():
            status = row["sla_status"]
            if status not in ("Due Soon", "Overdue"):
                continue
            spec_id = str(row["specification_id"])
            if status == "Due Soon":
                message = f"Specification {spec_id} is due in {int(row['days_remaining'])} day(s)."
            else:
                message = f"Specification {spec_id} is overdue by {int(row['days_overdue'])} day(s)."
            inserted = conn.execute(text("""
                INSERT INTO sla_notifications (
                    specification_id, notification_type, notification_date, message, is_read
                ) VALUES (:spec_id, :notification_type, CURRENT_DATE, :message, FALSE)
                ON CONFLICT (specification_id, notification_type, notification_date) DO NOTHING
                RETURNING notification_id
            """), {"spec_id": spec_id, "notification_type": status, "message": message})
            if inserted.scalar_one_or_none() is not None:
                created += 1
    return created

if st.button("Generate SLA Notifications"):
    try:
        count = generate_notifications()
        st.session_state["notification_success"] = f"{count} new SLA notification(s) generated."
        st.rerun()
    except Exception as exc:
        st.error(f"Notification generation failed: {exc}")

with engine.connect() as conn:
    notifications_df = pd.read_sql(text("""
        SELECT notification_id, specification_id, notification_type,
               notification_date, message, is_read, created_at
        FROM sla_notifications ORDER BY notification_id DESC
    """), conn)
notifications_df["notification_date"] = pd.to_datetime(notifications_df["notification_date"], errors="coerce")
unread_mask = ~notifications_df["is_read"].fillna(False).astype(bool)
n1, n2 = st.columns(2)
n1.metric("Total Notifications", len(notifications_df))
n2.metric("Unread Notifications", int(unread_mask.sum()))
if notifications_df.empty:
    st.info("No notifications found. Click Generate SLA Notifications.")
else:
    unread_only = st.checkbox("Show Unread Notifications Only")
    st.dataframe(notifications_df.loc[unread_mask] if unread_only else notifications_df,
                 use_container_width=True, hide_index=True)
    unread_ids = notifications_df.loc[unread_mask, "notification_id"].astype(int).tolist()
    if unread_ids:
        selected_notification = st.selectbox("Select Notification to Mark as Read", unread_ids)
        if st.button("Mark Selected Notification as Read"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE sla_notifications SET is_read = TRUE
                        WHERE notification_id = :notification_id
                    """), {"notification_id": selected_notification})
                st.rerun()
            except Exception as exc:
                st.error(f"Unable to update notification: {exc}")

st.divider()
st.header("Workflow Bottleneck Analytics")
st.caption("Active backlogs, historical stage durations and employee workload")
active_df = spec_df[spec_df["completion_date"].isna()].copy()
st.subheader("Stage-Wise Active Backlog")
stage_backlog = active_df.groupby("current_stage", dropna=False).agg(
    Active_Specifications=("specification_id", "count"),
    Overdue_Specifications=("sla_status", lambda s: (s == "Overdue").sum()),
    Due_Soon_Specifications=("sla_status", lambda s: (s == "Due Soon").sum())
).reset_index().rename(columns={"current_stage": "Stage"})
if not stage_backlog.empty:
    stage_backlog["Overdue_Rate"] = (
        100 * stage_backlog["Overdue_Specifications"] / stage_backlog["Active_Specifications"]
    ).round(1)
    stage_backlog = stage_backlog.sort_values("Active_Specifications", ascending=False)
    st.plotly_chart(px.bar(stage_backlog, x="Stage", y="Active_Specifications",
                           color="Overdue_Specifications", title="Active Backlog by Stage"),
                    use_container_width=True)
    st.dataframe(stage_backlog, use_container_width=True, hide_index=True)
else:
    st.info("No active specifications found.")

st.subheader("Stage Transition Duration")
st.caption("Calendar-day intervals between consistent consecutive history records; same-day intervals count as 0.")
duration_records = []
if not history_df.empty:
    for spec_id, group in history_df.dropna(subset=["updated_date"]).groupby("specification_id"):
        group = group.sort_values(["updated_date", "history_id"]).reset_index(drop=True)
        for i in range(len(group) - 1):
            start, end = group.iloc[i], group.iloc[i + 1]
            if start["new_stage"] != end["previous_stage"]:
                continue
            days = (end["updated_date"] - start["updated_date"]).days
            if days >= 0:
                duration_records.append({"Specification_ID": spec_id, "Stage": start["new_stage"],
                                         "Start_Date": start["updated_date"], "End_Date": end["updated_date"],
                                         "Duration_Days": days})
duration_df = pd.DataFrame(duration_records)
duration_summary = pd.DataFrame()
if not duration_df.empty:
    duration_summary = duration_df.groupby("Stage").agg(
        Average_Days=("Duration_Days", "mean"),
        Median_Days=("Duration_Days", "median"),
        Maximum_Days=("Duration_Days", "max"),
        Observed_Transitions=("Duration_Days", "count")
    ).reset_index().sort_values("Average_Days", ascending=False)
    duration_summary["Average_Days"] = duration_summary["Average_Days"].round(2)
    st.plotly_chart(px.bar(duration_summary, x="Stage", y="Average_Days", color="Stage",
                           title="Average Observed Time Spent in Each Stage"), use_container_width=True)
    st.dataframe(duration_summary, use_container_width=True, hide_index=True)
    with st.expander("View Individual Stage Durations"):
        st.dataframe(duration_df, use_container_width=True, hide_index=True)
else:
    st.info("Insufficient consistent history for transition-duration analysis.")

st.subheader("Employee Workload Analysis")
employee_workload = active_df.groupby("assigned_to", dropna=False).agg(
    Active_Specifications=("specification_id", "count"),
    Overdue_Specifications=("sla_status", lambda s: (s == "Overdue").sum()),
    Due_Soon_Specifications=("sla_status", lambda s: (s == "Due Soon").sum())
).reset_index().rename(columns={"assigned_to": "Employee"})
if not employee_workload.empty:
    employee_workload["Overdue_Rate"] = (
        100 * employee_workload["Overdue_Specifications"] / employee_workload["Active_Specifications"]
    ).round(1)
    employee_workload = employee_workload.sort_values("Active_Specifications", ascending=False)
    st.plotly_chart(px.bar(employee_workload, x="Employee",
                           y=["Active_Specifications", "Overdue_Specifications"],
                           barmode="group", title="Employee Workload and Overdue Specifications"),
                    use_container_width=True)
    st.dataframe(employee_workload, use_container_width=True, hide_index=True)
else:
    st.info("No active employee assignments found.")

st.subheader("Automated Management Insights")
if not stage_backlog.empty:
    largest = stage_backlog.iloc[0]
    st.info(f"Largest active backlog: {largest['Stage']} ({int(largest['Active_Specifications'])} specifications).")
    most_overdue = stage_backlog.sort_values("Overdue_Specifications", ascending=False).iloc[0]
    if most_overdue["Overdue_Specifications"] > 0:
        st.warning(f"Highest overdue volume: {most_overdue['Stage']} ({int(most_overdue['Overdue_Specifications'])} overdue).")
if not duration_summary.empty:
    slowest = duration_summary.iloc[0]
    st.info(f"Longest observed average stage duration: {slowest['Stage']} "
            f"({slowest['Average_Days']} days across {int(slowest['Observed_Transitions'])} intervals).")
if not employee_workload.empty:
    busiest = employee_workload.iloc[0]
    st.info(f"Highest active workload: {busiest['Employee']} "
            f"({int(busiest['Active_Specifications'])} specifications).")
st.caption("Backlog and duration are descriptive; they do not prove the cause of delays.")

# ============================================================
# STEP 6 — STAGE AGING AND SLA RISK SCORING
# ============================================================
st.divider()
st.header("Stage Aging & SLA Risk Scoring")
st.caption("Transparent, rule-based priority scoring for active specifications; not a predictive ML model.")
risk_active = spec_df[(spec_df["current_stage"] != "Published") & spec_df["completion_date"].isna()].copy()

if risk_active.empty:
    st.success("No active specifications require risk scoring.")
else:
    critical = int((risk_active["risk_level"] == "Critical").sum())
    high = int((risk_active["risk_level"] == "High").sum())
    unknown_age = int(risk_active["stage_age_days"].isna().sum())
    risk_cols = st.columns(4)
    risk_cols[0].metric("Critical Risk", critical)
    risk_cols[1].metric("High Risk", high)
    risk_cols[2].metric("Average Risk Score", round(float(risk_active["risk_score"].mean()), 1))
    risk_cols[3].metric("Unknown Stage Age", unknown_age)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        risk_counts = risk_active["risk_level"].value_counts().rename_axis("Risk Level").reset_index(name="Count")
        st.plotly_chart(px.bar(risk_counts, x="Risk Level", y="Count", color="Risk Level",
                               category_orders={"Risk Level": ["Low", "Medium", "High", "Critical"]},
                               title="Active Specifications by Risk Level"), use_container_width=True)
    with chart_right:
        age_known = risk_active.dropna(subset=["stage_age_days"]).copy()
        if age_known.empty:
            st.info("No verified current-stage ages available for the aging chart.")
        else:
            age_known["stage_age_days"] = age_known["stage_age_days"].astype(int)
            st.plotly_chart(px.box(age_known, x="current_stage", y="stage_age_days", color="current_stage",
                                   title="Current Stage Age Distribution", points="all"),
                            use_container_width=True)

    st.subheader("Stage Aging Heatmap")
    st.caption("Counts of active specifications with verified stage ages. Unknown ages are shown separately.")
    age_buckets = [-1, 3, 7, 14, 30, float("inf")]
    age_labels = ["0–3 days", "4–7 days", "8–14 days", "15–30 days", "31+ days"]
    heat_df = risk_active.copy()
    heat_df["Age Bucket"] = pd.cut(heat_df["stage_age_days"].astype(float),
                                    bins=age_buckets, labels=age_labels)
    heat_df["Age Bucket"] = heat_df["Age Bucket"].astype(object).fillna("Unknown")
    heat_df["Stage"] = heat_df["current_stage"].fillna("Unknown Stage")
    matrix = pd.crosstab(heat_df["Stage"], heat_df["Age Bucket"])
    matrix = matrix.reindex(columns=age_labels + ["Unknown"], fill_value=0)
    fig_heat = px.imshow(matrix, text_auto=True, aspect="auto",
                         labels={"x": "Stage Age", "y": "Current Stage", "color": "Specifications"},
                         title="Stage Aging Heatmap")
    st.plotly_chart(fig_heat, use_container_width=True)

    st.subheader("Prioritized Management Action Queue")
    risk_filter = st.multiselect("Risk Levels", ["Critical", "High", "Medium", "Low"],
                                 default=["Critical", "High", "Medium", "Low"])
    action_df = risk_active[risk_active["risk_level"].isin(risk_filter)].copy()
    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    action_df["priority_sort"] = action_df["risk_level"].map(priority_order)
    action_df = action_df.sort_values(["priority_sort", "risk_score", "days_overdue"],
                                      ascending=[True, False, False])
    action_df["Recommended Action"] = action_df.apply(
        lambda r: (
            "Resolve hold blocker and contact owner/SME" if r["current_stage"] == "Hold"
            else "Escalate overdue item and confirm recovery date" if r["sla_status"] == "Overdue"
            else "Confirm approval owner and deadline" if r["sla_status"] == "Due Soon"
            else "Validate due date and owner" if r["sla_status"] == "Missing Due Date"
            else "Review prolonged stage and next approval" if pd.notna(r["stage_age_days"]) and r["stage_age_days"] >= 15
            else "Monitor progress at next review"
        ), axis=1
    )
    queue_columns = ["specification_id", "assigned_to", "current_stage", "due_date", "sla_status",
                     "stage_age_days", "risk_score", "risk_level", "risk_reason", "Recommended Action"]
    st.dataframe(action_df[queue_columns], use_container_width=True, hide_index=True)
    st.download_button("Download Risk Action Queue (CSV)",
                       action_df[queue_columns].to_csv(index=False).encode("utf-8"),
                       file_name="specification_risk_action_queue.csv", mime="text/csv")
    st.caption("Unknown stage age receives zero age points, so the score may underestimate risk. "
               "The risk queue is a prioritization aid, not an automated decision system.")

st.divider()
st.header("Data Quality Verification")
with st.expander("SLA Data Quality Verification"):
    missing = int(spec_df["due_date"].isna().sum())
    published_missing = int(((spec_df["current_stage"] == "Published") &
                             spec_df["completion_date"].isna()).sum())
    nonpublished_completed = int(((spec_df["current_stage"] != "Published") &
                                  spec_df["completion_date"].notna()).sum())
    st.write("Specifications missing a valid due date:", missing)
    st.write("Published specifications without completion dates:", published_missing)
    st.write("Non-published specifications with completion dates:", nonpublished_completed)
    if missing == published_missing == nonpublished_completed == 0:
        st.success("No SLA data quality issues detected.")
    else:
        st.warning("Some SLA data quality issues require review.")
with st.expander("Notification Duplicate Verification"):
    if notifications_df.empty:
        st.info("No notification records to verify.")
    else:
        duplicate_counts = notifications_df.groupby(
            ["specification_id", "notification_type", "notification_date"], dropna=False
        ).size().reset_index(name="Count")
        duplicates = duplicate_counts[duplicate_counts["Count"] > 1]
        if duplicates.empty:
            st.success("No duplicate SLA notifications found.")
        else:
            st.error("Duplicate SLA notifications detected.")
            st.dataframe(duplicates, use_container_width=True, hide_index=True)

st.divider()
st.caption("Specification Lifecycle Management | PostgreSQL + Streamlit + Plotly | Synthetic portfolio data")
