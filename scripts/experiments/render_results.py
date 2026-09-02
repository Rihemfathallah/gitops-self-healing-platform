#!/usr/bin/env python3
"""Rewrite the results table of README.md from results/*.json.
Every value comes from a file written by an experiment script; nothing is typed by hand."""

import json
import re

from lib import RESULTS, ROOT

README = ROOT / "README.md"
NA = "_pas encore mesuré_"


def load(rel: str):
    p = RESULTS / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fmt_s(st):
    return f"médiane {st['median_s']} s, max {st['max_s']} s" if st and st.get("n") else NA


def main() -> None:
    rb, slo, al, fp, dr = (load("rollback/summary.json"), load("slo/summary.json"), load("alerts/summary.json"),
                           load("alerts/false_positives.json"), load("dr/summary.json"))
    rows = [
        ("Temps de rollback (détection → version saine)",
         f"{rb['successful_rollbacks']}/{rb['runs']} rollbacks réussis ; {fmt_s(rb['detect_to_restored'])}"
         if rb else NA, "results/rollback/"),
        ("Temps total (commit fautif → version saine)", fmt_s(rb["push_to_restored"]) if rb else NA,
         "results/rollback/"),
        ("SLO tenus sous charge (k6, 30 min)",
         (f"disponibilité {slo['prometheus']['availability']:.3%} (cible 99,5 %) ; "
          f"{slo['prometheus']['fast_ratio_under_threshold']:.1%} des requêtes ≤ "
          f"{slo['prometheus']['latency_threshold_s']:g} s (cible 95 %)"
          + (" — tenus" if slo["passed"] else " — NON tenus"))
         if slo and slo["prometheus"]["availability"] is not None else NA, "results/slo/"),
        ("Incidents détectés par une alerte",
         f"{al['detected']}/{al['incidents']} ; délai {fmt_s(al['time_to_alert'])}" if al else NA,
         "results/alerts/"),
        ("Fausses alertes sur trafic normal",
         f"{fp['alert_episodes']} alerte(s) sur {fp['window_hours']:g} h ({fp['requests_served']} requêtes)"
         + ("" if fp["valid_measurement"] else " — mesure invalide") if fp else NA, "results/alerts/"),
        ("RTO (cluster détruit → service rétabli)", fmt_s(dr["rto"]) if dr and dr["successful"] else NA,
         "results/dr/"),
        ("RPO (données perdues)", fmt_s(dr["rpo"]) if dr and dr["successful"] else NA, "results/dr/"),
    ]
    table = "| Mesure | Résultat | Source |\n| --- | --- | --- |\n" + "\n".join(
        f"| {a} | {b} | [`{c}`]({c}) |" for a, b, c in rows)
    text = README.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- RESULTS:START -->\n).*?(\n<!-- RESULTS:END -->)", r"\1" + table.replace("\\", "\\\\") + r"\2",
                 text, flags=re.S)
    README.write_text(new, encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
