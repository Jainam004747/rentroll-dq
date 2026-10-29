"""Generates the landing files for a small property portfolio.

The data is fake but shaped like a real rent roll: properties, units, leases, monthly rent
payments, and the control totals finance posts to the general ledger. A few problems are
planted on purpose so the checks have something to find:

  * one lease id appears twice                       (uniqueness)
  * one payment points at a lease that doesn't exist  (referential integrity)
  * one payment has a negative amount                 (validity)
  * one lease is missing its unit                     (completeness)
  * the units file was delivered 3 days ago           (freshness)
  * one property's payments don't match the GL total  (reconciliation)

Run with --clean to generate the same data without the planted problems.

    python scripts/generate_data.py            # with issues
    python scripts/generate_data.py --clean    # everything passes
"""
import argparse
import csv
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "landing"

CITIES = ["Toronto", "Vancouver", "Calgary", "Montreal", "Ottawa", "Halifax"]
TYPES = ["residential", "office", "retail", "industrial"]


def write(name, rows, loaded_at):
    OUT.mkdir(parents=True, exist_ok=True)
    for r in rows:
        r["_loaded_at"] = loaded_at.strftime("%Y-%m-%d %H:%M:%S")
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {name + '.csv':<22} {len(rows):>5} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="no planted issues")
    ap.add_argument("--month", default="2026-10", help="rent month, YYYY-MM")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    month_start = date.fromisoformat(args.month + "-01")

    properties, units, leases, payments, gl = [], [], [], [], []
    unit_id = lease_id = payment_id = 0
    for p in range(1, 13):
        pid = f"P{p:03d}"
        properties.append({"property_id": pid, "name": f"{rng.choice(['King', 'Bay', 'Front', 'Harbour', 'Granville', 'Robson'])} {rng.choice(['Tower', 'Place', 'Centre', 'Commons'])} {p}",
                           "city": rng.choice(CITIES), "asset_type": rng.choice(TYPES)})
        expected_total = 0
        for _ in range(rng.randint(15, 30)):
            unit_id += 1
            uid = f"U{unit_id:04d}"
            units.append({"unit_id": uid, "property_id": pid, "sq_ft": rng.randint(450, 4000)})
            if rng.random() < 0.88:  # occupied
                lease_id += 1
                rent = round(rng.uniform(1400, 9000), 2)
                start = month_start - timedelta(days=rng.randint(30, 900))
                leases.append({"lease_id": f"L{lease_id:05d}", "unit_id": uid, "tenant": f"Tenant {lease_id}",
                               "monthly_rent": rent, "start_date": start.isoformat(),
                               "end_date": (start + timedelta(days=rng.choice([365, 730, 1095]))).isoformat(),
                               "status": "active"})
                if rng.random() < 0.95:  # paid this month
                    payment_id += 1
                    payments.append({"payment_id": f"R{payment_id:06d}", "lease_id": f"L{lease_id:05d}",
                                     "paid_on": (month_start + timedelta(days=rng.randint(0, 9))).isoformat(),
                                     "amount": rent})
                    expected_total += rent
        gl.append({"property_id": pid, "rent_month": args.month, "gl_rent_total": round(expected_total, 2)})

    units_loaded = now - timedelta(hours=2)
    if not args.clean:
        dup = dict(leases[10]); dup["tenant"] = "Tenant duplicate"; leases.append(dup)
        payment_id += 1
        payments.append({"payment_id": f"R{payment_id:06d}", "lease_id": "L99999", "paid_on": month_start.isoformat(), "amount": 2100.00})
        payments[5]["amount"] = -payments[5]["amount"]
        leases[3]["unit_id"] = ""
        units_loaded = now - timedelta(days=3)
        gl[4]["gl_rent_total"] = round(gl[4]["gl_rent_total"] + 4850.00, 2)

    print(f"Writing landing files to {OUT.relative_to(OUT.parent.parent)}  ({'clean' if args.clean else 'with planted issues'})")
    write("properties", properties, now - timedelta(hours=2))
    write("units", units, units_loaded)
    write("leases", leases, now - timedelta(hours=2))
    write("rent_payments", payments, now - timedelta(hours=1))
    write("gl_rent_control", gl, now - timedelta(hours=1))


if __name__ == "__main__":
    main()
