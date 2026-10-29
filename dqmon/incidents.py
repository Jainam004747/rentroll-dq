"""Turns failing checks into incidents, without opening a new one every run.

A check that keeps failing keeps the same incident open (occurrences goes up), so the owner
gets one ticket, not one per run. When the check passes again the incident is resolved and
the resolving run is recorded, which is the evidence that the fix worked.
"""


def sync(con, run_id, results):
    opened, updated, resolved = [], [], []
    open_by_check = {row[1]: row for row in con.execute(
        "select incident_id, check_id from dq_incidents where status = 'open'").fetchall()}
    next_id = con.execute("select coalesce(max(incident_id), 0) + 1 from dq_incidents").fetchone()[0]
    for r in results:
        if r.status == "skip":
            continue
        existing = open_by_check.get(r.check_id)
        if r.failed and existing is None:
            con.execute("""insert into dq_incidents values (?, ?, ?, ?, ?, ?, 'open', ?, now(), ?, 1, null, null, ?)""",
                        [next_id, r.check_id, r.object, r.dimension, "high" if r.severity == "error" else "low",
                         r.owner.get("team", ""), run_id, run_id, r.message])
            opened.append((next_id, r))
            next_id += 1
        elif r.failed:
            con.execute("""update dq_incidents set last_seen_run = ?, occurrences = occurrences + 1, message = ?
                           where incident_id = ?""", [run_id, r.message, existing[0]])
            updated.append((existing[0], r))
        elif existing is not None:
            con.execute("""update dq_incidents set status = 'resolved', resolved_run = ?, resolved_at = now()
                           where incident_id = ?""", [run_id, existing[0]])
            resolved.append((existing[0], r))
    return opened, updated, resolved
