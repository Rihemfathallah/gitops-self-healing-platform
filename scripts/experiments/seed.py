#!/usr/bin/env python3
"""Index the sample documents once (POST /api/index) and wait until ChromaDB has them.
Indexing is deliberately NOT done at startup: after a restore, the documents must
come back from the Velero backup, not from a re-index (otherwise the DR test proves nothing)."""

import sys
import time

import chroma
from lib import api_key, http, log, now


def main() -> int:
    before = chroma.count()
    if before:
        log(f"already seeded: {before} chunks")
        return 0
    status = http("POST", "/api/index", None, api_key())
    if status not in (200, 202):
        log(f"POST /api/index answered {status}")
        return 1
    deadline = now() + 600
    while now() < deadline:
        n = chroma.count()
        if n:
            time.sleep(10)  # let the indexer finish its last batch
            log(f"seeded: {chroma.count()} chunks")
            return 0
        time.sleep(5)
    log("timeout: no chunk indexed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
