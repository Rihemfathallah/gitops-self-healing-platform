"""
Shared helpers for the experiment scripts. Standard library only, so the scripts
run on any machine that has python3, kubectl and git.

Every number published in the README comes from a file these scripts write in
results/ (non-functional requirement "traçabilité").
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
KUBECONFIG = os.environ.get("KUBECONFIG", str(ROOT / ".kube" / "config"))
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
API_URL = os.environ.get("NEURALRAG_URL", "http://localhost:8080")
NS = "neuralrag"
RELEASE_FILE = ROOT / "gitops" / "releases" / "neuralrag.yaml"


# ── time ──────────────────────────────────────────────────────────────
def now() -> float:
    return time.time()


def iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ── shell / kubectl ──────────────────────────────────────────────────
def sh(cmd: list[str], check: bool = True, capture: bool = True, cwd: Path = ROOT, timeout: int | None = None) -> str:
    env = {**os.environ, "KUBECONFIG": KUBECONFIG}
    res = subprocess.run(cmd, cwd=cwd, env=env, text=True, timeout=timeout,
                         stdout=subprocess.PIPE if capture else None,
                         stderr=subprocess.PIPE if capture else None)
    if check and res.returncode != 0:
        raise RuntimeError(f"command failed ({res.returncode}): {' '.join(cmd)}\n{res.stderr or ''}")
    return (res.stdout or "").strip()


def kubectl(*args: str, check: bool = True) -> str:
    return sh(["kubectl", *args], check=check)


def kjson(*args: str) -> dict:
    out = kubectl(*args, "-o", "json")
    return json.loads(out) if out else {}


def kubectl_apply(manifest: dict) -> None:
    env = {**os.environ, "KUBECONFIG": KUBECONFIG}
    subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest), text=True, check=True, env=env)


def api_key() -> str:
    import base64
    data = kjson("-n", NS, "get", "secret", "neuralrag-api")["data"]["API_KEY"]
    return base64.b64decode(data).decode()


# ── Prometheus ───────────────────────────────────────────────────────
def prom(path: str, **params) -> dict:
    url = f"{PROMETHEUS}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(f"prometheus error: {body}")
    return body["data"]


def prom_scalar(query: str, at: float | None = None) -> float | None:
    params = {"query": query}
    if at is not None:
        params["time"] = f"{at:.3f}"
    result = prom("/api/v1/query", **params)["result"]
    if not result:
        return None
    return float(result[0]["value"][1])


def firing_alerts(team: str = "neuralrag") -> list[dict]:
    alerts = prom("/api/v1/alerts")["alerts"]
    return [a for a in alerts if a["labels"].get("team") == team and a["state"] == "firing"]


# ── HTTP to the API ──────────────────────────────────────────────────
def http(method: str, path: str, body: dict | None = None, key: str | None = None, timeout: int = 90) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API_URL}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


# ── Git (GitOps: experiments change the desired state through commits) ──
def git(*args: str) -> str:
    return sh(["git", *args])


def set_release(release_id: str, error_rate: str = "0", latency_ms: str = "0", crash: str = "false") -> None:
    """Rewrite the release block of gitops/releases/neuralrag.yaml, keeping image.tag."""
    lines = RELEASE_FILE.read_text(encoding="utf-8").splitlines()
    out, skip = [], False
    for line in lines:
        if line.startswith("release:"):
            skip = True
            continue
        if skip and (line.startswith(" ") or not line.strip()):
            continue
        skip = False
        out.append(line)
    out += [
        "release:",
        f"  id: {release_id}",
        "  chaos:",
        f'    errorRate: "{error_rate}"',
        f'    latencyMs: "{latency_ms}"',
        f'    crashOnStart: "{crash}"',
    ]
    RELEASE_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def commit_and_push(message: str) -> str:
    git("pull", "--rebase", "--autostash", "origin", "main")
    git("add", str(RELEASE_FILE.relative_to(ROOT)))
    git("commit", "-m", message)
    git("push", "origin", "HEAD:main")
    return git("rev-parse", "HEAD")


def argocd_refresh(app: str = "neuralrag") -> None:
    """Ask Argo CD to re-read Git now instead of waiting for the next poll."""
    kubectl("-n", "argocd", "annotate", "application", app,
            "argocd.argoproj.io/refresh=normal", "--overwrite")


# ── results ──────────────────────────────────────────────────────────
def write_csv(path: Path, rows: list[dict], append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and append
    with open(path, "a" if append else "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not exists:
            w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"generated_at": iso(now()), "generated_by": "scripts/experiments", **data}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median_s": round(statistics.median(values), 1),
        "max_s": round(max(values), 1),
        "min_s": round(min(values), 1),
    }
