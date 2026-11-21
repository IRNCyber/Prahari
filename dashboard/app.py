from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from agent.loop import run
from agent.reporter import create_pr
from faults.scenarios import heal, inject
from target_app.state import read_state
from verifier.report import verify
from prahari.policy import allow_approval
from prahari.store import audit, recent_audit
from prahari.auth import authorise_approval, provider_status
from prahari.observability import otel_status
from agent.integrations.deployment import DeploymentClient
from agent.integrations.notifications import SlackNotifier, TelegramNotifier
from agent.integrations.postgres import postgres_configured
from agent.integrations.sentry import SentryClient

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Prahari Dashboard")

PAGE = """<!doctype html><html><head><title>Prahari</title><style>body{font-family:system-ui;background:#07121f;color:#e5eef8;max-width:960px;margin:40px auto}button{padding:9px 14px;margin:4px;background:#0f766e;color:white;border:0;border-radius:5px}pre{background:#0d1b2a;padding:16px;white-space:pre-wrap;border-radius:8px}</style></head><body><h1>Prahari <small>AI On-Call Engineer</small></h1><p id='state'>Loading system status...</p><div><button onclick=action('bad_deploy')>Inject bad deploy</button><button onclick=action('config')>Inject DB pool fault</button><button onclick=action('slow_query')>Inject slow query</button><button onclick=action('dep_outage')>Inject provider outage</button><button onclick=action('heal')>Heal</button><button onclick=investigate()>Investigate</button><button onclick=approve()>Approve PR</button></div><h2>Incident timeline</h2><pre id='trace'>No incident run yet.</pre><h2>Verification</h2><pre id='verification'>Run after healing.</pre><script>async function refresh(){let s=await fetch('/api/state').then(r=>r.json());document.querySelector('#state').textContent='Active scenario: '+(s.scenario||'healthy')}async function action(name){await fetch('/api/control/'+name,{method:'POST'});refresh()}async function investigate(){let r=await fetch('/api/investigate',{method:'POST'}).then(r=>r.json());document.querySelector('#trace').textContent=JSON.stringify(r,null,2);let v=await fetch('/api/verify',{method:'POST'}).then(r=>r.json());document.querySelector('#verification').textContent=JSON.stringify(v,null,2)}async function approve(){let r=await fetch('/api/approve',{method:'POST'}).then(r=>r.json());document.querySelector('#verification').textContent=JSON.stringify(r,null,2)}refresh()</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/api/state")
def state() -> dict[str, object]:
    return read_state()


@app.get("/api/incidents")
def incidents() -> list[dict[str, object]]:
    return recent_audit()


@app.get("/api/integrations")
def integrations() -> dict[str, object]:
    return {
        "sentry": SentryClient().configured(),
        "slack": SlackNotifier().configured(),
        "telegram": TelegramNotifier().configured(),
        "postgres": postgres_configured(),
        "deployment": DeploymentClient().readiness(),
        "auth": provider_status(),
        "otel": otel_status(),
    }


@app.post("/api/control/{scenario}")
def control(scenario: str) -> dict[str, object]:
    result = heal() if scenario == "heal" else inject(scenario)
    audit("dashboard_control", {"scenario": scenario}, actor="demo-operator")
    return result


@app.post("/api/investigate")
def investigate() -> dict[str, object]:
    return run()


@app.post("/api/verify")
def verification() -> dict[str, object]:
    return verify().to_dict()


@app.post("/api/approve")
def approve(approver: str = "demo-operator", x_prahari_approver_token: str | None = Header(default=None)) -> dict[str, object]:
    if not authorise_approval(x_prahari_approver_token):
        raise HTTPException(status_code=401, detail="A valid approver token is required.")
    report = verify().to_dict()
    decision = allow_approval(bool(report["passed"]), approver)
    if not decision.allowed:
        return {"approved": False, "reason": decision.reason, "verification": report}
    result = {"approved": True, "pr": create_pr("Local incident healed and verified.", report)}
    audit("approval_granted", {"approver": approver}, actor=approver)
    return result


@app.get("/events")
async def events() -> StreamingResponse:
    async def stream():
        while True:
            trace = ROOT / "artifacts" / "incident_trace.json"
            data = trace.read_text(encoding="utf-8") if trace.exists() else json.dumps({"status": "idle"})
            yield f"data: {data}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream")
