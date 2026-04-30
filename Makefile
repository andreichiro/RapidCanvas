SHELL := /bin/bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help setup setup-backend setup-backend-full setup-frontend lint backend-lint frontend-lint test backend-test frontend-test dev dev-backend dev-frontend eval optimize mlflow-log mlflow-ui clean clean-generated check-secrets config-check frontend-audit frontend-build extras-dry-run requirements-review maintainability-review api-smoke frontend-smoke user-smoke deep-review

help:
	@echo "Bluesky Contextual Post Explainer"
	@echo ""
	@echo "Primary commands:"
	@echo "  make setup              Install backend dev deps and frontend deps"
	@echo "  make setup-backend-full Install backend optional deps for later phases"
	@echo "  make lint               Run backend and frontend lint/type checks"
	@echo "  make test               Run backend and frontend tests"
	@echo "  make deep-review        Run the full local review gate"
	@echo "  make requirements-review Validate Gate 1 requirement mappings"
	@echo "  make user-smoke         Exercise the scaffold as a user would"
	@echo "  make dev-backend        Start FastAPI scaffold"
	@echo "  make dev-frontend       Start Vite scaffold"
	@echo "  make check-secrets      Check that local secrets are not tracked"
	@echo ""
	@echo "Later-phase commands:"
	@echo "  make eval | make optimize | make mlflow-log | make mlflow-ui"

setup: setup-backend setup-frontend

setup-backend:
	cd $(BACKEND_DIR) && uv sync --dev

setup-backend-full:
	cd $(BACKEND_DIR) && uv sync --dev --all-extras

setup-frontend:
	npm --prefix $(FRONTEND_DIR) install

lint: backend-lint frontend-lint

backend-lint:
	cd $(BACKEND_DIR) && uv run ruff check app && uv run mypy app

frontend-lint:
	npm --prefix $(FRONTEND_DIR) run lint

test: backend-test frontend-test

backend-test:
	cd $(BACKEND_DIR) && uv run pytest app/tests

frontend-test:
	npm --prefix $(FRONTEND_DIR) test

config-check:
	cd $(BACKEND_DIR) && uv run python -m app.config >/tmp/rapidcanvas_config_check.json
	python -m json.tool /tmp/rapidcanvas_config_check.json >/dev/null

frontend-audit:
	npm --prefix $(FRONTEND_DIR) audit --audit-level=moderate

frontend-build:
	npm --prefix $(FRONTEND_DIR) run build

extras-dry-run:
	cd $(BACKEND_DIR) && uv sync --dev --all-extras --dry-run >/tmp/rapidcanvas_extras_dry_run.txt 2>&1
	@echo "Optional backend dependencies resolve."

maintainability-review:
	python3 scripts/review_quality.py

requirements-review:
	python3 scripts/check_requirements_matrix.py

api-smoke:
	@bash -lc 'set -euo pipefail; \
		cd "$(BACKEND_DIR)"; \
		LOG_FILE="/tmp/rapidcanvas_api_smoke.log"; \
		uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 >"$$LOG_FILE" 2>&1 & \
		PID=$$!; \
		trap "kill $$PID >/dev/null 2>&1 || true" EXIT; \
		for _ in {1..30}; do \
			if curl -fsS http://127.0.0.1:8001/api/health >/tmp/rapidcanvas_api_smoke_response.json 2>/dev/null; then \
				python -m json.tool /tmp/rapidcanvas_api_smoke_response.json >/dev/null; \
				cat /tmp/rapidcanvas_api_smoke_response.json; \
				echo; \
				exit 0; \
			fi; \
			sleep 0.5; \
		done; \
		cat "$$LOG_FILE"; \
		exit 1'

frontend-smoke:
	@bash -lc 'set -euo pipefail; \
		LOG_FILE="/tmp/rapidcanvas_frontend_smoke.log"; \
		npm --prefix "$(FRONTEND_DIR)" run dev -- --host 127.0.0.1 --port 5174 >"$$LOG_FILE" 2>&1 & \
		PID=$$!; \
		trap "kill $$PID >/dev/null 2>&1 || true" EXIT; \
		for _ in {1..30}; do \
			if curl -fsS http://127.0.0.1:5174 >/tmp/rapidcanvas_frontend_smoke.html 2>/dev/null; then \
				grep -q "Bluesky Contextual Post Explainer" /tmp/rapidcanvas_frontend_smoke.html; \
				echo "Frontend smoke loaded application shell."; \
				exit 0; \
			fi; \
			sleep 0.5; \
		done; \
		cat "$$LOG_FILE"; \
		exit 1'

user-smoke: api-smoke frontend-smoke

deep-review: lint test check-secrets config-check frontend-audit frontend-build extras-dry-run requirements-review clean-generated maintainability-review user-smoke

dev:
	@echo "Run backend and frontend in separate terminals:"
	@echo "  make dev-backend"
	@echo "  make dev-frontend"

dev-backend:
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload

dev-frontend:
	npm --prefix $(FRONTEND_DIR) run dev

eval:
	@echo "T9 is not implemented yet. This command is reserved for the evaluation harness."
	@exit 2

optimize:
	cd $(BACKEND_DIR) && uv run python -m app.eval.optimize --dry-run

mlflow-log:
	cd $(BACKEND_DIR) && uv run --extra eval --extra ai python -m app.agent.log_mlflow --reports-dir ../reports

mlflow-ui:
	cd $(BACKEND_DIR) && uv run --extra eval mlflow ui --backend-store-uri "$${MLFLOW_TRACKING_URI:-file:./mlruns}"

check-secrets:
	@if git ls-files | grep -E '(^|/)\.env($|\.)' | grep -vE '(^|/)\.env\.example$$'; then \
		echo "Tracked env file detected. Remove it before committing."; \
		exit 1; \
	fi
	@if rg --hidden -n -e 'sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}' \
		--glob '!.git/**' \
		--glob '!backend/.venv/**' \
		--glob '!frontend/node_modules/**' \
		--glob '!frontend/dist/**' \
		--glob '!backend/mlruns/**' \
		--glob '!mlruns/**' \
		. >/tmp/bluesky_secret_scan.txt 2>/dev/null; then \
		cat /tmp/bluesky_secret_scan.txt; \
		echo "Potential API key detected in unignored project content."; \
		exit 1; \
	fi
	@echo "No tracked .env files or obvious OpenAI keys found in unignored project files."

clean:
	rm -rf $(FRONTEND_DIR)/dist $(BACKEND_DIR)/mlruns mlruns
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.ruff_cache $(BACKEND_DIR)/.mypy_cache
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/coverage

clean-generated:
	rm -rf $(FRONTEND_DIR)/dist $(BACKEND_DIR)/mlruns mlruns
