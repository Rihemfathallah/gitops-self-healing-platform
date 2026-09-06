#!/usr/bin/env python3
"""
Measure "SLO tenus": a 30-minute k6 load test on the healthy release; availability
and latency SLIs are then read from Prometheus over exactly the test window.

k6 runs in Docker (no install needed): grafana/k6, host network.

usage: slo_loadtest.py [--duration 30m] [--vus 2]
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from lib import API_URL, RESULTS, ROOT, api_key, iso, log, now, prom_scalar, sh, write_json

K6_IMAGE = "grafana/k6:1.0.0"
TARGET_AVAILABILITY = 0.995
TARGET_FAST_RATIO = 0.95          # share of requests <= 10 s  (p95 <= 10 s)
THRESHOLD_LE = "10.0"


def seconds(duration: str) -> int:
    m = re.fullmatch(r"(\d+)([smh])", duration)
    if not m:
        raise ValueError("duration like 30m, 1800s, 1h")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--duration", default="30m")
    p.add_argument("--vus", type=int, default=2)
    a = p.parse_args()

    out_dir = RESULTS / "slo"
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = now()
    log(f"k6: {a.vus} VUs for {a.duration} against {API_URL}")
    sh(["docker", "run", "--rm", "--network", "host",
        "-e", f"NEURALRAG_URL={API_URL}", "-e", f"API_KEY={api_key()}",
        "-e", f"VUS={a.vus}", "-e", f"DURATION={a.duration}", "-e", "SUMMARY_FILE=/out/k6-summary.json",
        "-v", f"{ROOT / 'loadtest'}:/scripts:ro", "-v", f"{out_dir}:/out",
        "--user", "0", K6_IMAGE, "run", "/scripts/k6-slo.js"], check=False, capture=False)
    t_end = now()

    # Let Prometheus scrape the last samples before reading the window.
    import time
    time.sleep(45)
    win = f"{int(t_end - t_start)}s"
    sel = 'job="neuralrag-backend"'
    total = prom_scalar(f"sum(increase(http_requests_total{{{sel}}}[{win}]))", at=t_end + 30) or 0
    errors = prom_scalar(f'sum(increase(http_requests_total{{{sel}, code=~"5.."}}[{win}]))', at=t_end + 30) or 0
    fast = prom_scalar(
        f'sum(increase(http_request_duration_seconds_bucket{{{sel}, le="{THRESHOLD_LE}"}}[{win}]))', at=t_end + 30) or 0
    count = prom_scalar(f"sum(increase(http_request_duration_seconds_count{{{sel}}}[{win}]))", at=t_end + 30) or 0
    p95 = prom_scalar(
        f"histogram_quantile(0.95, sum by (le) (increase(http_request_duration_seconds_bucket{{{sel}}}[{win}])))",
        at=t_end + 30)

    availability = 1 - errors / total if total else None
    fast_ratio = fast / count if count else None
    k6 = {}
    k6_file = out_dir / "k6-summary.json"
    if k6_file.exists():
        m = json.loads(k6_file.read_text())["metrics"]
        k6 = {
            "requests": m["http_reqs"]["values"]["count"],
            "failed_rate": m["http_req_failed"]["values"]["rate"],
            "p95_ms": round(m["http_req_duration"]["values"]["p(95)"], 1),
        }

    result = {
        "window_start": iso(t_start), "window_end": iso(t_end), "duration": a.duration, "vus": a.vus,
        "release": sh(["git", "log", "-1", "--format=%h %s", "--", "gitops/releases/neuralrag.yaml"]),
        "prometheus": {
            "requests": int(total),
            "availability": round(availability, 5) if availability is not None else None,
            "availability_target": TARGET_AVAILABILITY,
            "fast_ratio_le_10s": round(fast_ratio, 5) if fast_ratio is not None else None,
            "fast_ratio_target": TARGET_FAST_RATIO,
            "p95_s_estimated": round(p95, 2) if p95 is not None else None,
        },
        "k6_client_view": k6,
    }
    result["availability_met"] = availability is not None and availability >= TARGET_AVAILABILITY
    result["latency_met"] = fast_ratio is not None and fast_ratio >= TARGET_FAST_RATIO
    result["passed"] = result["availability_met"] and result["latency_met"]
    write_json(out_dir / "summary.json", result)
    log(f"result: {json.dumps(result, indent=2)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
