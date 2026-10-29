"""Control evidence: what ran, when, who ran it, what it found, and proof it wasn't edited later.

Each run gets a folder evidence/<run_id>/ with the raw dbt artifacts, the normalised
results, the incidents, and a short summary. MANIFEST.sha256 lists a SHA-256 hash for every
file plus the hash of the previous run's manifest, so the runs form a chain: changing or
deleting an old file breaks verification for that run and every run after it.
"""
import hashlib
import json
from pathlib import Path


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(run_dir: Path, previous_manifest_hash: str | None):
    lines = [f"{sha256(p)}  {p.name}" for p in sorted(run_dir.iterdir()) if p.name != "MANIFEST.sha256"]
    lines.append(f"previous_run  {previous_manifest_hash or 'none'}")
    manifest = run_dir / "MANIFEST.sha256"
    manifest.write_text("\n".join(lines) + "\n")
    return sha256(manifest)


def verify(evidence_root: Path):
    """Re-hashes every run in order. Returns a list of (run_id, ok, problem)."""
    out, previous = [], None
    for run_dir in sorted(p for p in evidence_root.iterdir() if p.is_dir()):
        manifest = run_dir / "MANIFEST.sha256"
        if not manifest.exists():
            out.append((run_dir.name, False, "MANIFEST.sha256 missing"))
            previous = None
            continue
        problem = None
        listed = set()
        for line in manifest.read_text().splitlines():
            if "  " not in line:
                continue
            digest, name = line.split("  ", 1)
            if digest == "previous_run":
                if name != (previous or "none"):
                    problem = "chain broken: previous run's manifest was changed"
                continue
            listed.add(name)
            f = run_dir / name
            if not f.exists():
                problem = f"{name} is missing"
            elif sha256(f) != digest:
                problem = f"{name} was modified after the run"
        extra = {p.name for p in run_dir.iterdir()} - listed - {"MANIFEST.sha256"}
        if extra and not problem:
            problem = f"unexpected file(s) added: {', '.join(sorted(extra))}"
        out.append((run_dir.name, problem is None, problem or "ok"))
        previous = sha256(manifest)
    return out


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))
