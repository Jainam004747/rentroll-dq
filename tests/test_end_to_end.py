"""Runs the whole thing: planted problems are caught, then a clean load resolves them."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def project(tmp_path):
    work = tmp_path / "rentroll-dq"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("evidence", "*.duckdb*", "target", "logs", ".git", "__pycache__"))
    return work


def run(work, *args):
    return subprocess.run([sys.executable, *args], cwd=work, capture_output=True, text=True)


def test_issues_found_then_resolved(project):
    assert run(project, "scripts/generate_data.py").returncode == 0
    first = run(project, "-m", "dqmon", "run", "--operator", "ci")
    assert first.returncode == 1, first.stdout + first.stderr
    for expected in ["freshness", "uniqueness", "referential integrity", "reconciliation", "Rent Collection Dashboard"]:
        assert expected in first.stdout
    assert "Incidents: 6 opened" in first.stdout

    assert run(project, "scripts/generate_data.py", "--clean").returncode == 0
    second = run(project, "-m", "dqmon", "run", "--operator", "ci")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "6 resolved" in second.stdout
    assert run(project, "-m", "dqmon", "verify").returncode == 0
