SHELL := /bin/bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help setup setup-backend setup-backend-full setup-frontend lint backend-lint frontend-lint test backend-test frontend-test run dev start dev-backend dev-frontend docker-config docker-up docker-down eval gate6-shipping-audit gate7-final-truth-audit optimize mlflow-log mlflow-ui clean clean-generated check-secrets config-check frontend-audit frontend-build extras-dry-run requirements-review skills-review maintainability-review api-smoke frontend-smoke user-smoke deep-review

help:
	@echo "Bluesky Contextual Post Explainer"
	@echo ""
	@echo "Primary commands:"
	@echo "  make setup              Install full backend review deps and frontend deps"
	@echo "  make setup-backend-full Alias for full backend review deps"
	@echo "  make lint               Run backend and frontend lint/type checks"
	@echo "  make test               Run backend and frontend tests"
	@echo "  make deep-review        Run the full local review gate"
	@echo "  make requirements-review Validate Gate 1 requirement mappings"
	@echo "  make skills-review      Validate local project skills"
	@echo "  make user-smoke         Exercise the scaffold as a user would"
	@echo "  make run                One-command full Docker stack: UI, API, Qdrant, MLflow"
	@echo "  make dev                Install deps and start FastAPI + Vite in one terminal"
	@echo "  make dev-backend        Start only FastAPI"
	@echo "  make dev-frontend       Start only Vite"
	@echo "  make docker-up          Build and start backend + frontend with Docker"
	@echo "  make check-secrets      Check that local secrets are not tracked"
	@echo ""
	@echo "Evaluation and later-phase commands:"
	@echo "  make eval                 Run cached eval fixtures and write ignored reports"
	@echo "  make gate6-shipping-audit Regenerate eval reports and verify Gate 6 truth layer"
	@echo "  make gate7-final-truth-audit Verify final truth docs do not overclaim"
	@echo "  make optimize             Verify/preserve GEPA saved program metadata"
	@echo "  make mlflow-log           Create a local MLflow run"
	@echo "  make mlflow-ui            Start the local MLflow UI"

setup: setup-backend setup-frontend

setup-backend:
	cd $(BACKEND_DIR) && uv sync --dev --all-extras

setup-backend-full: setup-backend

setup-frontend:
	npm --prefix $(FRONTEND_DIR) ci

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

skills-review:
	python3 scripts/quick_validate.py .codex/skills/*

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

deep-review: lint test check-secrets config-check frontend-audit frontend-build extras-dry-run requirements-review skills-review clean-generated maintainability-review user-smoke

run: docker-up

dev: setup
	@bash -lc 'set -euo pipefail; \
		BACKEND_LOG="/tmp/rapidcanvas_dev_backend.log"; \
		FRONTEND_LOG="/tmp/rapidcanvas_dev_frontend.log"; \
		BACKEND_PID=""; \
		FRONTEND_PID=""; \
		cleanup() { \
			if [[ -n "$$BACKEND_PID" ]]; then kill "$$BACKEND_PID" >/dev/null 2>&1 || true; fi; \
			if [[ -n "$$FRONTEND_PID" ]]; then kill "$$FRONTEND_PID" >/dev/null 2>&1 || true; fi; \
		}; \
		trap cleanup INT TERM EXIT; \
		if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then \
			echo "Reusing healthy FastAPI on http://127.0.0.1:8000"; \
		else \
			echo "Starting FastAPI on http://127.0.0.1:8000"; \
			cd "$(BACKEND_DIR)" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload >"$$BACKEND_LOG" 2>&1 & \
			BACKEND_PID=$$!; \
			for _ in {1..60}; do \
				if ! kill -0 "$$BACKEND_PID" >/dev/null 2>&1; then break; fi; \
				curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; \
				sleep 0.5; \
			done; \
			if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then \
				echo "FastAPI did not become healthy. Backend log:"; \
				tail -80 "$$BACKEND_LOG"; \
				exit 1; \
			fi; \
		fi; \
		if curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then \
			echo "Reusing React UI on http://localhost:5173"; \
		else \
			echo "Starting React UI on http://localhost:5173"; \
			npm --prefix "$(FRONTEND_DIR)" run dev -- --host 0.0.0.0 --port 5173 --strictPort >"$$FRONTEND_LOG" 2>&1 & \
			FRONTEND_PID=$$!; \
			for _ in {1..60}; do \
				if ! kill -0 "$$FRONTEND_PID" >/dev/null 2>&1; then break; fi; \
				curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1 && break; \
				sleep 0.5; \
			done; \
			if ! curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then \
				echo "React UI did not become reachable on port 5173. Frontend log:"; \
				tail -80 "$$FRONTEND_LOG"; \
				exit 1; \
			fi; \
		fi; \
		echo "Ready: open http://localhost:5173"; \
		echo "Paste a Bluesky post URL and your OpenAI key into the masked field."; \
		if [[ -z "$$BACKEND_PID$$FRONTEND_PID" ]]; then exit 0; fi; \
		while true; do \
			if [[ -n "$$BACKEND_PID" ]] && ! kill -0 "$$BACKEND_PID" >/dev/null 2>&1; then \
				echo "FastAPI exited. Recent backend log:"; tail -40 "$$BACKEND_LOG"; exit 1; \
			fi; \
			if [[ -n "$$FRONTEND_PID" ]] && ! kill -0 "$$FRONTEND_PID" >/dev/null 2>&1; then \
				echo "React UI exited. Recent frontend log:"; tail -40 "$$FRONTEND_LOG"; exit 1; \
			fi; \
			sleep 1; \
		done'

start: dev

dev-backend:
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload

dev-frontend:
	npm --prefix $(FRONTEND_DIR) run dev

docker-config:
	docker compose config

docker-up:
	docker compose up --build

docker-down:
	docker compose down

eval:
	cd $(BACKEND_DIR) && uv run python -m app.eval.runner --cases eval/posts.yaml --out reports/eval

gate6-shipping-audit: eval
	python3 scripts/check_gate6_shipping_audit.py

gate7-final-truth-audit: eval
	python3 scripts/check_gate7_final_truth.py

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
	find reports -mindepth 1 ! -name .gitkeep -exec rm -rf {} +

clean-generated:
	rm -rf $(FRONTEND_DIR)/dist $(BACKEND_DIR)/mlruns mlruns
	find reports -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
