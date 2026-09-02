# Plateforme GitOps auto-réparatrice — entry points.
# `make up` rebuilds the whole platform from scratch; `make down` removes it.

SHELL := /bin/bash
export KUBECONFIG := $(CURDIR)/.kube/config
TF_CLUSTER  := infra/terraform/cluster
TF_PLATFORM := infra/terraform/platform
PY := python3
EXP := scripts/experiments

.PHONY: help prereqs up cluster platform down destroy-cluster seed status urls secrets \
        test test-app test-rules lint dashboard \
        exp-rollback exp-slo exp-alerts exp-false-positives exp-dr postmortems results

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

prereqs: ## check local tools
	@for t in docker terraform kubectl git python3; do \
	  command -v $$t >/dev/null && echo "ok      $$t" || { echo "MISSING $$t"; missing=1; }; done; \
	  docker info >/dev/null 2>&1 && echo "ok      docker daemon" || { echo "MISSING docker daemon"; missing=1; }; \
	  [ -z "$$missing" ]

# ── Platform lifecycle (EF-01, EF-02) ────────────────────────────────
up: prereqs cluster platform ## create cluster + Argo CD + Velero, then GitOps syncs the rest
	@echo "Argo CD now syncs gitops/apps (≈10 min the first time). Follow with: make status"

cluster: ## kind cluster + S3 store (Terraform)
	terraform -chdir=$(TF_CLUSTER) init -input=false
	terraform -chdir=$(TF_CLUSTER) apply -auto-approve -input=false

platform: ## Argo CD, Velero, root app (Terraform)
	terraform -chdir=$(TF_PLATFORM) init -input=false
	terraform -chdir=$(TF_PLATFORM) apply -auto-approve -input=false

down: ## destroy everything, backups included
	-terraform -chdir=$(TF_PLATFORM) destroy -auto-approve -input=false
	terraform -chdir=$(TF_CLUSTER) destroy -auto-approve -input=false

destroy-cluster: ## destroy only the cluster (backups in the S3 store are kept)
	terraform -chdir=$(TF_CLUSTER) destroy -target=kind_cluster.this -auto-approve -input=false

seed: ## index the sample documents once
	cd $(EXP) && $(PY) seed.py

status: ## Argo CD applications, rollout, pods
	@kubectl -n argocd get applications
	@echo; kubectl -n neuralrag get rollout,pods
	@echo; kubectl -n velero get schedules,backups 2>/dev/null | tail -5

urls: ## where to click
	@terraform -chdir=$(TF_PLATFORM) output urls

secrets: ## API key and Grafana password (local only)
	@echo "API key          : $$(terraform -chdir=$(TF_PLATFORM) output -raw api_key)"
	@echo "Grafana admin pwd: $$(terraform -chdir=$(TF_PLATFORM) output -raw grafana_password)"

# ── Tests (also run in CI) ───────────────────────────────────────────
test: test-app test-rules ## all local tests

test-app: ## unit tests of the SLI and chaos middlewares (light deps)
	cd app/backend && $(PY) -m pytest -q tests/test_sli_chaos.py

test-rules: ## promtool: rule syntax + alert unit tests
	@mkdir -p build
	$(PY) scripts/ci/extract_rules.py gitops/observability/slo-rules.yaml build/slo-rules.rules.yaml
	promtool check rules build/slo-rules.rules.yaml
	promtool test rules tests/prometheus/slo-rules.test.yaml

dashboard: ## regenerate the Grafana dashboard ConfigMap
	$(PY) scripts/ci/build_dashboard.py > gitops/observability/dashboard-slo.yaml

lint: ## terraform fmt, helm lint
	terraform fmt -check -recursive infra/terraform
	helm lint charts/neuralrag -f gitops/releases/neuralrag.yaml

# ── Measurements (each writes to results/) ───────────────────────────
exp-rollback: ## N faulty releases -> rollback time (default 10)
	cd $(EXP) && $(PY) rollback_experiment.py --runs $${RUNS:-10}

exp-slo: ## 30 min k6 load test -> SLOs met?
	cd $(EXP) && $(PY) slo_loadtest.py --duration $${DURATION:-30m}

exp-alerts: ## inject the 3 incidents -> each one alerts?
	cd $(EXP) && $(PY) alert_experiment.py

exp-false-positives: ## after 24 h untouched -> 0 alert?
	cd $(EXP) && $(PY) false_positive_check.py --hours $${HOURS:-24}

exp-dr: ## destroy and restore the cluster -> RTO / RPO
	cd $(EXP) && $(PY) dr_drill.py

postmortems: ## one postmortem draft per simulated incident
	cd $(EXP) && $(PY) postmortem_draft.py

results: ## refresh the README results table from results/
	cd $(EXP) && $(PY) render_results.py
