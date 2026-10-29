# rentroll-dq

Daily data quality checks for a property portfolio's rent data, built on dbt and DuckDB.

Every morning the property management system drops CSV files (properties, units, leases, rent payments) and finance posts monthly rent totals to the GL. Before any of that reaches the Power BI reports, this project checks it, opens an incident for anything wrong, routes it to the team that owns the data, and keeps a sealed record of what was checked so it can be shown to an auditor later.

I built it to practise the day to day side of data quality work: turning business rules into checks, tuning alert thresholds so people don't ignore them, and keeping evidence that controls actually ran.

## What it checks

| Dimension | How | Example rule |
|---|---|---|
| Freshness | `dbt source freshness` on the `_loaded_at` column | warn after 24 h, error after 48 h |
| Uniqueness | dbt `unique` tests | one row per lease id |
| Completeness | dbt `not_null` tests | every lease has a unit |
| Referential integrity | dbt `relationships` tests | every payment points at a real lease |
| Validity | `accepted_values` plus my own `positive_value` and `not_in_future` tests | rent amounts are above zero |
| Reconciliation | a singular dbt test | payments per property per month equal the GL control total |
| Volume | row count compared with the file's own history (median and MAD) | `rent_payments` stays within its normal range |
| Schema | columns and types compared with the last run | a renamed or retyped column is caught before dbt breaks |

dbt runs with `build`, so a failing test stops the models that depend on it. Bad data doesn't flow into the report tables; the reports keep showing the last good load, and the run output says which tables were held back.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/generate_data.py          # landing files with a few planted problems
python scripts/backfill_history.py       # 45 days of row-count history for the volume checks
python -m dqmon run                      # run everything, open incidents, write evidence

python scripts/generate_data.py --clean  # the "fixed" files
python -m dqmon run                      # incidents get resolved

python -m dqmon incidents                # incident list
python -m dqmon tune                     # compare threshold methods on the history
python -m dqmon verify                   # check that no evidence was edited
pytest -q                                # tests
```

## Output

### Morning run with problems in the files

The generator plants six problems: a stale units file, a duplicate lease, a lease with no unit, a payment for a lease that doesn't exist, a negative payment, and a GL total that doesn't match.

```text
$ python -m dqmon run --operator jainam
rentroll-dq   run 20261029T033621Z   operator jainam
========================================================================
Checks 34   passed 27   failed 6   warnings 0   skipped 1

Dimension                 pass  fail
  completeness               6     1
  freshness                  4     1
  reconciliation             0     1
  referential integrity      2     1
  schema                     5     0
  uniqueness                 4     1
  validity                   4     1
  volume                     2     0

Failures
  [HIGH] completeness          stg_leases
         not_null on stg_leases.unit_id: 1 bad row(s)
         owner: Leasing data stewards (leasing-data@example.com)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)
  [HIGH] freshness             source:landing.units
         last load 72.0 h ago (limit: warn 24 h, error 48 h)
         owner: Data Engineering (ingestion) (#de-ingestion)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)
  [HIGH] reconciliation        stg_rent_payments
         assert_rent_reconciles_to_gl: 2 bad row(s)
         owner: Portfolio Finance stewards (finance-data@example.com)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)
  [HIGH] referential integrity stg_rent_payments
         relationships on stg_rent_payments.lease_id: 1 bad row(s)
         owner: Portfolio Finance stewards (finance-data@example.com)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)
  [HIGH] uniqueness            stg_leases
         unique on stg_leases.lease_id: 1 bad row(s)
         owner: Leasing data stewards (leasing-data@example.com)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)
  [HIGH] validity              stg_rent_payments
         positive_value on stg_rent_payments.amount: 1 bad row(s)
         owner: Portfolio Finance stewards (finance-data@example.com)
         reports at risk: Portfolio Occupancy Report (Power BI), Rent Collection Dashboard (Power BI)

Not refreshed (blocked by failing tests, still showing the last good data): fct_rent_collection

Incidents: 6 opened, 0 still open, 0 resolved
  #1   opened    freshness.landing.units  -> Data Engineering (ingestion)
  #2   opened    test.not_null_stg_leases_unit_id  -> Leasing data stewards
  #3   opened    test.unique_stg_leases_lease_id  -> Leasing data stewards
  #4   opened    test.positive_value_stg_rent_payments_amount  -> Portfolio Finance stewards
  #5   opened    test.relationships_stg_rent_payments_lease_id__lease_id__ref_stg_leases_  -> Portfolio Finance stewards
  #6   opened    test.assert_rent_reconciles_to_gl  -> Portfolio Finance stewards

Evidence: evidence/20261029T033621Z/  (sealed, manifest sha256 b42b14cab4d9...)
```

The exit code is 1, so Airflow (or any scheduler) marks the task as failed.

### After the source teams send corrected files

```text
$ python -m dqmon run --operator jainam
rentroll-dq   run 20261029T033628Z   operator jainam
========================================================================
Checks 34   passed 34   failed 0   warnings 0   skipped 0

Dimension                 pass  fail
  completeness               8     0
  freshness                  5     0
  reconciliation             1     0
  referential integrity      3     0
  schema                     5     0
  uniqueness                 5     0
  validity                   5     0
  volume                     2     0

Incidents: 0 opened, 0 still open, 6 resolved
  #1   resolved  freshness.landing.units
  #2   resolved  test.not_null_stg_leases_unit_id
  #3   resolved  test.unique_stg_leases_lease_id
  #4   resolved  test.positive_value_stg_rent_payments_amount
  #5   resolved  test.relationships_stg_rent_payments_lease_id__lease_id__ref_stg_leases_
  #6   resolved  test.assert_rent_reconciles_to_gl

Evidence: evidence/20261029T033628Z/  (sealed, manifest sha256 e3b8d2d81df0...)
```

### Incident history

Each failing check opens one incident. If it keeps failing it stays the same incident, so the owner gets one ticket instead of one per run. The run that resolved it is recorded too.

```text
$ python -m dqmon incidents
#   status    sev   check                                                     owner                          runs  opened / resolved
1   resolved  high  freshness.landing.units                                   Data Engineering (ingestion)      1  20261029T033621Z / 20261029T033628Z
2   resolved  high  test.not_null_stg_leases_unit_id                          Leasing data stewards             1  20261029T033621Z / 20261029T033628Z
3   resolved  high  test.unique_stg_leases_lease_id                           Leasing data stewards             1  20261029T033621Z / 20261029T033628Z
4   resolved  high  test.positive_value_stg_rent_payments_amount              Portfolio Finance stewards        1  20261029T033621Z / 20261029T033628Z
5   resolved  high  test.relationships_stg_rent_payments_lease_id__lease_id_  Portfolio Finance stewards        1  20261029T033621Z / 20261029T033628Z
6   resolved  high  test.assert_rent_reconciles_to_gl                         Portfolio Finance stewards        1  20261029T033621Z / 20261029T033628Z
```

### Tuning the volume threshold

The history has normal noise, a small legitimate bump on the 1st of the month (pre-authorised payments), a day the file was loaded twice (440 rows) and a day it arrived cut off (112 rows). `tune` replays the history day by day and shows which days each method would have alerted on:

```text
$ python -m dqmon tune
Threshold replay for rows.rent_payments: 47 days of history, window 30, warm-up 7

  fixed +/-5%    8 alerts  Oct 01=229, Oct 02=440, Oct 03=222, Oct 09=226, Oct 16=112, Oct 17=224, Oct 24=204, Oct 25=217
  zscore k=3     1 alerts  Oct 02=440
  mad k=4        3 alerts  Oct 01=229, Oct 02=440, Oct 16=112
  mad k=5        2 alerts  Oct 02=440, Oct 16=112

Bounds for the next run with mad k=5 over the last 30 days: 198 to 236 rows
```

What this shows:

- A fixed +/-5% against the previous day alerts 8 times. Most of those are noise, and it also fires the day after each bad day. People stop reading alerts like that.
- Mean and standard deviation (z-score) catches the duplicate load, but that one huge day inflates the standard deviation, so the cut-off file two weeks later slips through. That's the worst outcome: a real problem with no alert.
- Median and MAD isn't pulled around by one bad day. With k=4 it also flags the month-start bump; with k=5 it alerts on exactly the two real problems. `dq.yml` uses k=5.

### Evidence

Every run writes a folder that can be handed to an auditor as is:

```text
evidence/20261029T033621Z/
  run.json              who ran it, when, which commit of the checks, outcome
  results.json          every check result
  incidents.json        incident register at the end of the run
  summary.txt           the console report above
  dbt_sources.json      raw dbt freshness results
  dbt_run_results.json  raw dbt test results
  dbt_manifest.json     the dbt project as it was at that moment
  MANIFEST.sha256       SHA-256 of every file above + hash of the previous run's manifest
```

```text
$ cat evidence/.../run.json
{
  "run_id": "20261029T033621Z",
  "started_at": "2026-10-29T03:36:21+00:00",
  "finished_at": "2026-10-29T03:36:26+00:00",
  "operator": "jainam",
  "project_commit": "db84e52",
  "dbt_version": "1.12.6",
  "outcome": "failed",
  "checks": 34,
  "failed": 6
}
```

Because each manifest includes the previous run's hash, the runs form a chain. If someone edits an old result to make it look like a check passed, `verify` catches it:

```text
$ python -m dqmon verify
  20261029T033621Z  OK        ok
  20261029T033628Z  OK        ok

All evidence intact.

# after changing a failed freshness result to "pass" in the first run's results.json:
$ python -m dqmon verify
  20261029T033621Z  TAMPERED  results.json was modified after the run
  20261029T033628Z  OK        ok

1 run(s) failed verification.
```

### The report table once the data is clean

```text
property  name                 occupancy    expected   collected  collected %
P001      Front Place 1            88.2%   76,921.61   76,921.61       100.0%
P002      Harbour Commons 2        95.0%   91,029.24   82,052.17        90.1%
P003      Granville Tower 3        82.4%   78,263.72   78,263.72       100.0%
P004      Granville Place 4        90.5%  117,448.21  111,149.87        94.6%
P005      Front Tower 5            94.1%   66,248.02   61,459.75        92.8%
P006      King Commons 6           81.3%   77,286.70   72,398.52        93.7%
```

## How it's put together

```text
data/landing/*.csv ──▶ dbt sources (freshness) ──▶ staging views + tests ──▶ marts ──▶ Power BI exposures
                                    │                        │
                                    ▼                        ▼
                 dqmon: volume + schema checks      dbt artifacts (run_results, manifest)
                                    │
                                    ▼
           results ──▶ incidents (owner routing) ──▶ evidence/<run_id>/ sealed with SHA-256
```

| Path | What's in it |
|---|---|
| `dbt/models/staging/` | sources with freshness rules, typed staging views, column tests |
| `dbt/models/marts/` | `dim_property`, `fct_rent_collection`, and the Power BI reports declared as dbt exposures |
| `dbt/tests/` | the GL reconciliation test and two custom generic tests |
| `dq.yml` | data owners and the extra checks (volume, schema) |
| `dqmon/dbt_artifacts.py` | runs dbt and turns its JSON artifacts into check results with a dimension and an owner |
| `dqmon/checks.py` | volume thresholds (z-score and MAD) and schema drift |
| `dqmon/incidents.py` | open, update and resolve incidents |
| `dqmon/impact.py` | walks the dbt lineage graph to find which reports a failure can affect |
| `dqmon/evidence.py` | writes and verifies the hash chain |
| `airflow/dags/rentroll_dq.py` | the daily schedule: run the checks, then verify evidence even if the checks failed |

## Decisions

- **Rules live in dbt where possible.** dbt tests are versioned, reviewed and documented with the models they protect. dqmon only adds what dbt doesn't do well: volume history, schema drift, incidents and evidence.
- **Owners come from config, not code.** Routing a lease problem to the leasing stewards is a governance decision, so it sits in `dq.yml` where it can be reviewed and changed without touching Python.
- **Impact comes from lineage.** Reports are declared as dbt exposures, so "which dashboards are affected" is a graph walk instead of tribal knowledge.
- **Evidence is written even when checks fail.** A failed control with a clean record is still evidence. The Airflow DAG runs `verify` with `trigger_rule="all_done"` for the same reason.
- **DuckDB locally.** It keeps the project runnable on a laptop and in CI. The dbt project only needs a different profile to run on a cloud warehouse.

## Limitations

- One month of data per run; a real setup would partition by load date.
- Incidents live in the warehouse. In practice they'd also go to a ticketing tool or chat channel.
- The evidence chain proves files weren't changed after the run, but someone with write access could rewrite the whole chain. Shipping each run's manifest hash to write-once storage would close that gap.
