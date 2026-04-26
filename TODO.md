# TODO: Add Comments to All Project Files

## Overview

Add clear, simple, short comments to all project files covering:

- Module/file role
- Parameter explanations
- How technologies/tools work
- Key design decisions

## Categories & Files

### A. Core Infrastructure (`src/core/`)

- [x] `logger.py` — Already heavily commented
- [x] `config.py` — Already heavily commented
- [ ] `observability.py` — Needs module docstring + function comments
- [ ] `singleton.py` — Needs module docstring + function comments
- [ ] `__init__.py` — Needs docstring

### B. Common Utilities (`src/common/`)

- [x] `anti_bot.py` — Already heavily commented
- [x] `captcha_solver.py` — Already heavily commented
- [x] `chunker.py` — Already commented
- [x] `column_detector.py` — Already heavily commented
- [x] `fs.py` — Already heavily commented
- [x] `llm_parser.py` — Already heavily commented
- [ ] `search_engine.py` — Needs inline comments + parameter docs
- [ ] `text_cleaner.py` — Needs module docstring + inline comments
- [ ] `universal_extractor.py` — Needs module docstring + section comments
- [ ] `disk_cleanup.py` — Needs module docstring + function docs
- [ ] `json_parser.py` — Needs module docstring + function docs
- [ ] `health_check.py` — Needs module docstring + function docs
- [ ] `metrics.py` — Needs module docstring + class/function docs
- [ ] `progress_tracker.py` — Needs module docstring + class/function docs
- [ ] `proxy_manager.py` — Needs module docstring + class/function docs

### C. Domain Layer (`src/domain/`)

- [ ] `excel/reader.py` — Needs module docstring + class/function docs
- [ ] `excel/writer.py` — Needs module docstring + function docs
- [ ] `excel/cleaner.py` — Needs module docstring + function docs
- [ ] `excel/__init__.py` — Needs docstring
- [ ] `search/phone_extractor.py` — Needs module docstring + function docs
- [ ] `search/__init__.py` — Needs docstring
- [ ] `enrichment/row_enricher.py` — Needs module docstring + function docs
- [ ] `enrichment/field_extractor.py` — Needs module docstring + function docs
- [ ] `enrichment/confidence.py` — Needs module docstring + function docs
- [ ] `enrichment/__init__.py` — Needs docstring
- [ ] `__init__.py` — Needs docstring

### D. Agents & Browsers (`src/agents/`, `src/infra/browsers/`)

- [ ] `agents/base_agent.py` — Needs module docstring + function docs
- [ ] `agents/enricher.py` — Needs module docstring + function docs
- [ ] `agents/phone_hunter.py` — Needs more inline comments
- [ ] `agents/__init__.py` — Needs docstring
- [x] `infra/browsers/hybrid_engine.py` — Already heavily commented
- [ ] `infra/browsers/patchright_agent.py` — Needs more comments
- [ ] `infra/browsers/nodriver_agent.py` — Needs more comments
- [ ] `infra/browsers/crawl4ai_agent.py` — Needs more comments
- [ ] `infra/browsers/camoufox_agent.py` — Already commented
- [ ] `infra/browsers/selenium_agent.py` — Needs more comments
- [ ] `infra/browsers/seleniumbase_agent.py` — Needs reading + comments
- [ ] `infra/browsers/__init__.py` — Needs docstring

### E. App Layer (`src/app/`)

- [ ] `app/orchestrator.py` — Needs module docstring + function docs
- [ ] `app/monitoring/app.py` — Needs module docstring + function docs
- [ ] `app/monitoring/models.py` — Needs module docstring + class docs
- [ ] `app/monitoring/__init__.py` — Needs docstring
- [ ] `app/__init__.py` — Needs docstring

### F. Infrastructure/Intelligence (`src/infra/intelligence/`)

- [ ] `infra/intelligence/ollama_client.py` — Needs reading + comments
- [ ] `infra/intelligence/router.py` — Needs module docstring + function docs
- [ ] `infra/intelligence/prompt_optimizer.py` — Needs reading + comments
- [ ] `infra/intelligence/__init__.py` — Needs docstring

### G. Scripts (`scripts/`)

- [ ] `scripts/entrypoint.sh` — Needs comments
- [ ] `scripts/start_with_monitoring.sh` — Already commented
- [ ] `scripts/setup_dev.sh` — Needs comments
- [ ] `scripts/update.sh` — Needs comments
- [ ] `scripts/update.bat` — Needs comments
- [ ] `scripts/benchmark_engines.py` — Needs comments
- [ ] `scripts/clean_chrome_profiles.py` — Needs comments
- [ ] `scripts/consolidate_results.py` — Needs comments
- [ ] `scripts/fix_imports.py` — Needs comments
- [ ] `scripts/log_manager.py` — Needs comments
- [ ] `scripts/rebuild_output.py` — Needs comments
- [ ] `scripts/resilient_agent_demo.py` — Needs comments
- [ ] `scripts/security_dast.py` — Needs comments
- [ ] `scripts/security_sast.py` — Needs comments
- [ ] `scripts/test_architecture.sh` — Needs comments
- [ ] `scripts/validator.py` — Needs comments

### H. Config/Root Files

- [ ] `bootstrap.py` — Needs module docstring + comments
- [x] `Dockerfile` — Already heavily commented
- [ ] `docker-compose.yml` — Needs more inline comments
- [x] `requirements.txt` — Already heavily commented
- [ ] `requirements-prod.txt` — Needs comments
- [ ] `pyproject.toml` — Needs comments
- [ ] `.env.example` — Needs comments
- [ ] `config/prometheus.yml` — Needs comments

### I. Documentation (\*.md files)

- [ ] `README.md` — Check if comments/annotations needed
- [ ] `ARCHITECTURE.md` — Check if comments needed
- [ ] `AGENTS.md` — Check if comments needed
- [ ] `CLAUDE.md` — Check if comments needed
- [ ] `RULES.md` — Check if comments needed
- [ ] `SOUL.md` — Check if comments needed
- [ ] `SECURITY.md` — Check if comments needed
- [ ] `TODO.md` — This file itself

### J. Tests (`tests/`)

- [ ] `tests/test_agent_pool.py` — Needs comments
- [ ] `tests/test_anti_detection.py` — Needs comments
- [ ] `tests/test_cleaner.py` — Needs comments
- [ ] `tests/test_core.py` — Needs comments
- [ ] `tests/test_hybrid_escalation.py` — Needs comments
- [ ] `tests/test_orchestrator.py` — Needs comments
- [ ] `tests/test_proxy_circuit_breaker.py` — Needs comments
- [ ] `tests/__init__.py` — Needs docstring
- [ ] `tests/README.md` — Check if comments needed

### K. K8s Configs (`k8s/`)

- [ ] `k8s/configmap.yaml` — Needs comments
- [ ] `k8s/deployment.yaml` — Needs comments
- [ ] `k8s/persistent-volume.yaml` — Needs comments
