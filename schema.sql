-- Specification Lifecycle & SLA Analytics
-- Schema based on the user's PostgreSQL 18 schema-only export.
-- Run ONLY against a new, empty database. Does not create a database.
BEGIN;
CREATE TABLE public.data_dictionary (
    table_name varchar(100), column_name varchar(100),
    description text, data_type varchar(50)
);
CREATE TABLE public.employee_master (
    employee_id varchar(10) PRIMARY KEY,
    employee_name varchar(100), department varchar(50), role varchar(100)
);
CREATE TABLE public.specification_tracker (
    specification_id varchar(20) PRIMARY KEY,
    specification_name varchar(150), specification_type varchar(100),
    assigned_to_id varchar(10) REFERENCES public.employee_master(employee_id),
    assigned_to varchar(100), department varchar(50),
    assigned_date date, due_date date, current_stage varchar(50),
    sme varchar(100), hold_reason text, sla_days integer,
    completion_date date, priority varchar(20), record_status varchar(20)
);
CREATE SEQUENCE public.stage_history_id_seq START 1;
CREATE TABLE public.stage_history (
    history_id varchar(20) PRIMARY KEY DEFAULT ('HIST-' || lpad(nextval('public.stage_history_id_seq')::text, 5, '0')),
    specification_id varchar(20) REFERENCES public.specification_tracker(specification_id),
    previous_stage varchar(50), new_stage varchar(50), updated_date date,
    updated_by varchar(100), comment text
);
ALTER SEQUENCE public.stage_history_id_seq OWNED BY public.stage_history.history_id;
CREATE TABLE public.sla_notifications (
    notification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    specification_id varchar(20) NOT NULL REFERENCES public.specification_tracker(specification_id),
    notification_type varchar(30) NOT NULL CHECK (notification_type IN ('Due Soon', 'Overdue')),
    notification_date date NOT NULL DEFAULT CURRENT_DATE,
    message text NOT NULL,
    is_read boolean NOT NULL DEFAULT false,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (specification_id, notification_type, notification_date)
);
COMMIT;
