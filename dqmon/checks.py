"""Checks that dbt tests don't cover well: volume anomalies and schema drift."""
import statistics

from .dbt_artifacts import CheckResult, owner_for


def threshold(history, method="mad", k=4.0):
    """Returns (low, high) bounds for the next value, learned from past values.

    zscore: mean +/- k * standard deviation. Simple, but one past spike inflates the std
            and hides real problems, and a few spikes in history cause false alerts.
    mad:    median +/- k * 1.4826 * MAD (median absolute deviation). Robust to spikes;
            1.4826 makes the MAD comparable to a standard deviation for normal data.
    """
    if method == "zscore":
        mean, sd = statistics.fmean(history), statistics.pstdev(history)
        return mean - k * sd, mean + k * sd
    med = statistics.median(history)
    mad = statistics.median(abs(x - med) for x in history) * 1.4826
    mad = max(mad, med * 0.01)  # don't let a perfectly flat history give a zero-width band
    return med - k * mad, med + k * mad


def volume_check(con, cfg, run_id, landing_dir, owners):
    """Counts rows in today's landing file and compares with the history of earlier runs."""
    source = cfg["source"]
    path = f"{landing_dir}/{source}.csv"
    count = con.execute(f"select count(*) from read_csv('{path}', header = true)").fetchone()[0]
    history = [v for (v,) in con.execute(
        "select value from dq_metrics where metric = ? order by measured_at desc limit 30", [f"rows.{source}"]).fetchall()]
    con.execute("insert into dq_metrics values (?, now(), ?, ?)", [run_id, f"rows.{source}", count])
    base = dict(check_id=cfg["id"], kind="volume", dimension="volume", object=f"source:landing.{source}",
                owner=owner_for(f"source:landing.{source}", owners))
    if len(history) < cfg.get("min_history", 7):
        return CheckResult(**base, status="pass", severity="warn",
                           message=f"{count} rows (learning: {len(history)} of {cfg.get('min_history', 7)} runs of history)")
    low, high = threshold(history, cfg.get("method", "mad"), cfg.get("k", 4))
    ok = low <= count <= high
    return CheckResult(**base, status="pass" if ok else "fail", severity="error",
                       failures=0 if ok else 1,
                       message=f"{count} rows, expected {low:.0f} to {high:.0f} from {len(history)} runs")


def schema_check(con, run_id, landing_dir, sources, owners):
    """Compares each landing file's columns and types with the previous run."""
    out = []
    prev_run = con.execute("select max(run_id) from dq_schema").fetchone()[0]
    for source in sources:
        cols = con.execute(f"describe select * from read_csv('{landing_dir}/{source}.csv', header = true)").fetchall()
        now = {c[0]: c[1] for c in cols}
        con.executemany("insert into dq_schema values (?, ?, ?, ?)", [[run_id, source, c, t] for c, t in now.items()])
        before = {c: t for c, t in con.execute(
            "select column_name, data_type from dq_schema where run_id = ? and source = ?", [prev_run, source]).fetchall()} if prev_run else {}
        changes = []
        if before:
            changes += [f"added {c}" for c in now.keys() - before.keys()]
            changes += [f"removed {c}" for c in before.keys() - now.keys()]
            changes += [f"{c} {before[c]} -> {now[c]}" for c in now.keys() & before.keys() if now[c] != before[c]]
        out.append(CheckResult(
            check_id=f"schema.{source}", kind="schema", dimension="schema", object=f"source:landing.{source}",
            status="fail" if changes else "pass", severity="error", failures=len(changes),
            message=("; ".join(sorted(changes))) if changes else (f"{len(now)} columns, unchanged" if before else f"{len(now)} columns (first snapshot)"),
            owner=owner_for(f"source:landing.{source}", owners)))
    return out
