import os
import uuid
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

st.set_page_config(page_title="Specification Lifecycle & SLA Analytics", page_icon="📋", layout="wide")
STAGES = ["Assigned", "Ballot", "GSA Approval", "FAA Approval", "DCMA Approval", "Hold", "Published"]
TODAY = pd.Timestamp.now().normalize()


@st.cache_resource
def get_engine(db_name):
    url = URL.create(
        "postgresql+psycopg", username="postgres",
        password=os.environ["SPEC_DB_PASSWORD"],
        host="localhost", port=5432, database=db_name
    )
    return create_engine(url, pool_pre_ping=True)


def load_data(engine):
    with engine.connect() as conn:
        actual_db = conn.execute(text("SELECT current_database()")).scalar_one()
        specs = pd.read_sql(text("SELECT * FROM specification_tracker ORDER BY specification_id"), conn)
        history = pd.read_sql(text("""
            SELECT history_id, specification_id, previous_stage, new_stage,
                   updated_date, updated_by, comment FROM stage_history
            ORDER BY updated_date DESC, history_id DESC
        """), conn)
        alerts = pd.read_sql(text("""
            SELECT notification_id, specification_id, notification_type,
                   notification_date, message, is_read, created_at
            FROM sla_notifications ORDER BY notification_id DESC
        """), conn)
    return actual_db, specs, history, alerts


def calculate_metrics(specs, history, warning_days):
    specs = specs.copy()
    history = history.copy()
    for col in ["due_date", "completion_date"]:
        specs[col] = pd.to_datetime(specs[col], errors="coerce")
    history["updated_date"] = pd.to_datetime(history["updated_date"], errors="coerce")
    completed = specs["completion_date"].notna()
    remaining = (specs["due_date"] - TODAY).dt.days
    specs["days_remaining"] = remaining
    specs["days_overdue"] = (TODAY - specs["due_date"]).dt.days.clip(lower=0).fillna(0).astype(int)
    specs["sla_status"] = "On Track"
    specs.loc[~completed & specs["due_date"].isna(), "sla_status"] = "Missing Due Date"
    specs.loc[~completed & (remaining < 0), "sla_status"] = "Overdue"
    specs.loc[~completed & remaining.between(0, warning_days), "sla_status"] = "Due Soon"
    specs.loc[completed, "sla_status"] = "Completed"

    # DATE-only history cannot order multiple updates occurring on the same day.
    latest = {}
    for sid, group in history.dropna(subset=["updated_date"]).groupby("specification_id"):
        day = group["updated_date"].max()
        rows = group[group["updated_date"] == day]
        if len(rows) == 1:
            latest[str(sid)] = (str(rows.iloc[0]["new_stage"]), day)

    def age(row):
        record = latest.get(str(row["specification_id"]))
        if not record or record[0] != str(row["current_stage"]):
            return pd.NA
        value = (TODAY - record[1]).days
        return value if value >= 0 else pd.NA

    specs["stage_age_days"] = specs.apply(age, axis=1).astype("Int64")

    def risk(row):
        if pd.notna(row["completion_date"]) or row["current_stage"] == "Published":
            return pd.Series([0, "Completed", "Already completed"])
        remaining = row["days_remaining"]
        if pd.isna(remaining):
            deadline, reason = 40, "Missing due date"
        elif remaining < 0:
            deadline = min(60, 40 + 5 * abs(int(remaining)))
            reason = f"Overdue {abs(int(remaining))} days"
        elif remaining <= 2:
            deadline, reason = 40, f"Due in {int(remaining)} days"
        elif remaining <= 7:
            deadline, reason = 25, f"Due in {int(remaining)} days"
        elif remaining <= 14:
            deadline, reason = 10, f"Due in {int(remaining)} days"
        else:
            deadline, reason = 0, "Deadline over 14 days away"
        age_days = row["stage_age_days"]
        age_score = 0 if pd.isna(age_days) else min(30, 2 * int(age_days))
        hold = 10 if row["current_stage"] == "Hold" else 0
        score = min(100, deadline + age_score + hold)
        level = "Critical" if score >= 75 else "High" if score >= 50 else "Medium" if score >= 25 else "Low"
        detail = f"{reason}; stage age: {'unknown' if pd.isna(age_days) else str(int(age_days)) + ' days'}"
        if hold:
            detail += "; on Hold"
        return pd.Series([score, level, detail])

    specs[["risk_score", "risk_level", "risk_reason"]] = specs.apply(risk, axis=1)
    specs["risk_score"] = specs["risk_score"].astype(int)
    return specs, history


def action(row):
    if row["current_stage"] == "Hold":
        return "Resolve hold blocker with owner/SME"
    if row["sla_status"] == "Overdue":
        return "Escalate and confirm recovery date"
    if row["sla_status"] == "Due Soon":
        return "Confirm approval before deadline"
    if row["sla_status"] == "Missing Due Date":
        return "Validate due date and ownership"
    if pd.notna(row["stage_age_days"]) and row["stage_age_days"] >= 15:
        return "Review stage delay with approver"
    return "Monitor at next review"


def priority_queue(specs):
    active = specs[(specs["completion_date"].isna()) & (specs["current_stage"] != "Published")].copy()
    active["recommended_action"] = active.apply(action, axis=1)
    return active.sort_values(
        ["risk_score", "days_overdue", "stage_age_days", "specification_id"],
        ascending=[False, False, False, True], na_position="last"
    )


def update_stage(engine, sid, old, new, actor, comment):
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE specification_tracker SET current_stage=:new,
                completion_date=CASE
                    WHEN :publish=1 THEN COALESCE(completion_date, CURRENT_DATE)
                    WHEN :reopen=1 THEN NULL ELSE completion_date END
            WHERE specification_id=:sid AND current_stage=:old
        """), {"sid": sid, "old": old, "new": new,
               "publish": int(new == "Published"),
               "reopen": int(old == "Published" and new != "Published")})
        if result.rowcount != 1:
            raise ValueError("Record changed; refresh and retry.")
        conn.execute(text("""
            INSERT INTO stage_history
            (history_id, specification_id, previous_stage, new_stage, updated_date, updated_by, comment)
            VALUES (:hid, :sid, :old, :new, CURRENT_DATE, :actor, :comment)
        """), {"hid": "H-" + uuid.uuid4().hex[:16], "sid": sid, "old": old,
               "new": new, "actor": actor, "comment": comment})


def generate_notifications(engine, specs):
    count = 0
    with engine.begin() as conn:
        for _, row in specs[specs["sla_status"].isin(["Due Soon", "Overdue"])].iterrows():
            status = row["sla_status"]
            message = (f"{row['specification_id']} overdue by {row['days_overdue']} days"
                       if status == "Overdue" else
                       f"{row['specification_id']} due in {int(row['days_remaining'])} days")
            inserted = conn.execute(text("""
                INSERT INTO sla_notifications
                    (specification_id, notification_type, notification_date, message, is_read)
                VALUES (:sid, :type, CURRENT_DATE, :message, FALSE)
                ON CONFLICT (specification_id, notification_type, notification_date) DO NOTHING
                RETURNING notification_id
            """), {"sid": str(row["specification_id"]), "type": status, "message": message})
            count += int(inserted.scalar_one_or_none() is not None)
    return count


st.title("Specification Lifecycle & SLA Analytics")
st.caption("Synthetic portfolio data | Executive monitoring · Workflow updates · SLA alerts")
db_name = os.environ.get("SPEC_DB_NAME", "specification_lifecycle_db")
warning_days = st.sidebar.slider("Due Soon Window (days)", 1, 30, 7)

try:
    engine = get_engine(db_name)
    connected_db, raw_specs, history, notifications = load_data(engine)
    if raw_specs.empty:
        st.warning("No specifications found.")
        st.stop()
    specs, history = calculate_metrics(raw_specs, history, warning_days)
except Exception as exc:
    st.error(f"Database load failed: {exc}")
    st.stop()

st.sidebar.info(f"Connected Database: {connected_db}")
if connected_db != "specification_lifecycle_test":
    st.sidebar.warning("This is not the test database. Stage updates will modify this database.")

for key in ["update_success", "alert_success"]:
    if key in st.session_state:
        st.success(st.session_state.pop(key))

queue = priority_queue(specs)
active = specs[specs["completion_date"].isna()].copy()
done = specs[specs["completion_date"].notna()].copy()
on_time = int((done["completion_date"] <= done["due_date"]).sum())
on_time_rate = 100 * on_time / len(done) if len(done) else 0
backlog = active.groupby("current_stage", dropna=False).agg(
    Active=("specification_id", "count"),
    Overdue=("sla_status", lambda s: int((s == "Overdue").sum()))
).reset_index().rename(columns={"current_stage": "Stage"})
backlog = backlog.sort_values(["Overdue", "Active"], ascending=False)

tab1, tab2, tab3 = st.tabs(["Executive Overview", "Specification Management", "SLA & Risk Monitoring"])

with tab1:
    st.subheader("Executive Overview")
    cols = st.columns(5)
    for col, label, value in zip(cols,
        ["Total", "Active", "Overdue", "Critical Risk", "Completed On-Time"],
        [len(specs), len(active), int((active["sla_status"] == "Overdue").sum()),
         int((queue["risk_level"] == "Critical").sum()), f"{on_time_rate:.1f}%"]):
        col.metric(label, value)
    left, right = st.columns(2)
    with left:
        if not backlog.empty:
            st.plotly_chart(px.bar(backlog, x="Stage", y=["Active", "Overdue"],
                                   barmode="group", title="Approval Backlog & Overdue"),
                            use_container_width=True)
    with right:
        if not queue.empty:
            counts = queue["risk_level"].value_counts().rename_axis("Risk").reset_index(name="Count")
            st.plotly_chart(px.bar(counts, x="Risk", y="Count", color="Risk",
                                   title="Active Risk Distribution"), use_container_width=True)
    st.subheader("Top 10 Management Priorities")
    st.dataframe(queue[["specification_id", "current_stage", "assigned_to",
                        "days_overdue", "risk_score", "risk_level", "recommended_action"]].head(10),
                 use_container_width=True, hide_index=True)
    if not backlog.empty:
        top = backlog.iloc[0]
        st.info(f"Highest overdue volume: {top['Stage']} ({int(top['Overdue'])} overdue specifications).")
    st.caption("On-time rate = completed on/before due date ÷ all completed with recorded dates. "
               "Risk scoring is rule-based, not predictive.")

with tab2:
    st.subheader("Specification Tracker")
    search = st.text_input("Search specification ID", placeholder="e.g. SPEC-0002")
    stage_filter = st.selectbox("Stage", ["All"] + STAGES)
    view = specs[specs["specification_id"].astype(str).str.contains(search, case=False, regex=False)]
    if stage_filter != "All":
        view = view[view["current_stage"] == stage_filter]
    st.dataframe(view[["specification_id", "current_stage", "assigned_to", "due_date",
                       "completion_date", "sla_status", "risk_level"]],
                 use_container_width=True, hide_index=True)

    st.subheader("Update Stage")
    ids = sorted(specs["specification_id"].astype(str).tolist())
    sid = st.selectbox("Specification ID", ids)
    current = specs.loc[specs["specification_id"].astype(str) == sid].iloc[0]
    old = str(current["current_stage"])
    st.write(f"Current stage: **{old}** · Assigned to: **{current['assigned_to']}**")
    with st.form("stage_update_form"):
        new = st.selectbox("New stage", STAGES, index=STAGES.index(old) if old in STAGES else 0)
        actor = st.text_input("Updated by")
        comment = st.text_area("Reason for change")
        submitted = st.form_submit_button("Save Stage Update")
    if submitted:
        if new == old or not actor.strip() or not comment.strip():
            st.error("Select a different stage and provide your name and a comment.")
        else:
            try:
                update_stage(engine, sid, old, new, actor.strip(), comment.strip())
                st.session_state["update_success"] = f"{sid}: {old} → {new} saved with audit history."
                st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")

    st.subheader("Audit History")
    hist = history[history["specification_id"].astype(str) == sid]
    st.dataframe(hist[["previous_stage", "new_stage", "updated_date", "updated_by", "comment"]],
                 use_container_width=True, hide_index=True)
    with st.expander("All stage history"):
        st.dataframe(history, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("SLA & Risk Monitoring")
    risk_levels = st.multiselect("Risk level", ["Critical", "High", "Medium", "Low"],
                                 default=["Critical", "High"])
    filtered = queue[queue["risk_level"].isin(risk_levels)]
    columns = ["specification_id", "assigned_to", "current_stage", "due_date",
               "days_overdue", "stage_age_days", "risk_score", "risk_level",
               "risk_reason", "recommended_action"]
    st.dataframe(filtered[columns], use_container_width=True, hide_index=True,
                 column_config={
                     "risk_reason": st.column_config.TextColumn("Risk Explanation", width="large"),
                     "recommended_action": st.column_config.TextColumn("Recommended Action", width="large")
                 })
    st.download_button("Download Action Queue (CSV)", filtered[columns].to_csv(index=False),
                       file_name="sla_risk_action_queue.csv", mime="text/csv")
    st.caption("Score: deadline (0–60) + stage age (0–30) + Hold (0–10). "
               "Ties sorted by overdue days then stage age. Unknown stage age earns 0 points.")

    st.subheader("SLA Notifications")
    if st.button("Generate Due Soon / Overdue Alerts"):
        try:
            count = generate_notifications(engine, specs)
            st.session_state["alert_success"] = f"{count} new notifications generated."
            st.rerun()
        except Exception as exc:
            st.error(f"Notification generation failed: {exc}")
    unread = notifications[~notifications["is_read"].fillna(False).astype(bool)]
    st.write(f"**Total alerts:** {len(notifications)} · **Unread:** {len(unread)}")
    unread_only = st.checkbox("Unread only", value=True)
    st.dataframe(unread if unread_only else notifications, use_container_width=True, hide_index=True)
    if not unread.empty:
        nid = st.selectbox("Notification to mark read", unread["notification_id"].astype(int).tolist())
        if st.button("Mark as Read"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE sla_notifications SET is_read=TRUE WHERE notification_id=:nid"),
                                 {"nid": int(nid)})
                st.rerun()
            except Exception as exc:
                st.error(f"Unable to update notification: {exc}")

    with st.expander("Data Quality Checks"):
        st.write("Missing due dates:", int(specs["due_date"].isna().sum()))
        st.write("Published without completion date:",
                 int(((specs["current_stage"] == "Published") & specs["completion_date"].isna()).sum()))
        st.write("Non-published with completion date:",
                 int(((specs["current_stage"] != "Published") & specs["completion_date"].notna()).sum()))
        st.write("Orphan history rows:",
                 int((~history["specification_id"].isin(specs["specification_id"])).sum()))
        duplicates = notifications.duplicated(["specification_id", "notification_type", "notification_date"]).sum()
        st.write("Duplicate notification rows:", int(duplicates))

st.caption("Portfolio demonstration only. Synthetic data; DATE-level history limits exact stage-duration analysis.")
