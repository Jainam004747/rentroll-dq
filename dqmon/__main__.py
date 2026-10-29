"""dqmon: runs the daily data quality checks and keeps the evidence.

    python -m dqmon run          freshness + dbt build + extra checks, incidents, evidence
    python -m dqmon incidents    open and recently resolved incidents
    python -m dqmon tune         compare threshold methods on the metric history
    python -m dqmon verify       re-check every evidence folder for tampering
"""
import argparse
import getpass
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import checks, evidence, impact, incidents, store
from .dbt_artifacts import collect, freshness_results, test_results

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "dbt"
LANDING = ROOT / "data" / "landing"
EVIDENCE = ROOT / "evidence"
WAREHOUSE = ROOT / "warehouse.duckdb"
LANDING_SOURCES = ["properties", "units", "leases", "rent_payments", "gl_rent_control"]


def load_config():
    return yaml.safe_load((ROOT / "dq.yml").read_text())


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def cmd_run(args):
    cfg = load_config()
    owners = cfg["owners"]
    started = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVIDENCE / run_id
    run_dir.mkdir(parents=True)
    os.environ["DQ_WAREHOUSE"] = str(WAREHOUSE)
    os.environ["DQ_LANDING"] = str(LANDING)

    sources, run_results, manifest = collect(DBT_DIR, run_dir)  # dbt needs the warehouse to itself
    results = freshness_results(sources, owners) + test_results(run_results, manifest, owners)

    con = store.connect(WAREHOUSE)
    for c in cfg.get("checks", []):
        if c["type"] == "volume":
            results.append(checks.volume_check(con, c, run_id, LANDING, owners))
        elif c["type"] == "schema":
            results.extend(checks.schema_check(con, run_id, LANDING, LANDING_SOURCES, owners))

    opened, updated, resolved = incidents.sync(con, run_id, results)
    failed = [r for r in results if r.failed]
    blocking = [r for r in failed if r.severity == "error"]
    outcome = "failed" if blocking else ("passed with warnings" if failed else "passed")
    con.executemany("insert into dq_results values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [[run_id, r.check_id, r.kind, r.dimension, r.object, r.status, r.severity, r.failures,
                      r.message, r.owner.get("team", "")] for r in results])

    # Evidence: who, when, what code, what was found
    evidence.write_json(run_dir / "run.json", {
        "run_id": run_id, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "operator": args.operator or getpass.getuser(), "project_commit": git_commit(),
        "dbt_version": manifest["metadata"]["dbt_version"], "outcome": outcome,
        "checks": len(results), "failed": len(failed)})
    evidence.write_json(run_dir / "results.json", [r.__dict__ for r in results])
    rows = con.execute("select * from dq_incidents order by incident_id").fetchall()
    cols = [d[0] for d in con.description]
    evidence.write_json(run_dir / "incidents.json", [dict(zip(cols, row)) for row in rows])
    skipped = impact.skipped_models(run_results)
    summary = report(run_id, args.operator or getpass.getuser(), results, manifest, skipped, opened, updated, resolved)
    (run_dir / "summary.txt").write_text(summary)
    previous = con.execute("select evidence_sha256 from dq_runs order by run_id desc limit 1").fetchone()
    digest = evidence.seal(run_dir, previous[0] if previous else None)
    con.execute("insert into dq_runs values (?, ?, timezone('UTC', now()), ?, ?, ?, ?, ?)",
                [run_id, started.replace(tzinfo=None), args.operator or getpass.getuser(), outcome, len(results), len(failed), digest])
    con.close()

    print(summary)
    print(f"Evidence: evidence/{run_id}/  (sealed, manifest sha256 {digest[:12]}...)")
    return 1 if blocking else 0


def report(run_id, operator, results, manifest, skipped, opened, updated, resolved):
    status = Counter(r.status for r in results)
    lines = [f"rentroll-dq   run {run_id}   operator {operator}", "=" * 72,
             f"Checks {len(results)}   passed {status['pass']}   failed {status['fail'] + status['error']}"
             f"   warnings {status['warn']}   skipped {status['skip']}", "",
             f"{'Dimension':<24}{'pass':>6}{'fail':>6}"]
    dims = sorted({r.dimension for r in results})
    for d in dims:
        rs = [r for r in results if r.dimension == d and r.status != "skip"]
        lines.append(f"  {d:<22}{sum(not r.failed for r in rs):>6}{sum(r.failed for r in rs):>6}")
    failed = [r for r in results if r.failed]
    if failed:
        lines += ["", "Failures"]
        for r in sorted(failed, key=lambda r: (r.severity != "error", r.dimension)):
            sev = "HIGH" if r.severity == "error" else "LOW "
            lines.append(f"  [{sev}] {r.dimension:<21} {r.object}")
            lines.append(f"         {r.message}")
            lines.append(f"         owner: {r.owner.get('team', '?')} ({r.owner.get('contact', '')})")
            reports = impact.downstream_exposures(manifest, r.object)
            if reports:
                lines.append(f"         reports at risk: {', '.join(reports)}")
    if skipped:
        lines += ["", f"Not refreshed (blocked by failing tests, still showing the last good data): {', '.join(skipped)}"]
    lines += ["", f"Incidents: {len(opened)} opened, {len(updated)} still open, {len(resolved)} resolved"]
    for iid, r in opened:
        lines.append(f"  #{iid:<3} opened    {r.check_id}  -> {r.owner.get('team', '?')}")
    for iid, r in sorted(resolved, key=lambda x: x[0]):
        lines.append(f"  #{iid:<3} resolved  {r.check_id}")
    return "\n".join(lines) + "\n"


def cmd_incidents(args):
    con = store.connect(WAREHOUSE)
    rows = con.execute("""select incident_id, status, severity, check_id, owner, occurrences, opened_run, coalesce(resolved_run, '')
                          from dq_incidents order by status desc, incident_id""").fetchall()
    print(f"{'#':<4}{'status':<10}{'sev':<6}{'check':<58}{'owner':<30}{'runs':>5}  opened / resolved")
    for r in rows:
        print(f"{r[0]:<4}{r[1]:<10}{r[2]:<6}{r[3][:56]:<58}{r[4][:28]:<30}{r[5]:>5}  {r[6]} / {r[7] or '-'}")
    return 0


def cmd_tune(args):
    """Replays the metric history day by day and shows which days each method would alert on."""
    con = store.connect(WAREHOUSE)
    metric = f"rows.{args.source}"
    hist = con.execute("select measured_at::date, value from dq_metrics where metric = ? order by measured_at", [metric]).fetchall()
    if len(hist) < 10:
        print(f"Not enough history for {metric} ({len(hist)} points). Run scripts/backfill_history.py first.")
        return 1
    methods = [("fixed +/-5%", None), ("zscore k=3", ("zscore", 3)), ("mad k=4", ("mad", 4)), ("mad k=5", ("mad", 5))]
    print(f"Threshold replay for {metric}: {len(hist)} days of history, window 30, warm-up 7\n")
    for label, m in methods:
        alerts = []
        for i in range(7, len(hist)):
            window = [v for _, v in hist[max(0, i - 30):i]]
            if m is None:
                prev = window[-1]
                low, high = prev * 0.95, prev * 1.05
            else:
                low, high = checks.threshold(window, *m)
            day, v = hist[i]
            if not low <= v <= high:
                alerts.append(f"{day:%b %d}={v:.0f}")
        print(f"  {label:<13} {len(alerts):>2} alerts  {', '.join(alerts)}")
    window = [v for _, v in hist[-30:]]
    low, high = checks.threshold(window, "mad", 5)
    print(f"\nBounds for the next run with mad k=5 over the last 30 days: {low:.0f} to {high:.0f} rows")
    return 0


def cmd_verify(args):
    if not EVIDENCE.exists():
        print("No evidence yet.")
        return 1
    bad = 0
    for run_id, ok, msg in evidence.verify(EVIDENCE):
        print(f"  {run_id}  {'OK      ' if ok else 'TAMPERED'}  {msg}")
        bad += not ok
    print(f"\n{'All evidence intact.' if not bad else f'{bad} run(s) failed verification.'}")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dqmon", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run all checks and write evidence")
    r.add_argument("--operator", help="name recorded in the evidence (default: your OS user)")
    sub.add_parser("incidents", help="list incidents")
    t = sub.add_parser("tune", help="compare threshold methods on history")
    t.add_argument("--source", default="rent_payments")
    sub.add_parser("verify", help="verify evidence has not been modified")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "incidents": cmd_incidents, "tune": cmd_tune, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
