#!/usr/bin/env python3
"""
Measure "alertes pertinentes", part 1: every injected incident must trigger its alert.

For each incident in incidents/*.yaml (Chaos Mesh), the script:
  1. checks no NeuralRAG alert is already firing;
  2. applies the chaos object and timestamps it;
  3. polls Prometheus /api/v1/alerts until the expected alert fires (time to alert);
  4. deletes the chaos object and waits for every NeuralRAG alert to resolve.

Part 2 (0 alert over 24 h of normal traffic) is false_positive_check.py.

usage: alert_experiment.py [--incidents dependency-loss,latency,pod-failure] [--repeat 1]
"""

from __future__ import annotations

import argparse
import sys
import time

from lib import RESULTS, ROOT, firing_alerts, iso, kubectl, log, now, read_csv, stats, write_csv, write_json

EXPECTED = {
    "dependency-loss": "NeuralRAGAvailabilityBudgetFastBurn",
    "latency": "NeuralRAGLatencyBudgetFastBurn",
    "pod-failure": "NeuralRAGBackendDown",
}
CSV = RESULTS / "alerts" / "incidents.csv"
SUMMARY = RESULTS / "alerts" / "summary.json"


def wait_quiet(timeout: int) -> bool:
    deadline = now() + timeout
    while now() < deadline:
        if not firing_alerts():
            return True
        time.sleep(15)
    return False


def run_incident(name: str, run: int, alert_timeout: int, resolve_timeout: int) -> dict:
    if not wait_quiet(resolve_timeout):
        raise RuntimeError("NeuralRAG alerts already firing; refusing to start (results would be ambiguous)")
    manifest = ROOT / "incidents" / f"{name}.yaml"
    expected = EXPECTED[name]
    log(f"incident {name} #{run}: injecting, expecting {expected}")
    kubectl("apply", "-f", str(manifest))
    t_inject = now()

    t_alert, others = None, set()
    try:
        while now() - t_inject < alert_timeout:
            firing = firing_alerts()
            names = {a["labels"]["alertname"] for a in firing}
            others |= names - {expected}
            if expected in names:
                t_alert = now()
                break
            time.sleep(10)
    finally:
        kubectl("delete", "-f", str(manifest), "--ignore-not-found", "--wait=true")
        t_removed = now()

    log(f"  alert {'fired after %.0f s' % (t_alert - t_inject) if t_alert else 'NOT fired'}; waiting for recovery")
    resolved = wait_quiet(resolve_timeout)
    return {
        "incident": name, "run": run, "expected_alert": expected, "detected": t_alert is not None,
        "t_inject": iso(t_inject), "t_alert": iso(t_alert), "t_chaos_removed": iso(t_removed),
        "time_to_alert_s": round(t_alert - t_inject, 1) if t_alert else "",
        "other_alerts": ";".join(sorted(others)),
        "resolved_after_removal": resolved,
    }


def summarize() -> dict:
    rows = read_csv(CSV)
    detected = [r for r in rows if r["detected"] == "True"]
    summary = {
        "incidents": len(rows),
        "detected": len(detected),
        "all_detected": len(rows) > 0 and len(detected) == len(rows),
        "time_to_alert": stats([float(r["time_to_alert_s"]) for r in detected]),
        "by_incident": {
            name: {
                "runs": sum(1 for r in rows if r["incident"] == name),
                "detected": sum(1 for r in detected if r["incident"] == name),
                "time_to_alert": stats([float(r["time_to_alert_s"]) for r in detected if r["incident"] == name]),
            } for name in EXPECTED if any(r["incident"] == name for r in rows)
        },
    }
    write_json(SUMMARY, summary)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--incidents", default=",".join(EXPECTED))
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--alert-timeout", type=int, default=20 * 60)
    p.add_argument("--resolve-timeout", type=int, default=30 * 60)
    p.add_argument("--summary-only", action="store_true")
    a = p.parse_args()
    if not a.summary_only:
        names = [n.strip() for n in a.incidents.split(",") if n.strip()]
        start = len(read_csv(CSV))
        run = start
        for _ in range(a.repeat):
            for name in names:
                run += 1
                write_csv(CSV, [run_incident(name, run, a.alert_timeout, a.resolve_timeout)])
    s = summarize()
    log(f"summary: {s}")
    return 0 if s["all_detected"] else 1


if __name__ == "__main__":
    sys.exit(main())
