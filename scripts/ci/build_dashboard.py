#!/usr/bin/env python3
"""Generate the Grafana SLO dashboard (EF-08) as a ConfigMap picked up by the
Grafana sidecar. The JSON is generated rather than hand-edited so the panels
stay consistent with the recording rules.

usage: build_dashboard.py > gitops/observability/dashboard-slo.yaml
"""
import json

DS = {"type": "prometheus", "uid": "prometheus"}


def stat(pid, title, expr, x, y, w=6, h=5, unit="percentunit", thresholds=None, decimals=2):
    return {
        "id": pid, "type": "stat", "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "expr": expr, "datasource": DS}],
        "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"]}},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]},
        }, "overrides": []},
    }


def series(pid, title, targets, x, y, w=12, h=8, unit="percentunit", thresholds=None):
    return {
        "id": pid, "type": "timeseries", "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": {
            "unit": unit,
            "custom": {"thresholdsStyle": {"mode": "line" if thresholds else "off"}},
            "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]},
        }, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }


BURN = [{"color": "green", "value": None}, {"color": "orange", "value": 1.4}, {"color": "red", "value": 3.36}]
RED_GREEN_BUDGET = [{"color": "red", "value": None}, {"color": "orange", "value": 0}, {"color": "green", "value": 0.25}]

panels = [
    {"id": 1, "type": "row", "title": "SLO — 7 days", "collapsed": False, "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1}},
    stat(2, "Availability (7d) — target 99.5 %", "1 - neuralrag:sli_errors:ratio_rate7d", 0, 1,
         thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 0.995}], decimals=3),
    stat(3, "Availability error budget left", "neuralrag:slo_availability:error_budget_remaining", 6, 1,
         thresholds=RED_GREEN_BUDGET, decimals=1),
    stat(4, "Requests ≤ 30 s (7d) — target 95 %", "1 - neuralrag:sli_slow:ratio_rate7d", 12, 1,
         thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 0.95}], decimals=2),
    stat(5, "Latency error budget left", "neuralrag:slo_latency:error_budget_remaining", 18, 1,
         thresholds=RED_GREEN_BUDGET, decimals=1),

    {"id": 10, "type": "row", "title": "Burn rate (1 = budget lasts exactly 7 days)", "collapsed": False,
     "gridPos": {"x": 0, "y": 6, "w": 24, "h": 1}},
    series(11, "Availability burn rate", [
        ("neuralrag:sli_errors:ratio_rate5m / 0.005", "5m"),
        ("neuralrag:sli_errors:ratio_rate1h / 0.005", "1h"),
        ("neuralrag:sli_errors:ratio_rate6h / 0.005", "6h"),
    ], 0, 7, unit="none", thresholds=BURN),
    series(12, "Latency burn rate", [
        ("neuralrag:sli_slow:ratio_rate5m / 0.05", "5m"),
        ("neuralrag:sli_slow:ratio_rate1h / 0.05", "1h"),
        ("neuralrag:sli_slow:ratio_rate6h / 0.05", "6h"),
    ], 12, 7, unit="none", thresholds=BURN),

    {"id": 20, "type": "row", "title": "Traffic and releases", "collapsed": False,
     "gridPos": {"x": 0, "y": 15, "w": 24, "h": 1}},
    series(21, "Requests per second by status code", [
        ('sum by (code) (rate(http_requests_total{job="neuralrag-backend"}[1m]))', "{{code}}"),
    ], 0, 16, unit="reqps"),
    series(22, "Latency p95 (SLO threshold 30 s)", [
        ("neuralrag:latency_seconds:p95_rate5m", "p95"),
    ], 12, 16, unit="s", thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 30}]),
    series(23, "Error ratio per pod (canary vs stable)", [
        ('(sum by (pod) (rate(http_requests_total{job="neuralrag-backend", code=~"5.."}[1m])) or '
         'sum by (pod) (rate(http_requests_total{job="neuralrag-backend"}[1m])) * 0) / '
         'sum by (pod) (rate(http_requests_total{job="neuralrag-backend"}[1m]))', "{{pod}}"),
    ], 0, 24),
    series(24, "Running version and rollout phase", [
        ('count by (version) (neuralrag_build_info{job="neuralrag-backend"})', "pods on {{version}}"),
        ('max by (phase) (rollout_info{namespace="neuralrag", name="neuralrag-backend"}) > 0', "phase {{phase}}"),
    ], 12, 24, unit="none"),

    {"id": 30, "type": "row", "title": "Alerts", "collapsed": False, "gridPos": {"x": 0, "y": 32, "w": 24, "h": 1}},
    {
        "id": 31, "type": "alertlist", "title": "Firing NeuralRAG alerts",
        "gridPos": {"x": 0, "y": 33, "w": 24, "h": 8},
        "options": {"alertInstanceLabelFilter": '{team="neuralrag"}', "stateFilter": {"firing": True, "pending": True},
                    "maxItems": 20, "sortOrder": 1, "groupMode": "default", "showInstances": True,
                    "viewMode": "list", "datasource": "Prometheus"},
    },
]

dashboard = {
    "uid": "neuralrag-slo",
    "title": "NeuralRAG — SLO, error budget and releases",
    "tags": ["neuralrag", "slo", "sre"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-6h", "to": "now"},
    "panels": panels,
    "templating": {"list": []},
    "annotations": {"list": []},
}

body = json.dumps(dashboard, indent=2, ensure_ascii=False)
print("# Generated by scripts/ci/build_dashboard.py — do not edit by hand.")
print("apiVersion: v1")
print("kind: ConfigMap")
print("metadata:")
print("  name: neuralrag-slo-dashboard")
print("  namespace: monitoring")
print("  labels:")
print('    grafana_dashboard: "1"')
print("data:")
print("  neuralrag-slo.json: |")
for line in body.splitlines():
    print("    " + line)
