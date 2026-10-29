import duckdb

from dqmon import checks, evidence, incidents, store
from dqmon.dbt_artifacts import CheckResult


def test_mad_ignores_one_bad_day_that_inflates_zscore():
    history = [218, 221, 215, 219, 223, 217, 220, 216, 440, 218, 222, 219]
    z_low, z_high = checks.threshold(history, "zscore", 3)
    m_low, m_high = checks.threshold(history, "mad", 5)
    # A cut-off file with half the rows: z-score's band got too wide after the 440 day
    assert z_low < 112 < z_high
    assert not m_low <= 112 <= m_high
    assert m_low <= 225 <= m_high


def test_flat_history_still_has_a_band():
    low, high = checks.threshold([100] * 10, "mad", 5)
    assert low < 100 < high


def _result(check_id, status):
    return CheckResult(check_id=check_id, kind="dbt_test", dimension="uniqueness", object="stg_leases",
                       status=status, severity="error", owner={"team": "Leasing"})


def test_incident_opens_once_then_resolves(tmp_path):
    con = store.connect(tmp_path / "w.duckdb")
    opened, _, _ = incidents.sync(con, "r1", [_result("t.unique", "fail")])
    assert len(opened) == 1
    opened, updated, _ = incidents.sync(con, "r2", [_result("t.unique", "fail")])
    assert not opened and len(updated) == 1
    _, _, resolved = incidents.sync(con, "r3", [_result("t.unique", "pass")])
    assert len(resolved) == 1
    row = con.execute("select status, occurrences, resolved_run from dq_incidents").fetchone()
    assert row == ("resolved", 2, "r3")


def test_evidence_detects_edits_and_breaks_the_chain(tmp_path):
    a, b = tmp_path / "20260101T000000Z", tmp_path / "20260102T000000Z"
    a.mkdir(); b.mkdir()
    (a / "results.json").write_text('{"failed": 0}')
    (b / "results.json").write_text('{"failed": 3}')
    h = evidence.seal(a, None)
    evidence.seal(b, h)
    assert all(ok for _, ok, _ in evidence.verify(tmp_path))

    (a / "results.json").write_text('{"failed": 0, "note": "edited later"}')
    report = evidence.verify(tmp_path)
    assert report[0][1] is False and "modified" in report[0][2]

    (a / "results.json").write_text('{"failed": 0}')
    (a / "MANIFEST.sha256").write_text((a / "MANIFEST.sha256").read_text() + "\n")
    report = evidence.verify(tmp_path)
    assert report[1][1] is False and "chain broken" in report[1][2]


def test_schema_drift_is_reported(tmp_path):
    con = store.connect(tmp_path / "w.duckdb")
    (tmp_path / "units.csv").write_text("unit_id,property_id,sq_ft\nU1,P1,500\n")
    first = checks.schema_check(con, "r1", tmp_path, ["units"], {})
    assert first[0].status == "pass"
    (tmp_path / "units.csv").write_text("unit_id,property_id,area_m2\nU1,P1,46.5\n")
    second = checks.schema_check(con, "r2", tmp_path, ["units"], {})
    assert second[0].status == "fail"
    assert "added area_m2" in second[0].message and "removed sq_ft" in second[0].message
