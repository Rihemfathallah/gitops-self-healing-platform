# NeuralRAG backend image used by the GitOps platform.
# Differences from the original rag-devops-pfa image:
#   - embedding model baked in (no download at runtime, faster and reproducible rollouts/restores)
#   - non-root user, APP_VERSION exposed to metrics (neuralrag_build_info)
#   - sample documents baked in /data/documents (indexed once with `make seed`)

# ── Stage 1: dependencies ─────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Download the embedding model once, at build time
ENV HF_HOME=/opt/hf
ARG EMBED_MODEL=all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBED_MODEL}')"

# ── Stage 2: runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /opt/hf /opt/hf

COPY backend/ .
COPY sample-docs/ /data/documents/

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --uid 10001 --no-create-home appuser \
    && chown -R 10001:10001 /data /opt/hf
USER 10001

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
