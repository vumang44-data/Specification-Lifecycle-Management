--
-- PostgreSQL database dump
--

\restrict c6GhOWxbQfIFSkH3MlFuH31T3zRADCh1PlZKZcuD7nnmZaAf0Ob6mNYBE62RFzh

-- Dumped from database version 18.7
-- Dumped by pg_dump version 18.7

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: data_dictionary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.data_dictionary (
    table_name character varying(100),
    column_name character varying(100),
    description text,
    data_type character varying(50)
);


--
-- Name: employee_master; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employee_master (
    employee_id character varying(10) NOT NULL,
    employee_name character varying(100),
    department character varying(50),
    role character varying(100)
);


--
-- Name: sla_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sla_notifications (
    notification_id bigint NOT NULL,
    specification_id character varying(20) NOT NULL,
    notification_type character varying(30) NOT NULL,
    notification_date date DEFAULT CURRENT_DATE NOT NULL,
    message text NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT sla_notifications_notification_type_check CHECK (((notification_type)::text = ANY ((ARRAY['Due Soon'::character varying, 'Overdue'::character varying])::text[])))
);


--
-- Name: sla_notifications_notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.sla_notifications ALTER COLUMN notification_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.sla_notifications_notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: specification_tracker; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.specification_tracker (
    specification_id character varying(20) NOT NULL,
    specification_name character varying(150),
    specification_type character varying(100),
    assigned_to_id character varying(10),
    assigned_to character varying(100),
    department character varying(50),
    assigned_date date,
    due_date date,
    current_stage character varying(50),
    sme character varying(100),
    hold_reason text,
    sla_days integer,
    completion_date date,
    priority character varying(20),
    record_status character varying(20)
);


--
-- Name: stage_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.stage_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stage_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stage_history (
    history_id character varying(20) DEFAULT ('HIST-'::text || lpad((nextval('public.stage_history_id_seq'::regclass))::text, 5, '0'::text)) NOT NULL,
    specification_id character varying(20),
    previous_stage character varying(50),
    new_stage character varying(50),
    updated_date date,
    updated_by character varying(100),
    comment text
);


--
-- Name: employee_master employee_master_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employee_master
    ADD CONSTRAINT employee_master_pkey PRIMARY KEY (employee_id);


--
-- Name: sla_notifications sla_notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_notifications
    ADD CONSTRAINT sla_notifications_pkey PRIMARY KEY (notification_id);


--
-- Name: sla_notifications sla_notifications_specification_id_notification_type_notifi_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_notifications
    ADD CONSTRAINT sla_notifications_specification_id_notification_type_notifi_key UNIQUE (specification_id, notification_type, notification_date);


--
-- Name: specification_tracker specification_tracker_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specification_tracker
    ADD CONSTRAINT specification_tracker_pkey PRIMARY KEY (specification_id);


--
-- Name: stage_history stage_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stage_history
    ADD CONSTRAINT stage_history_pkey PRIMARY KEY (history_id);


--
-- Name: sla_notifications sla_notifications_specification_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_notifications
    ADD CONSTRAINT sla_notifications_specification_id_fkey FOREIGN KEY (specification_id) REFERENCES public.specification_tracker(specification_id);


--
-- Name: specification_tracker specification_tracker_assigned_to_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.specification_tracker
    ADD CONSTRAINT specification_tracker_assigned_to_id_fkey FOREIGN KEY (assigned_to_id) REFERENCES public.employee_master(employee_id);


--
-- Name: stage_history stage_history_specification_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stage_history
    ADD CONSTRAINT stage_history_specification_id_fkey FOREIGN KEY (specification_id) REFERENCES public.specification_tracker(specification_id);


--
-- PostgreSQL database dump complete
--

\unrestrict c6GhOWxbQfIFSkH3MlFuH31T3zRADCh1PlZKZcuD7nnmZaAf0Ob6mNYBE62RFzh

