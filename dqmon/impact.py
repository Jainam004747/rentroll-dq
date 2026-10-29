"""Uses the dbt manifest to find which reports a failing table or source can affect."""


def downstream_exposures(manifest, obj):
    """Returns the labels of the exposures (Power BI reports) downstream of a model or source."""
    if obj.startswith("source:"):
        start = "source.rentroll." + obj.split(":", 1)[1]
    else:
        start = next((uid for uid in manifest["nodes"] if uid.endswith("." + obj) and uid.startswith("model.")), None)
    if not start:
        return []
    child_map = manifest["child_map"]
    seen, stack, reports = set(), [start], set()
    while stack:
        uid = stack.pop()
        for child in child_map.get(uid, []):
            if child in seen:
                continue
            seen.add(child)
            if child.startswith("exposure."):
                exp = manifest["exposures"][child]
                reports.add(exp.get("label") or exp["name"])
            elif child.startswith("model."):
                stack.append(child)
    return sorted(reports)


def skipped_models(run_results):
    """Models dbt didn't build because an upstream test failed: they keep yesterday's data."""
    return sorted(r["unique_id"].split(".")[-1] for r in run_results["results"]
                  if r["unique_id"].startswith("model.") and r["status"] == "skipped")
