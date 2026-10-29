"""Airflow DAG that runs the checks every morning after the landing files arrive.

The task fails (and Airflow alerts) when any high-severity check fails, so a broken load
never gets marked as a successful day. Evidence is written whatever the outcome.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT = "/opt/rentroll-dq"

with DAG(
    dag_id="rentroll_daily_quality",
    schedule="30 6 * * *",           # after the 06:00 landing drop
    start_date=datetime(2026, 10, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
    tags=["data-quality", "controls"],
) as dag:
    checks = BashOperator(
        task_id="run_quality_checks",
        bash_command=f"cd {PROJECT} && python -m dqmon run --operator airflow",
        execution_timeout=timedelta(minutes=20),
    )
    verify = BashOperator(
        task_id="verify_evidence_chain",
        bash_command=f"cd {PROJECT} && python -m dqmon verify",
        trigger_rule="all_done",       # verify evidence even when the checks failed
    )
    checks >> verify
