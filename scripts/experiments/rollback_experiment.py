#!/usr/bin/env python3
"""
Measure "temps de rollback" (acceptance criterion: N >= 10, rollback succeeds on all,
median and max published).

Each run:
  1. commits a faulty release to gitops/releases/neuralrag.yaml and pushes it
     (exactly what a developer shipping a bad version would do);
  2. Argo CD syncs it, Argo Rollouts starts a canary, the AnalysisRun queries
     Prometheus and fails, the rollout is aborted, traffic goes back to stable;
  3. the script timestamps each phase from the cluster state;
  4. the faulty commit is reverted in Git (the human part of the response, scripted
     here so the experiment can loop) and the script waits for a healthy state.

Timestamps:
  t_push      faulty commit pushed
  t_canary    first canary pod of the faulty revision exists
  t_detect    rollout aborted (AnalysisRun failed or progress deadline exceeded) = the alert
  t_restored  canary scaled to 0 and every stable pod ready = back on the healthy version

usage: rollback_experiment.py --runs 10 [--kinds errors,latency,crash]
"""

from __future__ import annotations

import argparse
import sys

from lib import (NS, RESULTS, argocd_refresh, commit_and_push, git, iso, kjson, log, now, set_release,
                 read_csv, stats, write_csv, write_json)
import time

FAULTS = {
    "errors": dict(error_rate="0.5"),        # half of the requests fail
    "latency": dict(latency_ms="15000"),     # every request takes > 15 s
    "crash": dict(crash="true"),             # pods crash-loop, never ready
}
CSV = RESULTS / "rollback" / "runs.csv"
SUMMARY = RESULTS / "rollback" / "summary.json"


def rollout() -> dict:
    return kjson("-n", NS, "get", "rollout", "neuralrag-backend")


def rs_for_hash(pod_hash: str) -> dict | None:
    items = kjson("-n", NS, "get", "rs", "-l", f"rollouts-pod-template-hash={pod_hash}").get("items", [])
    return items[0] if items else None


def wait_healthy(timeout: int = 900) -> str:
    """Wait for a Healthy, fully promoted rollout. Returns the stable pod hash."""
    deadline = now() + timeout
    while now() < deadline:
        ro = rollout()
        st = ro.get("status", {})
        if (st.get("phase") == "Healthy" and not st.get("abort")
                and st.get("stableRS") == st.get("currentPodHash")
                and st.get("readyReplicas", 0) >= ro["spec"]["replicas"]):
            return st["stableRS"]
        time.sleep(5)
    raise TimeoutError("rollout did not become Healthy")


def run_once(run: int, kind: str, timeout: int) -> dict:
    stable = wait_healthy()
    log(f"run {run} [{kind}] stable revision {stable}")

    set_release(f"bad-{kind}-{run}", **FAULTS[kind])
    sha = commit_and_push(f"test(incident): bad release '{kind}' run {run}")
    t_push = now()
    argocd_refresh()

    t_canary = t_detect = t_restored = None
    canary_hash = None
    deadline = t_push + timeout
    while now() < deadline:
        st = rollout().get("status", {})
        current = st.get("currentPodHash")
        if current and current != stable and canary_hash is None:
            canary_hash = current
        if canary_hash and t_canary is None:
            rs = rs_for_hash(canary_hash)
            if rs and rs.get("status", {}).get("replicas", 0) > 0:
                t_canary = now()
        if st.get("abort") and t_detect is None:
            t_detect = now()
            log(f"  aborted: {st.get('message', '')}")
        if t_detect and st.get("stableRS") == stable:
            canary_rs = rs_for_hash(canary_hash) if canary_hash else None
            canary_left = canary_rs.get("status", {}).get("replicas", 0) if canary_rs else 0
            stable_rs = rs_for_hash(stable) or {}
            ready = stable_rs.get("status", {}).get("readyReplicas", 0)
            if canary_left == 0 and ready >= rollout()["spec"]["replicas"]:
                t_restored = now()
                break
        time.sleep(2)

    success = t_restored is not None
    row = {
        "run": run, "kind": kind, "commit": sha[:7], "success": success,
        "t_push": iso(t_push), "t_canary": iso(t_canary), "t_detect": iso(t_detect), "t_restored": iso(t_restored),
        "push_to_detect_s": round(t_detect - t_push, 1) if t_detect else "",
        "canary_to_detect_s": round(t_detect - t_canary, 1) if t_detect and t_canary else "",
        "detect_to_restored_s": round(t_restored - t_detect, 1) if success else "",
        "push_to_restored_s": round(t_restored - t_push, 1) if success else "",
    }
    log(f"  result: {row}")

    # Human part of the response (scripted): revert the faulty commit in Git.
    git("pull", "--rebase", "--autostash", "origin", "main")
    git("revert", "--no-edit", sha)
    git("push", "origin", "HEAD:main")
    argocd_refresh()
    wait_healthy()
    return row


def summarize() -> dict:
    rows = read_csv(CSV)
    ok = [r for r in rows if r["success"] == "True"]
    summary = {
        "runs": len(rows),
        "successful_rollbacks": len(ok),
        "all_successful": len(rows) > 0 and len(ok) == len(rows),
        "detect_to_restored": stats([float(r["detect_to_restored_s"]) for r in ok]),
        "push_to_restored": stats([float(r["push_to_restored_s"]) for r in ok]),
        "by_kind": {},
    }
    for kind in FAULTS:
        k_ok = [r for r in ok if r["kind"] == kind]
        k_all = [r for r in rows if r["kind"] == kind]
        if k_all:
            summary["by_kind"][kind] = {
                "runs": len(k_all), "successful": len(k_ok),
                "push_to_detect": stats([float(r["push_to_detect_s"]) for r in k_ok]),
                "detect_to_restored": stats([float(r["detect_to_restored_s"]) for r in k_ok]),
            }
    write_json(SUMMARY, summary)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--kinds", default="errors,latency,crash")
    p.add_argument("--timeout", type=int, default=900, help="seconds per run before declaring failure")
    p.add_argument("--summary-only", action="store_true")
    a = p.parse_args()

    if not a.summary_only:
        kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
        unknown = set(kinds) - FAULTS.keys()
        if unknown:
            p.error(f"unknown kinds: {unknown}")
        start = len(read_csv(CSV))
        for i in range(a.runs):
            row = run_once(start + i + 1, kinds[i % len(kinds)], a.timeout)
            write_csv(CSV, [row])
    s = summarize()
    log(f"summary: {s}")
    return 0 if s["all_successful"] else 1


if __name__ == "__main__":
    sys.exit(main())
