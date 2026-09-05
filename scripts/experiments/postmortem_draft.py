#!/usr/bin/env python3
"""
EF-11 — create one postmortem draft per simulated incident, from the measured data.
The timeline and the impact come from results/; the analysis sections are left
for a human to write (a postmortem is a learning document, not a log dump).

usage: postmortem_draft.py            # drafts every incident not drafted yet
"""


from lib import RESULTS, ROOT, read_csv

OUT = ROOT / "docs" / "postmortems"
TEMPLATE = (OUT / "TEMPLATE.md").read_text(encoding="utf-8")

CAUSES = {
    "errors": "Release configurée pour faire échouer 50 % des requêtes API (CHAOS_ERROR_RATE=0.5).",
    "latency": "Release configurée pour ajouter 40 s à chaque requête API (CHAOS_LATENCY_MS=40000).",
    "crash": "Release configurée pour planter au démarrage (CHAOS_CRASH_ON_START=true).",
    "dependency-loss": "Partition réseau entre le backend et ChromaDB (Chaos Mesh NetworkChaos).",
    "latency-net": "Délai réseau de 25 s sur les réponses d'Ollama au backend (Chaos Mesh NetworkChaos).",
    "pod-failure": "Toutes les pods backend rendues indisponibles pendant 10 minutes (Chaos Mesh PodChaos).",
}


def write(name: str, fields: dict) -> bool:
    path = OUT / f"{name}.md"
    if path.exists():
        return False
    text = TEMPLATE
    for k, v in fields.items():
        text = text.replace("{{" + k + "}}", str(v))
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    created = 0
    for r in read_csv(RESULTS / "rollback" / "runs.csv"):
        timeline = "\n".join([
            f"| {r['t_push']} | Release fautive poussée dans Git (commit {r['commit']}) |",
            f"| {r['t_canary']} | Argo CD a synchronisé ; Argo Rollouts lance le canary |",
            f"| {r['t_detect']} | Analyse du canary en échec, rollout annulé (détection) |",
            f"| {r['t_restored']} | 100 % du trafic revenu sur la dernière version saine |",
        ])
        created += write(f"release-{int(r['run']):03d}-{r['kind']}", {
            "TITLE": f"Release fautive '{r['kind']}' annulée automatiquement (essai {r['run']})",
            "DATE": r["t_push"][:10], "TRIGGER": CAUSES[r["kind"]],
            "DETECTION": "AnalysisRun Argo Rollouts (Prometheus, pods du canary uniquement)",
            "TTD": r["push_to_detect_s"], "TTR": r["detect_to_restored_s"], "TIMELINE": timeline,
            "IMPACT": "Seule la pod canary (environ 50 % des requêtes) a servi la version fautive, "
                      f"pendant {r['push_to_detect_s']} s au plus.",
        })
    for r in read_csv(RESULTS / "alerts" / "incidents.csv"):
        kind = "latency-net" if r["incident"] == "latency" else r["incident"]
        timeline = "\n".join([
            f"| {r['t_inject']} | Incident injecté |",
            f"| {r['t_alert']} | Alerte {r['expected_alert']} déclenchée |",
            f"| {r['t_chaos_removed']} | Cause retirée (objet Chaos Mesh supprimé) |",
        ])
        created += write(f"incident-{int(r['run']):03d}-{r['incident']}", {
            "TITLE": f"Incident '{r['incident']}' (essai {r['run']})",
            "DATE": r["t_inject"][:10], "TRIGGER": CAUSES[kind],
            "DETECTION": f"Alerte Prometheus {r['expected_alert']}",
            "TTD": r["time_to_alert_s"] or "non détecté", "TTR": "voir la chronologie", "TIMELINE": timeline,
            "IMPACT": "À compléter depuis le tableau de bord SLO (requêtes en échec ou lentes, budget consommé).",
        })
    print(f"{created} brouillon(s) de postmortem créé(s) dans {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
