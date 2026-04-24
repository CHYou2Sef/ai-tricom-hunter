# AI Tricom Hunter — docs/Recupered Upgrade TODO

## Phase A — Structural Foundation

- [x] Create `Recupered/RAPPORT_COMPLET_PFE.md` — Complete PFE report (NEW)
- [x] **MERGE** `docs/Recupered/DAILY_JOURNAL.md` + `docs/DAILY_JOURNAL.md` — Unified into root-level file, all entries preserved
- [ ] Rewrite `Recupered/README.md` — Fix links, add Telemetry/K8s/Tier Reference sections
- [ ] Update `Recupered/01_system_architecture.md` — 6-tier pool, current module paths, Prometheus/Grafana
- [ ] Update `Recupered/02_extraction_cascade.md` — Add Step 1.5 Deep Discovery, 6-step cascade
- [ ] Update `Recupered/03_enrichment_dataflow.md` — Sync module names, add telemetry flush node
- [ ] Update `Recupered/04_comparative_matrices.md` — Add Phase 5 Stealth column, Tier Benchmark matrix
- [ ] Update `Recupered/05_scaling_topology.md` — Add K8s manifests, browserless container, S3/MinIO

## Phase B — Core Documentation Overhaul

- [x] Update `Recupered/PROJECT_REPORT.md` — Already current (verified)
- [ ] Update `Recupered/ENRICHMENT_ARCHITECTURE.md` — Add latency/tier/scrap_source to audit schema
- [ ] Update `Recupered/PERFORMANCE_AND_SECURITY.md` — Add Bandit results, Prometheus labels, K8s security
- [ ] Update `Recupered/SEARCH_OPTIMIZATIONS.md` — Sync prompt templates from config.py
- [ ] Update `Recupered/multi_agent_cross_platform_study.md` — Add 4-Pillar framework, uv/pathlib
- [ ] Update `Recupered/architecture_research.md` — Merge with ARCHITECTURE.md, add browserless
- [ ] Update `Recupered/pipeline_visuals.md` — Add Deep Discovery, checkpoint/telemetry side-flow
- [ ] Update `Recupered/presentation.md` — Update metrics, replace 3-tier with 6-tier, V4 branding

## Phase C — Implementation Plans (Archive + Summary)

- [ ] Archive `Recupered/implementation_plan_clean.md` — Mark IMPLEMENTED, retrospective note
- [ ] Archive `Recupered/implementation_plan_perfo.md` — Mark IMPLEMENTED, reference metrics.py
- [ ] Archive `Recupered/implementation_plan_03_04.md` — Mark PARTIALLY IMPLEMENTED/REFINED
- [ ] Archive `Recupered/implementation_plan2.md` — Mark PARTIALLY IMPLEMENTED, note asyncio.Queue choice
- [ ] Create `Recupered/implementation_plan_async_error.md` — Document thread fix + asyncio.Semaphore

## Phase D — Visual Assets (SVGs & Diagrams)

- [ ] Replace `hybrid_engine_waterfall.svg` — 6-tier + circuit breaker + proxy rotation
- [ ] Update `02_extraction_cascade.svg` — Add Deep Discovery + Expert Retry loop
- [ ] Update `05_scaling_topology.svg` — Add K8s ingress, browserless pod, S3 bucket
- [ ] Update `stealth_fingerprint_bundle.svg` — 10-property CDP bundle from config.py
- [ ] Update `eeat_reliability_pyramid.svg` — Add Tier provenance weights + telemetry
- [ ] Update `System_Architecture_2026.svg` — Reflect 6-tier + ingest + metrics stack
- [ ] Update `ai_phone_hunter_architecture.svg` — Reconcile with docs/architecture_overview.svg
- [ ] Update `pipeline.svg` — Sync with pipeline_visuals.md
- [ ] Update `excel_to_output_workflow.svg` — Show checkpoint JSON + telemetry + daily fusion
- [ ] Update `arch_globale.svg` — French variant of global architecture

## Phase E — Daily Journal & Misc

- [x] **MERGED** `DAILY_JOURNAL.md` — Unified root-level file with ALL entries from both sources
- [ ] Consolidate `gemini_1.md` → `GEMINI6.md` into `GEMINI_DESIGN_LOG.md`
- [ ] Archive `histo-chat.txt`, `errrrrr.txt` to `raw_chats/` or delete
- [ ] Review/delete `winconvert.md`
- [ ] Update `slides.html` — Sync with updated presentation.md

## Phase F — New Additions (Missing Docs)

- [x] Create `Recupered/TIER_REFERENCE_CARD.md` — 6-tier quick-lookup table
- [x] Create `Recupered/ENVIRONMENT_SETUP_MATRIX.md` — Windows/Linux/macOS/Docker setup
- [x] Create `Recupered/TROUBLESHOOTING_MATRIX.md` — Common failures → diagnostic → fix
- [x] Create `Recupered/TELEMETRY_GUIDE.md` — telemetry.json, MTTI, Prometheus/Grafana setup
- [x] Create `Recupered/CHANGELOG_V3_TO_V4.md` — Migration notes 3-tier → 6-tier
- [x] Create `Recupered/OPERATIONS_GUIDE.md` — Pause/stop, DockerHub, multi-worker, monitoring
- [x] Create `Recupered/TECHNICAL_DECISION_LOG.md` — 10 ADRs explaining all technical choices
- [x] Create `Recupered/K8S_TESTING_GUIDE.md` — K8s deployment, 4 test scenarios, troubleshooting
- [x] Create `Recupered/PROMETHEUS_GRAFANA_SETUP.md` — Observability stack setup & testing
- [x] Create `Recupered/CRITICAL_REVIEW_CHECKLIST.md` — Pre-production security/perf/reliability audit
- [x] Create `Recupered/LANGCHAIN_MIGRATION_ROADMAP.md` — V5 LangGraph migration plan (5 phases)
