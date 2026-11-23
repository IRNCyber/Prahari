# Prahari

Prahari is an AI on-call engineer demo: it detects a sample-service incident,
investigates it, prepares a branch-only fix, verifies the result, and asks a
human to approve the outcome.

## Quickstart

1. Copy `.env.example` to `.env` and set local credentials as needed.
2. Create and activate a Python 3.12+ virtual environment.
3. Install dependencies: `python -m pip install -r requirements.txt`.
4. Start both services: `docker compose up --build`.
5. Open `http://localhost:8080` and inject an incident.
6. Click **Investigate**, then **Heal** and **Investigate** again to see green verification.

Without Docker, use two terminals: `python main.py serve` and `python main.py dashboard`.
Run `python -m detector.watcher --url http://localhost:8000` in a third terminal to continuously evaluate alerts.

## Demo flow

```text
Target service -> metrics/logs -> detector -> Prahari tools -> proposed branch-only fix
       ^                                                               |
       +---------------- traffic replay + verifier + human approval --+
```

Run a CLI demonstration with `python main.py break --scenario bad_deploy`,
`python main.py investigate`, `python main.py heal`, and `python main.py verify`.
The dependency outage scenario intentionally ends in escalation rather than a code fix.
Run `python main.py seed-demo` to load repeatable deployment/incident history and
captured traffic, or `python scripts/bad_deploy_demo.py` to see the injected failure
and recovery without starting Docker.

## Safety

- Fault injection is restricted to the local sample service.
- Proposed fixes are written to `artifacts/proposed_fix.diff`; the default branch is never changed.
- Patch generation requires a clean Git worktree and only allows sample-service and test files.
- Candidate verification builds and runs in a network-isolated, read-only Docker container.
- A report is only green when the test suite, regression condition, and healthy replay state pass.
- No production deployment is performed automatically.
- `.env` is excluded from Docker build contexts; never commit it or put real credentials in `.env.example`.

## Operations

Runtime state and audit events use PostgreSQL in Docker Compose and SQLite under
`data/prahari.db` (or `PRAHARI_DATA_DIR`) when `DATABASE_URL` is unset. Alembic
migrations run on CLI startup. All services use the same database, so incident
state and evidence remain synchronized.
The demo Compose credentials are for local use only. Production startup requires
Auth0 JWT configuration, a non-default PostgreSQL password, and a long approval
token; set these through a secret manager rather than a committed file.

Every control action, test result, patch proposal, escalation, approval, and
postmortem is recorded in the audit log. View recent events through
`GET /api/incidents` on the dashboard service.

The project includes connector contracts for production telemetry, logging,
deployment, and notifications in `agent/adapters.py`; supply organisation-specific
implementations and credentials outside the demo repository.

## External integrations

`AUTH_PROVIDER=auth0` enables JWT validation using the configured issuer and
audience. Operator and approver roles must be present in token permissions (or
the `https://prahari.dev/roles` claim). In production, do not set the provider
to `none`. `GET /api/integrations` reports which configured adapters are ready
without revealing secrets. Slack, Telegram, and PagerDuty delivery is opt-in via
`PRAHARI_SEND_NOTIFICATIONS=true`; failures are reported in the API result and audit
log. Sentry error reporting and OTLP tracing start only when their endpoints are
configured. A valid `X-Prahari-Approver-Token` header is required for the approval endpoint.

GitHub and GitLab deployment-status webhooks require their respective shared
secrets and an exact repository match. GitHub PR creation and Render/Koyeb
deployment clients require credentials; production deployment is never part of
the automatic incident loop.

Run quality checks with `ruff check .`, `mypy --ignore-missing-imports
--follow-imports=silent .`, and `pytest --cov=prahari --cov=agent
--cov-fail-under=45`. CI also builds and scans the application container.

### Koyeb deployment

Set `DEPLOYMENT_PROVIDER=koyeb`, `KOYEB_API_TOKEN`, and the staging and
production service IDs in `.env`. Create services from the Koyeb dashboard using
this repository's Dockerfile, expose the service port, and configure `/health`
as the health-check path. The free Koyeb instance is suitable for one demo web
service, not the always-on detector worker.

Prahari also exposes Koyeb's public platform health at
`GET /api/platform-status/koyeb`; it is credential-free and can be used as
evidence when an incident may be caused by a hosting-provider outage.

## Layout

```text
target_app/   Sample service
faults/       Reversible incident scenarios
traffic/      Load and traffic replay
detector/     Alert polling and schemas
agent/        On-call investigation and repair loop
verifier/     Tests and replay verification
incidents/    Incident-memory documents
dashboard/    Operator dashboard
```
