#!/usr/bin/env python3
"""
Measure "alertes pertinentes", part 2: 0 NeuralRAG alert over 24 h of normal traffic.

Run it AFTER leaving the platform alone for the window (traffic generator on,
no experiment, no chaos). It reads history from Prometheus, so the machine only
has to stay on; the script itself takes a few seconds.

It checks, over [now - hours, now]:
  - traffic really flowed (number of requests served);
  - no experiment ran in the window (no "test(incident)" commit, no chaos object);
  - how many times a NeuralRAG alert (label team="neuralrag") was firing.

usage: false_positive_check.py [--hours 24]
"""

from __future__ import annotations

import argparse
import sys

from lib import RESULTS, git, iso, kubectl, log, now, prom, prom_scalar, write_json


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hours", type=float, default=24)
    a = p.parse_args()
    end = now()
    start = end - a.hours * 3600
    window = f"{int(a.hours * 3600)}s"

    requests = prom_scalar(f'sum(increase(http_requests_total{{job="neuralrag-backend"}}[{window}]))', at=end) or 0
    errors = prom_scalar(
        f'sum(increase(http_requests_total{{job="neuralrag-backend", code=~"5.."}}[{window}]))', at=end) or 0

    series = prom("/api/v1/query_range", query='ALERTS{team="neuralrag", alertstate="firing"}',
                  start=f"{start:.0f}", end=f"{end:.0f}", step="60")["result"]
    episodes = []
    for s in series:
        prev = None
        for ts, _ in s["values"]:
            ts = float(ts)
            if prev is None or ts - prev > 120:
                episodes.append({"alert": s["metric"]["alertname"], "started": iso(ts)})
            prev = ts

    experiment_commits = git("log", f"--since={iso(start)}", "--grep=test(incident)", "--oneline")
    chaos_left = kubectl("get", "networkchaos,podchaos", "-A", "--no-headers", check=False)

    clean_window = not experiment_commits and not chaos_left.strip()
    result = {
        "window_hours": a.hours,
        "window_start": iso(start), "window_end": iso(end),
        "requests_served": int(requests),
        "requests_5xx": int(errors),
        "alert_episodes": len(episodes),
        "episodes": episodes,
        "experiments_in_window": bool(experiment_commits) or bool(chaos_left.strip()),
        "valid_measurement": clean_window and requests > 0,
        "passed": clean_window and requests > 0 and len(episodes) == 0,
    }
    write_json(RESULTS / "alerts" / "false_positives.json", result)
    log(f"result: {result}")
    if not clean_window:
        log("WARNING: an experiment ran during the window; the measurement is not valid")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
