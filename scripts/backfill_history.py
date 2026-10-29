"""Loads 45 days of past row counts so the volume checks have history to learn from.

The history is simulated, but it has the things real history has:
  * normal day-to-day noise
  * a small, legitimate bump on the 1st of each month (pre-authorised payments land)
  * one day where the file was loaded twice (row count doubles)
  * one day where the file arrived cut off (row count drops by half)

`python -m dqmon tune` replays this history to compare threshold methods.
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dqmon import store  # noqa: E402

WAREHOUSE = Path(__file__).resolve().parent.parent / "warehouse.duckdb"


def main():
    rng = random.Random(3)
    con = store.connect(WAREHOUSE)
    con.execute("delete from dq_metrics where run_id like 'backfill-%'")
    today = date.today()
    rows = []
    for i in range(45, 0, -1):
        d = today - timedelta(days=i)
        payments = round(rng.gauss(218, 4))
        if d.day == 1:
            payments += 10                    # legitimate month-start bump
        if i == 26:
            payments *= 2                     # file loaded twice
        if i == 12:
            payments = payments // 2          # file cut off
        leases = round(rng.gauss(231, 1.5))
        tag = f"backfill-{d:%Y%m%d}"
        rows += [[tag, f"{d} 06:00:00", "rows.rent_payments", payments], [tag, f"{d} 06:00:00", "rows.leases", leases]]
    con.executemany("insert into dq_metrics values (?, ?::timestamp, ?, ?)", rows)
    print(f"Loaded {len(rows)} metric points covering {today - timedelta(days=45)} to {today - timedelta(days=1)}")
    print(f"  duplicate load on {today - timedelta(days=26)}, cut-off file on {today - timedelta(days=12)}")


if __name__ == "__main__":
    main()
