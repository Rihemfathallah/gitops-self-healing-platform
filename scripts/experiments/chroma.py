"""Small helpers that talk to ChromaDB from inside its own pod (kubectl exec),
so no port-forward and no extra client install are needed."""

from __future__ import annotations

import json

from lib import NS, kubectl

POD = "neuralrag-chromadb-0"
COLLECTION = "rag_documents"
MARKERS = "dr_markers"

_PY = """
import json, sys, chromadb
c = chromadb.HttpClient(host="localhost", port=8000)
op = sys.argv[1]
if op == "count":
    try:
        print(json.dumps(c.get_collection(sys.argv[2]).count()))
    except Exception:
        print(json.dumps(0))
elif op == "mark":
    col = c.get_or_create_collection(sys.argv[2])
    ts = sys.argv[3]
    col.add(ids=[ts], documents=["dr marker " + ts], embeddings=[[0.0, 0.0, 0.0]])
    print(json.dumps(ts))
elif op == "max_marker":
    try:
        ids = c.get_collection(sys.argv[2]).get(include=[])["ids"]
        print(json.dumps(max(float(i) for i in ids) if ids else None))
    except Exception:
        print(json.dumps(None))
"""


def _run(*args: str):
    out = kubectl("-n", NS, "exec", POD, "-c", "chromadb", "--", "python", "-c", _PY, *args)
    return json.loads(out.splitlines()[-1])


def count(collection: str = COLLECTION) -> int:
    return int(_run("count", collection))


def write_marker(ts: float) -> None:
    _run("mark", MARKERS, f"{ts:.3f}")


def last_marker() -> float | None:
    return _run("max_marker", MARKERS)
