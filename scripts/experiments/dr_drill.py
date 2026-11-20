#!/usr/bin/env python3
"""
Disaster-recovery drill (EF-13): destroy the cluster with Terraform, rebuild it,
restore ChromaDB with Velero, let Argo CD resync from Git, and measure RTO and RPO.

  RPO  = t_disaster - timestamp of the newest data that survived
         (markers are written to ChromaDB every few seconds until the disaster)
  RTO  = t_service_back - t_disaster, where "service back" means
         POST /api/query answers 200 AND the indexed documents are present again.

Steps
  1. pre-checks: platform healthy, documents indexed (run `make seed` first)
  2. write a marker into ChromaDB every --marker-interval seconds
  3. wait for the next *scheduled* Velero backup to complete, keep writing markers
     for --after-backup seconds (data that the backup does not contain), then:
  4. DISASTER: terraform destroy -target=kind_cluster.this
  5. terraform apply (cluster), platform in restore mode (Argo CD + Velero, no apps)
  6. Velero Restore of the ChromaDB StatefulSet, its pod and its volume
  7. platform in normal mode: the root app is created, Argo CD resyncs everything from Git
  8. wait for the API, compare document count, read the newest surviving marker

usage: dr_drill.py [--after-backup 300] [--marker-interval 10]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import chroma
from lib import (NS, RESULTS, ROOT, api_key, http, iso, kjson, kubectl_apply, log, now, read_csv, sh, stats,
                 write_csv, write_json)

TF_CLUSTER = ROOT / "infra" / "terraform" / "cluster"
TF_PLATFORM = ROOT / "infra" / "terraform" / "platform"
SCHEDULE = "velero-neuralrag"
CSV = RESULTS / "dr" / "drills.csv"
SUMMARY = RESULTS / "dr" / "summary.json"


def tf(root, *args: str) -> None:
    sh(["terraform", f"-chdir={root}", *args, "-input=false"], capture=False)


def scheduled_backups() -> list[dict]:
    items = kjson("-n", "velero", "get", "backups.velero.io",
                  "-l", f"velero.io/schedule-name={SCHEDULE}").get("items", [])
    return sorted(items, key=lambda b: b["metadata"]["creationTimestamp"])


def wait_new_backup(after: float, timeout: int) -> dict:
    from datetime import datetime
    deadline = now() + timeout
    while now() < deadline:
        for b in reversed(scheduled_backups()):
            st = b.get("status", {})
            done = st.get("completionTimestamp")
            if st.get("phase") == "Completed" and done:
                t_done = datetime.fromisoformat(done.replace("Z", "+00:00")).timestamp()
                if t_done > after:
                    return b
        time.sleep(15)
    raise TimeoutError("no scheduled backup completed in time; check `kubectl -n velero get backups`")


def forget_platform_state() -> None:
    """The cluster is gone, so the platform state describes objects that no longer exist.
    Keep only the generated secrets (random_password) so the API key stays the same."""
    for addr in sh(["terraform", f"-chdir={TF_PLATFORM}", "state", "list"]).splitlines():
        if addr.startswith("random_password.") or addr.startswith("data."):
            continue
        sh(["terraform", f"-chdir={TF_PLATFORM}", "state", "rm", addr])


def wait_for(predicate, timeout: int, every: int = 10, what: str = "") -> float:
    deadline = now() + timeout
    while now() < deadline:
        try:
            if predicate():
                return now()
        except Exception:
            pass
        time.sleep(every)
    raise TimeoutError(f"timeout waiting for {what}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--after-backup", type=int, default=300,
                   help="seconds of new data written after the last backup, before the disaster")
    p.add_argument("--marker-interval", type=int, default=10)
    p.add_argument("--backup-timeout", type=int, default=3600)
    p.add_argument("--recovery-timeout", type=int, default=3600)
    p.add_argument("--summary-only", action="store_true")
    a = p.parse_args()
    if a.summary_only:
        return summarize()

    # 1 ── pre-checks
    docs_before = chroma.count()
    if docs_before == 0:
        log("no indexed document: run `make seed` first")
        return 2
    key = api_key()
    if http("POST", "/api/query", {"question": "Qu'est-ce que le RPO ?"}, key) != 200:
        log("the API does not answer 200 before the drill; fix the platform first")
        return 2
    log(f"pre-check ok: {docs_before} chunks in ChromaDB")

    # 2 ── markers
    stop = threading.Event()
    written: list[float] = []

    def writer():
        while not stop.is_set():
            ts = now()
            try:
                chroma.write_marker(ts)
                written.append(ts)
            except Exception as e:  # the pod disappears at the disaster
                log(f"marker write failed: {e}")
            stop.wait(a.marker_interval)

    threading.Thread(target=writer, daemon=True).start()

    # 3 ── wait for a fresh scheduled backup, then let new data accumulate
    t_wait = now()
    backup = wait_new_backup(t_wait, a.backup_timeout)
    log(f"scheduled backup {backup['metadata']['name']} completed; writing {a.after_backup}s of new data")
    time.sleep(a.after_backup)
    stop.set()
    last_written = max(written) if written else None

    # 4 ── DISASTER
    t_disaster = now()
    log("DISASTER: destroying the cluster with Terraform")
    tf(TF_CLUSTER, "destroy", "-target=kind_cluster.this", "-auto-approve")
    t_destroyed = now()

    # 5 ── rebuild: cluster, then Argo CD + Velero without applications
    forget_platform_state()
    tf(TF_CLUSTER, "apply", "-auto-approve")
    tf(TF_PLATFORM, "apply", "-auto-approve", "-var", "restore_mode=true")
    t_platform = now()

    # 6 ── restore ChromaDB from the newest completed backup
    def latest_backup():
        done = [b for b in scheduled_backups() if b.get("status", {}).get("phase") == "Completed"]
        return done[-1] if done else None

    wait_for(lambda: latest_backup() is not None, 600, what="backups synced from the S3 store")
    restored_from = latest_backup()["metadata"]["name"]
    restore_name = f"dr-{int(t_disaster)}"
    manifest = {
        "apiVersion": "velero.io/v1", "kind": "Restore",
        "metadata": {"name": restore_name, "namespace": "velero"},
        "spec": {
            "backupName": restored_from,
            "includedNamespaces": [NS],
            "includedResources": ["persistentvolumeclaims", "persistentvolumes", "pods", "statefulsets"],
            "labelSelector": {"matchLabels": {"neuralrag/dr": "restore"}},
            "restorePVs": True,
        },
    }
    kubectl_apply(manifest)
    log(f"restore {restore_name} from {restored_from}")

    def restore_done():
        phase = kjson("-n", "velero", "get", "restores.velero.io", restore_name).get("status", {}).get("phase")
        if phase in ("Failed", "FailedValidation"):
            raise SystemExit(f"restore {phase}")
        return phase in ("Completed", "PartiallyFailed")

    t_restored = wait_for(restore_done, 1800, what="velero restore")
    restore_phase = kjson("-n", "velero", "get", "restores.velero.io", restore_name)["status"]["phase"]

    # 7 ── back to normal: root app, Argo CD resyncs everything from Git
    tf(TF_PLATFORM, "apply", "-auto-approve", "-var", "restore_mode=false")

    # 8 ── service back?
    key = api_key()
    t_api = wait_for(lambda: http("POST", "/api/query", {"question": "Qu'est-ce que le RTO ?"}, key) == 200,
                     a.recovery_timeout, every=15, what="API answering 200")
    docs_after = chroma.count()
    last_restored = chroma.last_marker()
    t_back = now()

    row = {
        "drill": len(read_csv(CSV)) + 1,
        "backup_used": restored_from,
        "restore_phase": restore_phase,
        "t_disaster": iso(t_disaster), "t_service_back": iso(t_back),
        "destroy_s": round(t_destroyed - t_disaster, 1),
        "rebuild_platform_s": round(t_platform - t_destroyed, 1),
        "velero_restore_s": round(t_restored - t_platform, 1),
        "rto_s": round(t_api - t_disaster, 1),
        "rpo_s": round(t_disaster - last_restored, 1) if last_restored else "",
        "data_written_after_last_marker_restored_s": round(last_written - last_restored, 1)
        if last_written and last_restored else "",
        "docs_before": docs_before, "docs_after": docs_after,
        "docs_present": docs_after == docs_before,
        "success": docs_after == docs_before and last_restored is not None,
    }
    write_csv(CSV, [row])
    log(f"drill: {row}")
    return summarize()


def summarize() -> int:
    rows = read_csv(CSV)
    ok = [r for r in rows if r["success"] == "True"]
    summary = {
        "drills": len(rows),
        "successful": len(ok),
        "rto": stats([float(r["rto_s"]) for r in ok]),
        "rpo": stats([float(r["rpo_s"]) for r in ok if r["rpo_s"]]),
        "last": rows[-1] if rows else None,
    }
    write_json(SUMMARY, summary)
    log(f"summary: {summary}")
    return 0 if rows and len(ok) == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
