"""Deterministic synthetic-only records for an EMPTY project database.

Requires SPEC_DB_NAME and SPEC_DB_PASSWORD environment variables.
Refuses to run if any target table already contains data.
"""
import os
import random
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

STAGES = ["Ballot", "GSA Approval", "FAA Approval", "DCMA Approval", "Hold", "Published"]

def main():
    database = os.environ.get("SPEC_DB_NAME")
    password = os.environ.get("SPEC_DB_PASSWORD")
    if not database or not password:
        raise SystemExit("Set SPEC_DB_NAME and SPEC_DB_PASSWORD first.")
    if database in {"specification_lifecycle_db", "specification_lifecycle_test", "postgres"}:
        raise SystemExit("Refusing to seed an existing project database. Use a fresh database name.")
    if input(f"Type SEED to populate the EMPTY database '{database}': ") != "SEED":
        raise SystemExit("Cancelled")
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres", password=password,
                                      host="localhost", port=5432, database=database))
    rng = random.Random(42)
    today = date.today()
    with engine.begin() as conn:
        for table in ("employee_master", "specification_tracker", "stage_history", "sla_notifications"):
            count = conn.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
            if count:
                raise SystemExit(f"{table} already has {count} rows. Refusing to seed.")
        for i in range(1, 9):
            conn.execute(text("""INSERT INTO public.employee_master
                (employee_id, employee_name, department, role)
                VALUES (:id, :name, :department, :role)"""),
                {"id": f"EMP{i:03}", "name": f"Analyst {i}", "department": "Engineering",
                 "role": "Specification Reviewer"})
        for i in range(1, 101):
            stage = STAGES[(i - 1) % len(STAGES)]
            assigned = today - timedelta(days=rng.randint(10, 85))
            due = today + timedelta(days=rng.randint(-35, 25))
            if stage == "Published":
                completed = assigned + timedelta(days=rng.randint(3, 35))
                if completed > today:
                    completed = today
            else:
                completed = None
            employee = (i % 8) + 1
            sid = f"SPEC-{i:04}"
            conn.execute(text("""INSERT INTO public.specification_tracker
                (specification_id, specification_name, specification_type, assigned_to_id,
                 assigned_to, department, assigned_date, due_date, current_stage,
                 sme, hold_reason, sla_days, completion_date, priority, record_status)
                VALUES (:sid, :name, :kind, :emp_id, :emp, :department, :assigned, :due,
                        :stage, :sme, :hold, :sla, :completed, :priority, :status)"""),
                {"sid": sid, "name": f"Synthetic Specification {i:04}",
                 "kind": "Materials" if i % 2 else "Process", "emp_id": f"EMP{employee:03}",
                 "emp": f"Analyst {employee}", "department": "Engineering",
                 "assigned": assigned, "due": due, "stage": stage, "sme": "Synthetic SME",
                 "hold": "Awaiting synthetic review" if stage == "Hold" else None,
                 "sla": (due - assigned).days, "completed": completed,
                 "priority": ["Low", "Medium", "High"][i % 3],
                 "status": "Completed" if completed else "Active"})
            # A single dated transition gives a determinable current-stage start date.
            start = min(today, assigned + timedelta(days=rng.randint(1, 8)))
            conn.execute(text("""INSERT INTO public.stage_history
                (specification_id, previous_stage, new_stage, updated_date, updated_by, comment)
                VALUES (:sid, :old, :new, :day, :actor, :comment)"""),
                {"sid": sid, "old": "Assigned", "new": stage, "day": start,
                 "actor": "Synthetic Seeder", "comment": "Generated demonstration event"})
    print(f"Created 8 synthetic employees, 100 specifications and 100 history rows in {database}.")
    print("No notification rows seeded; generate them using the dashboard button.")

if __name__ == "__main__":
    main()
