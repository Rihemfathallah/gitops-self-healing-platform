#!/usr/bin/env python3
"""Extract `spec` of a PrometheusRule manifest into a plain rules file for promtool.

usage: extract_rules.py gitops/observability/slo-rules.yaml build/slo-rules.rules.yaml
"""
import sys

import yaml

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    docs = [d for d in yaml.safe_load_all(f) if d and d.get("kind") == "PrometheusRule"]
groups = [g for d in docs for g in d["spec"]["groups"]]
with open(dst, "w", encoding="utf-8") as f:
    yaml.safe_dump({"groups": groups}, f, sort_keys=False, allow_unicode=True)
print(f"{len(groups)} groups -> {dst}")
