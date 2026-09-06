# results/

Every number in the main README comes from a file in this folder, written by a
script in `scripts/experiments/`. Nothing here is typed by hand.

| Folder | Written by | Make target |
| --- | --- | --- |
| `rollback/` | `rollback_experiment.py` (`runs.csv`, `summary.json`) | `make exp-rollback` |
| `slo/` | `slo_loadtest.py` (`summary.json`) | `make exp-slo` |
| `alerts/` | `alert_experiment.py`, `false_positive_check.py` | `make exp-alerts`, `make exp-false-positives` |
| `dr/` | `dr_drill.py` (`drills.csv`, `summary.json`) | `make exp-dr` |

`make results` rewrites the table of the main README from the `summary.json` files.
