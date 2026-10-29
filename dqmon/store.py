"""Tables dqmon keeps next to the data in the warehouse.

dq_runs        one row per monitoring run (who ran it, when, outcome, evidence hash)
dq_results     every check result of every run
dq_metrics     numbers tracked over time (row counts) for anomaly thresholds
dq_schema      column snapshot of each landing file, to spot schema drift
dq_incidents   open and resolved incidents, one per failing check
"""
import duckdb

DDL = """
create table if not exists dq_runs (
    run_id varchar primary key, started_at timestamp, finished_at timestamp,
    operator varchar, outcome varchar, checks integer, failures integer, evidence_sha256 varchar);
create table if not exists dq_results (
    run_id varchar, check_id varchar, kind varchar, dimension varchar, object varchar,
    status varchar, severity varchar, failures integer, message varchar, owner varchar);
create table if not exists dq_metrics (
    run_id varchar, measured_at timestamp, metric varchar, value double);
create table if not exists dq_schema (
    run_id varchar, source varchar, column_name varchar, data_type varchar);
create table if not exists dq_incidents (
    incident_id integer primary key, check_id varchar, object varchar, dimension varchar,
    severity varchar, owner varchar, status varchar, opened_run varchar, opened_at timestamp,
    last_seen_run varchar, occurrences integer, resolved_run varchar, resolved_at timestamp,
    message varchar);
"""


def connect(path):
    con = duckdb.connect(str(path))
    con.execute(DDL)
    return con
