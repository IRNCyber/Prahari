# Prahari

Prahari is an AI on-call engineer demo: it detects a sample-service incident,
investigates it, prepares a branch-only fix, verifies the result, and asks a
human to approve the outcome.

## Quickstart

1. Create and activate a Python 3.12+ virtual environment.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Start both services: `docker compose up --build`.
4. Open `http://localhost:8080` and inject an incident.
5. Click **Investigate**, then **Heal** and **Investigate** again to see green verification.

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

## Safety

- Fault injection is restricted to the local sample service.
- Proposed fixes are written to `artifacts/proposed_fix.diff`; the default branch is never changed.
- A report is only green when the test suite, regression condition, and healthy replay state pass.
- Real Datadog, Sentry, GitHub, PagerDuty, and production deployment are deliberately out of scope.

## Operations

Runtime state and audit events are stored in SQLite under `data/prahari.db` (or
`PRAHARI_DATA_DIR`). Docker Compose mounts a shared named volume at `/data` so
the service, dashboard, and detector use the same incident state.

Every control action, test result, patch proposal, escalation, approval, and
postmortem is recorded in the audit log. View recent events through
`GET /api/incidents` on the dashboard service.

The project includes connector contracts for production telemetry, logging,
deployment, and notifications in `agent/adapters.py`; supply organisation-specific
implementations and credentials outside the demo repository.

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
