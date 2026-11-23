# Phased Implementation Roadmap (25 Items Grouped)

| Phase | Target – what will be functional | Key Files / Artifacts | Approx. Effort |
|------|-----------------------------------|-----------------------|----------------|
| **0️⃣ Prep** | Repo hygiene – add `requirements.txt`, `.gitignore` tweaks, tooling scaffolding. | `requirements.txt`, `setup.cfg` (ruff, mypy), `pre‑commit-config.yaml` | 0.5 day |
| **1️⃣ Persistent State & Incident State‑Machine** | SQLite fallback → Postgres (optional). DB tables for incidents, alerts, tool calls, approvals, verification reports. | `prahari/store/models.py`, `prahari/store/__init__.py`, `prahari/store/audit.py`, Alembic migration folder | 1 day |
| **2️⃣ LLM Tool‑Calling Loop** | Replace deterministic mapping in `agent/loop.py` with a budget‑aware LLM loop that reads/writes the DB. | Updated `agent/loop.py`, config `agent/budget.yaml` | 1 day |
| **3️⃣ Real‑Branch Patch Generation** | `propose_patch` now creates a Git branch, applies a unified diff, generates a regression test, and commits. | New module `agent/patcher.py`, helper script `scripts/create_branch.sh` | 1 day |
| **4️⃣ Isolated Worktree Verification** | After patch creation, `git worktree add` a temporary worktree, run tests inside a *sandboxed* virtualenv (or Docker container) and store results in `verification_report`. | `agent/verifier.py`, Dockerfile `verifier/Dockerfile`, volume mount `state/` | 2 days |
| **5️⃣ Docker Architecture Fix** | Shared volume (or central Postgres/Redis) mounted by both `dashboard` and `target_app` containers so fault state & artifacts are synchronized. | Updated `docker-compose.yml`, volume definition `shared_state` | 0.5 day |
| **6️⃣ Always‑Running Detector Service** | Convert detector code into a FastAPI background service that polls metrics/logs, writes alerts to DB, and auto‑triggers the LLM loop. | New `detector/service.py`, `detector/Dockerfile`, API endpoint `/detect` | 1 day |
| **7️⃣ Replay‑Based Verification** | Load captured traffic (`traffic/replay.py`), replay against the staging worktree, compute baseline/error‑rate/latency, gate “approve” button. | `verifier/replay_test.py`, metrics aggregation script | 1.5 days |
| **8️⃣ Bad‑Deploy Scenario** | Script that deliberately introduces a regression, runs the full pipeline, and demonstrates pre‑fix failure / post‑fix success. | `scripts/bad_deploy_demo.sh` | 0.5 day |
| **9️⃣ Authentication & RBAC** | Add FastAPI JWT auth, role tables, endpoint protection for incident injection, approvals, and production actions. | `auth/jwt.py`, `auth/models.py`, middleware | 2 days |
| **🔟 Signed Human Approvals** | UI + API to create expiring, cryptographically signed approvals; store signer, reason, expiry. | `frontend/src/ApprovalForm.tsx`, `api/approvals.py` | 1.5 days |
| **1️⃣1️⃣ Change‑Risk Scoring & Policies** | Risk engine that estimates blast‑radius, rollback plan, and enforces policy rules before any patch is applied. | `risk/engine.py`, policy JSON config | 1 day |
| **1️⃣2️⃣ Container Isolation & Least‑Privileged Runtime** | Dockerfiles that run as non‑root, restrict network/filesystem, add seccomp profile. | Updated `Dockerfile`s, `docker-compose.yml` security settings | 0.5 day |
| **1️⃣3️⃣ Secret Redaction & Audit Logging** | Central log sink (Postgres table or file) with PII scrubbing, immutable evidence IDs, retention config. | `audit/logging.py`, `audit/models.py` | 1 day |
| **1️⃣4️⃣ Atomic File‑State Updates** | Replace mutable global test state with transactional writes (e.g., using `tempfile` & rename). | Utility `utils/atomic_write.py` | 0.5 day |
| **1️⃣5️⃣ Observability Adapters** | Export metrics/logs to Prometheus, Loki, Sentry; add webhook adapters for GitHub, PagerDuty, Slack, Datadog. | `observability/prometheus.py`, `observability/webhooks.py` | 2 days |
| **1️⃣6️⃣ OpenTelemetry Tracing** | Instrument detector, LLM loop, patcher, verifier with OTEL spans; export to Jaeger or CloudTrace. | `otel/tracing.py`, config `otel.yaml` | 1 day |
| **1️⃣7️⃣ SLOs & Alert Management** | Define error‑budget SLOs, anomaly detection, deduplication, suppression windows. | `slo/config.yaml`, alert aggregation service | 1 day |
| **1️⃣8️⃣ CI/CD Webhook Integration** | Endpoint that parses GitHub/GitLab webhook payloads to auto‑start incidents on deploy. | `ci/webhook_handler.py`, Dockerfile | 1 day |
| **1️⃣9️⃣ Dependency‑Health Adapter** | Probe external services, expose health scores, suggest retries/circuit‑breakers. | `deps/health.py`, config `deps.yml` | 1 day |
| **2️⃣0️⃣ Agent‑Quality Enhancements** | Hypothesis ranking, evidence citations, memory retrieval, retry planner, rollback‑first mode, replay cache. | Several helper modules under `agent/quality/` (≈ 6 files) | 2 days |
| **2️⃣1️⃣ Dashboard UI Revamp** | Replace raw HTML with a React/HTMX SPA that consumes the SSE endpoint, shows timeline, evidence, diff, test logs, replay graph, approvals. | `dashboard/frontend/` (React), new `dashboard/Dockerfile` | 3 days |
| **2️⃣2️⃣ Engineering Quality** | Ruff, mypy, coverage gates, pre‑commit, GitHub Actions, container scanning, healthchecks, env validation. | Config files (`pyproject.toml`, `.github/workflows/ci.yml`, etc.) | 2 days |
| **2️⃣3️⃣ SQLAlchemy + Postgres (Production) & SQLite Fallback** | Already covered in Phase 1, but ensure migrations, connection pooling, and seed data. | `prahari/store/seed.py` | 0.5 day |
| **2️⃣4️⃣ Seed Realistic Git History & Traffic** | Add sample commits, deployment metadata, incident JSON samples, and recorded traffic files. | `seed/` folder, scripts to import into DB | 1 day |

**Total estimated effort:** ~ 24 person‑days (≈ 5 working weeks) if done by a single developer, but many steps can be parallelized.

---

### How to Use This Roadmap
* Each phase is deliberately incremental; you can checkout the code after any phase and have a runnable system.
* The **Key Files / Artifacts** column lists the new or modified files you should expect to see in the repository after the phase is completed.
* The **Approx. Effort** column is a rough estimate for a single developer familiar with the stack.
* Feel free to reorder phases based on project‑specific priorities (e.g., start with Docker fix if you need immediate UI sync).

---

*This document is generated as a living artifact—keep it under version control (e.g., `docs/ROADMAP.md`) and update it as you complete each phase.*

## Implementation status

| Phase | Status | Scope notes |
|------:|:-------|:------------|
| 0 | Complete | Packaging, Ruff, mypy, pre-commit, CI, coverage and container scanning are configured. |
| 1 | Complete | SQLAlchemy persistence, SQLite/PostgreSQL support, Alembic migrations and incident/audit/alert/approval/report tables. |
| 2 | Complete | Anthropic tool loop has per-run/daily budgets, an allowlist, evidence citations and audited results; API credentials remain optional. |
| 3 | Partial | Branch-only diff application, path/risk checks and commits are implemented; patches require a clean, tracked repository and a proposed regression test. |
| 4 | Complete | Candidate Docker builds run with no network, a read-only filesystem and dropped capabilities; Docker must be available to the invoking host process. |
| 5 | Complete | Compose services share PostgreSQL state and artifact volumes. |
| 6 | Complete | Detector FastAPI worker polls, deduplicates, stores and investigates alerts. |
| 7 | Complete | Captured requests replay against the candidate and gate verification by tests, error rate and latency. |
| 8 | Partial | Local bad-deploy demo proves injected failure and recovery; it does not fabricate a candidate patch or production deployment. |
| 9 | Complete | Auth0 JWT role checks protect operational routes; production rejects local-token auth. |
| 10 | Complete | Approvals have required reasons, expiry and HMAC signatures, and require verified candidates. |
| 11 | Complete | Risk scoring and allowlisted patch policy run before branch creation. |
| 12 | Partial | Containers are non-root, read-only where practical, capability-dropped and use Docker's default seccomp profile; no custom profile is supplied. |
| 13 | Complete | Audit/tool records are redacted and retention-pruned; evidence IDs are attached to tool results. |
| 14 | Complete | Shared artifact writes use atomic replacement. |
| 15 | Partial | Prometheus, Sentry, GitHub/GitLab webhooks, Slack, Telegram, PagerDuty and deployment clients are available; Loki/Datadog export and production-specific connector validation remain external setup. |
| 16 | Complete | Detector, agent, patcher and verifier expose opt-in OTLP spans. |
| 17 | Complete | Configured rolling-window SLOs create, deduplicate and resolve alerts. |
| 18 | Partial | Signed GitHub and GitLab deployment-status webhooks are supported; provider-specific event variants still require integration testing. |
| 19 | Complete | Dependency probes are bounded and report retry/circuit-breaker guidance for transient failures. |
| 20 | Complete | Hypothesis ranking, citation checks, memory retrieval, bounded retry planning, rollback-first assessment and revision-keyed replay caching are implemented. |
| 21 | Partial | Responsive fetch/SSE dashboard exposes operations, evidence, diff, tests, replay and approvals; it is not a React/HTMX frontend and has no graph visualization. |
| 22 | Complete | CI runs lint, type checks, coverage gates, container build/scanning and service healthchecks; environment validation fails closed in production. |
| 23 | Complete | PostgreSQL is the Compose default, SQLite is the local fallback, and seed data is repeatable. |
| 24 | Partial | Representative deployments, incidents and captured traffic are seeded; synthetic Git commit history is intentionally not generated in the user's repository. |

External provider credentials, an available Docker daemon, and a clean committed
Git repository are required for corresponding live integration paths. These
requirements are not simulated as successful production actions.