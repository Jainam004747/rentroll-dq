"""Runs dbt and turns its artifacts into plain check results.

dbt writes everything we need as JSON in target/:
  sources.json      source freshness results
  run_results.json  status of every model and test in the build
  manifest.json     the project graph: tests, models, sources, exposures and how they connect
"""
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# What each kind of test tells us about the data
DIMENSIONS = {
    "unique": "uniqueness",
    "not_null": "completeness",
    "relationships": "referential integrity",
    "accepted_values": "validity",
    "positive_value": "validity",
    "not_in_future": "validity",
}


@dataclass
class CheckResult:
    check_id: str
    kind: str          # freshness | dbt_test | volume | schema
    dimension: str     # freshness, uniqueness, completeness, validity, ...
    object: str        # the model or source the check is about
    status: str        # pass | warn | fail | error | skip
    severity: str      # error | warn
    failures: int = 0
    message: str = ""
    owner: dict = field(default_factory=dict)

    @property
    def failed(self):
        return self.status in ("fail", "error", "warn")


def run_dbt(project_dir: Path, args: list[str]):
    """Runs a dbt command in-process and returns whether it succeeded."""
    from dbt.cli.main import dbtRunner
    res = dbtRunner().invoke(["--log-level", "none"] + args + ["--project-dir", str(project_dir), "--profiles-dir", str(project_dir)])
    return res.success


def collect(project_dir: Path, evidence_dir: Path):
    """Runs freshness then build, copying each artifact before the next command overwrites it."""
    target = project_dir / "target"
    run_dbt(project_dir, ["source", "freshness"])
    shutil.copy(target / "sources.json", evidence_dir / "dbt_sources.json")
    run_dbt(project_dir, ["build"])
    for name in ("run_results.json", "manifest.json"):
        shutil.copy(target / name, evidence_dir / f"dbt_{name}")
    return (json.loads((evidence_dir / "dbt_sources.json").read_text()),
            json.loads((evidence_dir / "dbt_run_results.json").read_text()),
            json.loads((evidence_dir / "dbt_manifest.json").read_text()))


def freshness_results(sources, owners):
    out = []
    for r in sources["results"]:
        name = r["unique_id"].split(".", 2)[2]           # landing.units
        status = {"pass": "pass", "warn": "warn", "error": "fail", "runtime error": "error"}[r["status"]]
        hours = r.get("max_loaded_at_time_ago_in_s", 0) / 3600
        out.append(CheckResult(
            check_id=f"freshness.{name}", kind="freshness", dimension="freshness", object=f"source:{name}",
            status=status, severity="error" if status in ("fail", "error") else "warn",
            message=f"last load {hours:.1f} h ago" + ("" if status == "pass" else " (limit: warn 24 h, error 48 h)"),
            owner=owner_for(f"source:{name}", owners)))
    return out


def test_results(run_results, manifest, owners):
    out = []
    nodes = manifest["nodes"]
    for r in run_results["results"]:
        node = nodes.get(r["unique_id"])
        if not node or node["resource_type"] != "test":
            continue
        meta = node.get("test_metadata") or {}
        test_name = meta.get("name")
        if test_name:
            dimension = DIMENSIONS.get(test_name, "validity")
        elif "reconciliation" in node.get("tags", []):
            dimension = "reconciliation"
        else:
            dimension = "business rule"
        # The model a test is defined on; for singular tests it comes from config meta.
        attached = node.get("attached_node") or node["config"].get("meta", {}).get("object")
        parents = [p for p in node["depends_on"]["nodes"] if not p.startswith("test.")]
        obj = (attached or (parents[0] if parents else node["name"])).split(".")[-1]
        column = node.get("column_name")
        status = {"pass": "pass", "fail": "fail", "warn": "warn", "error": "error", "skipped": "skip"}[r["status"]]
        failures = r.get("failures") or 0
        label = f"{test_name or node['name']}" + (f" on {obj}.{column}" if column else "")
        owner_key = "reconciliation" if dimension == "reconciliation" else obj
        out.append(CheckResult(
            check_id=f"test.{node['name']}", kind="dbt_test", dimension=dimension, object=obj,
            status=status, severity=node["config"].get("severity", "error").lower(), failures=failures,
            message=label + (f": {failures} bad row(s)" if failures else ""),
            owner=owner_for(owner_key, owners)))
    return out


def owner_for(obj, owners):
    if obj in owners:
        return owners[obj]
    if obj.startswith("source:") and "source:landing" in owners:
        return owners["source:landing"]
    return owners.get("default", {})
