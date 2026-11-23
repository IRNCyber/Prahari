from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.integrations.datadog import DatadogConfig
from agent.integrations.deployment import DeploymentClient
from agent.integrations.koyeb import platform_status
from agent.integrations.loki import LokiClient
from agent.integrations.notifications import (
    PagerDutyNotifier,
    SlackNotifier,
    TelegramNotifier,
)
from agent.integrations.postgres import postgres_configured
from agent.integrations.sentry import SentryClient
from agent.loop import run
from agent.reporter import create_pr
from ci.webhook_handler import handle_github_webhook, handle_gitlab_webhook
from deps.health import check_dependencies
from faults.scenarios import heal, inject
from prahari.auth import authorise_approval, provider_status, require_role
from prahari.observability import otel_status
from prahari.policy import allow_approval
from prahari.runtime import configure_runtime
from prahari.store import (
    audit,
    create_signed_approval,
    latest_tool_call,
    latest_verification,
    recent_alerts,
    recent_audit,
)
from slo.service import evaluate_slo
from target_app.state import read_state
from verifier.report import verify

ROOT = Path(__file__).resolve().parents[1]
configure_runtime("prahari-dashboard")
operator_auth = Depends(require_role("operator"))
approver_auth = Depends(require_role("approver"))
app = FastAPI(title="Prahari Dashboard")


class ApprovalRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prahari | On-call console</title>
<style>
:root { color-scheme: dark; --bg:#070b12; --panel:#101820; --line:#243140; --text:#e8eef6; --muted:#9aafc4; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin:0; color:var(--text); font:15px/1.5 ui-sans-serif, system-ui, sans-serif;
  background: radial-gradient(900px 260px at 8% -10%, rgba(15,118,110,.2), transparent 60%), var(--bg); }
.top { position:sticky; top:0; z-index:10; backdrop-filter:blur(12px); background:rgba(7,11,18,.9); border-bottom:1px solid var(--line); }
.top-inner, main { max-width:1120px; margin:0 auto; padding:14px 20px; }
.top-inner, .top-meta, .brand, .panel-head, .auth-row, .trace-title, .timeline summary { display:flex; align-items:center; gap:12px; }
.top-inner, .panel-head, .trace-title, .timeline summary { justify-content:space-between; }
.brand h1 { margin:0; font-size:18px; letter-spacing:-.02em; }
.brand p, .note, .empty p, .trace-title time, .timeline .muted { margin:0; color:var(--muted); }
.mark { width:28px; height:28px; border-radius:8px; background:#0f766e; position:relative; flex:none; }
.mark:before { content:""; position:absolute; width:8px; height:8px; border-radius:50%; background:#ccfbf1; top:10px; left:10px; }
main { padding-top:18px; padding-bottom:56px; }
main > * + * { margin-top:14px; }
.banner, .panel { background:var(--panel); border:1px solid var(--line); border-radius:16px; }
.banner { display:flex; justify-content:space-between; gap:18px; align-items:flex-end; padding:18px 20px; }
.banner.is-healthy { background:#0d1c1a; border-color:#14584f; }
.banner.is-incident { background:#1c140c; border-color:#7c4a12; }
.banner.is-escalated { background:#1a160c; border-color:#854d0e; }
.kicker { margin:0; font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
.banner h2 { margin:4px 0; font-size:clamp(22px, 3vw, 30px); letter-spacing:-.03em; line-height:1.15; }
.steps { display:flex; gap:8px; list-style:none; padding:0; margin:0; flex-wrap:wrap; }
.steps li { font-size:12px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:6px 10px; }
.steps li.is-current { color:var(--text); border-color:#2dd4bf; background:#102824; }
.steps li.is-done { color:#99f6e4; border-color:#115e59; }
.steps li.is-skipped { opacity:.45; }
.panel { padding:16px 18px; }
.panel h2, .panel-head h2 { margin:0; font-size:16px; font-weight:650; }
.panel > h2 { margin-bottom:12px; }
.scenarios { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
button { font:inherit; color:white; background:#24364a; border:1px solid transparent; border-radius:8px; padding:10px 14px; min-height:40px; cursor:pointer; }
button.primary { background:#0f766e; }
button.primary.is-ready { box-shadow:0 0 0 3px rgba(45,212,191,.28); }
button.ghost { background:transparent; color:var(--text); border-color:var(--line); }
button:disabled { opacity:.45; cursor:not-allowed; }
button:focus-visible, summary:focus-visible, input:focus-visible { outline:2px solid #5eead4; outline-offset:2px; }
button.scenario { display:block; width:100%; text-align:left; background:#0c141d; color:inherit; border:1px solid var(--line); min-height:0; padding:14px; }
button.scenario strong { display:block; font-size:14px; }
button.scenario .desc { display:block; margin-top:4px; color:var(--muted); font-size:13px; }
button.scenario.is-active { border-color:#b45309; background:#1c140c; }
.badge { margin-left:8px; font-size:11px; font-weight:650; letter-spacing:.04em; text-transform:uppercase; color:#fde68a; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }
.activity { margin:12px 0 0; color:#99f6e4; }
.load-error { margin:0; color:#fca5a5; }
.split { display:grid; grid-template-columns:1.15fr .85fr; gap:14px; align-items:start; }
.quad { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.pill { border-radius:999px; padding:4px 10px; font-size:12px; border:1px solid var(--line); color:var(--muted); }
.pill.good, .good { color:#99f6e4; }
.pill.good { border-color:#115e59; background:#0c2422; }
.pill.bad, .bad { color:#fecaca; }
.pill.bad { border-color:#7f1d1d; background:#2a1214; }
.pill.warn { color:#fde68a; border-color:#854d0e; background:#2a2110; }
.empty strong { display:block; }
.diagnosis { margin:0 0 12px; padding:10px 12px; border-radius:10px; background:#0c141d; }
.trace-list, .rows, .gates, .timeline { list-style:none; margin:0; padding:0; display:grid; gap:10px; }
.trace-list li { display:grid; grid-template-columns:28px 1fr; gap:10px; }
.seq { width:28px; height:28px; border-radius:50%; display:grid; place-items:center; background:#10202c; color:var(--muted); font-size:12px; }
.trace-list p { margin:4px 0 0; }
.rows li, .gate { display:flex; gap:10px; align-items:flex-start; }
.gate { align-items:center; padding:8px 10px; border-radius:8px; background:#0c141d; }
.gate strong { margin-left:auto; font-size:13px; }
.dot { width:8px; height:8px; margin-top:6px; border-radius:50%; background:var(--muted); flex:none; }
.gate .dot { margin-top:0; }
.ok .dot { background:#2dd4bf; }
.bad .dot, .meter.bad strong { background:#f87171; color:#fca5a5; }
.meter.bad strong { background:transparent; }
.sev { font-size:11px; text-transform:uppercase; letter-spacing:.04em; border-radius:999px; padding:3px 7px; border:1px solid var(--line); color:var(--muted); }
.sev-high, .sev-critical { color:#fecaca; border-color:#7f1d1d; }
.sev-medium, .sev-warning { color:#fde68a; border-color:#854d0e; }
.meters { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.meter { background:#0c141d; border-radius:10px; padding:12px; }
.meter strong { display:block; font-size:22px; margin:4px 0; letter-spacing:-.03em; }
.meter-label { color:var(--muted); font-size:12px; }
.chips { display:flex; flex-wrap:wrap; gap:8px; }
.chip { border:1px solid var(--line); border-radius:999px; padding:6px 10px; font-size:13px; color:var(--muted); }
.chip.ready { color:#99f6e4; border-color:#115e59; }
.chip b { color:var(--text); font-weight:650; margin-right:6px; }
.timeline details { border-top:1px solid var(--line); padding-top:8px; }
.timeline summary { cursor:pointer; }
pre.raw, .diff { margin:8px 0 0; max-height:240px; overflow:auto; background:#090f16; padding:10px 12px; border-radius:8px; color:#c5d4e4; font:12px/1.5 ui-monospace, Consolas, monospace; white-space:pre-wrap; }
.diff { max-height:420px; margin:0; }
.diff .add { color:#86efac; }
.diff .del { color:#fca5a5; }
.diff .hunk { color:#93c5fd; }
.approve, .fields { display:grid; gap:8px; margin-top:12px; }
.approve { padding:12px; border:1px solid var(--line); border-radius:10px; background:#0c141d; }
label { font-size:13px; color:var(--muted); display:grid; gap:6px; }
input { width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--line); background:#0a121c; color:var(--text); font:inherit; }
details.creds summary { cursor:pointer; font-weight:650; }
.toast { position:fixed; left:50%; bottom:18px; transform:translateX(-50%) translateY(12px); background:#132033; color:white; border:1px solid var(--line); border-radius:10px; padding:10px 14px; opacity:0; pointer-events:none; z-index:20; max-width:min(520px, calc(100% - 24px)); }
.toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
.toast.bad { border-color:#7f1d1d; }
@media (hover:hover) { button:hover:not(:disabled) { filter:brightness(1.08); } }
@media (max-width: 800px) {
  .split, .quad, .scenarios, .banner { grid-template-columns:1fr; }
  .banner { flex-direction:column; align-items:flex-start; }
  .toast { top:68px; bottom:auto; }
  .actions { position:sticky; bottom:0; z-index:8; padding:10px 0 12px; background:rgba(7,11,18,.94); }
}
@media (prefers-reduced-motion: reduce) { .toast { transition:none; } }
</style>
</head>
<body>
<div id="toast" class="toast" role="status"></div>
<header class="top">
  <div class="top-inner">
    <div class="brand">
      <span class="mark" aria-hidden="true"></span>
      <div><h1>Prahari</h1><p>On-call console</p></div>
    </div>
    <div class="top-meta">
      <span id="health" class="pill">Connecting</span>
      <span id="connection" class="pill" role="status" aria-live="polite">Connecting</span>
      <span id="updated" class="note"></span>
      <button id="refresh-btn" class="ghost" type="button">Refresh</button>
    </div>
  </div>
</header>
<main>
  <section id="banner" class="banner" aria-live="polite">
    <div>
      <p id="banner-kicker" class="kicker">Status</p>
      <h2 id="banner-title">Checking the service…</h2>
      <p id="banner-hint" class="note">Loading incident state.</p>
    </div>
    <ol id="steps" class="steps">
      <li data-step="1">1 Inject</li>
      <li data-step="2">2 Investigate</li>
      <li data-step="3">3 Verify</li>
      <li data-step="4">4 Approve</li>
    </ol>
  </section>
  <section class="panel">
    <div class="panel-head">
      <h2>Run an incident</h2>
    </div>
    <div class="scenarios">
      <button type="button" class="scenario" data-scenario="bad_deploy" data-banner="Bad deploy is active" data-hint="Checkout is failing. Investigate to collect metrics, logs, and the latest deploy.">
        <strong>Bad deploy <span class="badge" hidden>Active</span></strong>
        <span class="desc">Checkout fails after a release that sends a null discount code.</span>
      </button>
      <button type="button" class="scenario" data-scenario="config" data-banner="The database pool is saturated" data-hint="Latency is coming from pool waits. Investigate before you decide on a fix.">
        <strong>DB pool saturation <span class="badge" hidden>Active</span></strong>
        <span class="desc">Requests stall because the connection pool is exhausted.</span>
      </button>
      <button type="button" class="scenario" data-scenario="slow_query" data-banner="Checkout queries are slow" data-hint="p95 latency should breach the SLO. Investigate to confirm the slow lookup.">
        <strong>Slow query <span class="badge" hidden>Active</span></strong>
        <span class="desc">Product lookup latency climbs past the SLO.</span>
      </button>
      <button type="button" class="scenario" data-scenario="dep_outage" data-banner="The payment provider is down" data-hint="Expect an escalation, not a code fix. Provider outages are not patched locally.">
        <strong>Provider outage <span class="badge" hidden>Active</span></strong>
        <span class="desc">Payments return 503. Prahari should escalate instead of patching.</span>
      </button>
    </div>
    <div class="actions">
      <button id="heal-btn" class="ghost" type="button">Heal</button>
      <button id="investigate-btn" class="primary" type="button">Investigate</button>
      <button id="verify-btn" type="button">Verify</button>
      <button id="approve-toggle" class="ghost" type="button" aria-expanded="false" aria-controls="approve-form">Approve</button>
    </div>
    <p id="control-activity" class="activity" hidden></p>
    <form id="approve-form" class="approve" hidden>
      <label>Reason<input id="approval-reason" maxlength="1000" value="Verified fix is ready for human review"></label>
      <label>Approver token<input id="approval-token" type="password" autocomplete="off" placeholder="PRAHARI_APPROVER_TOKEN"></label>
      <div class="auth-row"><button id="approve-btn" class="primary" type="submit">Approve verified change</button></div>
    </form>
    <p class="note">Faults stay on the local sample service. Approval records a decision and does not deploy it.</p>
  </section>
  <div class="split">
    <section class="panel" aria-labelledby="trace-heading">
      <div class="panel-head"><h2 id="trace-heading">Investigation</h2><span id="trace-status" class="pill">Waiting</span></div>
      <p id="trace-activity" class="activity" hidden></p>
      <div id="trace"><div class="empty"><strong>No investigation yet</strong><p>Inject a fault, then run Investigate.</p></div></div>
    </section>
    <section class="panel" aria-labelledby="verify-heading">
      <div class="panel-head"><h2 id="verify-heading">Verification</h2></div>
      <p id="verify-activity" class="activity" hidden></p>
      <div id="verification"><div class="empty"><strong>No report yet</strong><p>Verify checks the suite, the regression, and a traffic replay.</p></div></div>
    </section>
  </div>
  <section class="panel">
    <div class="panel-head"><h2>Proposed change</h2><button id="copy-diff" class="ghost" type="button" hidden>Copy diff</button></div>
    <div id="patch"><div class="empty"><strong>No proposed change</strong><p>A diff shows up here when the agent prepares a branch-only fix.</p></div></div>
  </section>
  <div class="quad">
    <section class="panel"><h2>Alerts</h2><div id="alerts"><p class="note">Loading…</p></div></section>
    <section class="panel"><h2>Service level</h2><div id="slo"><p class="note">Loading…</p></div></section>
    <section class="panel"><h2>Integrations</h2><div id="integrations"><p class="note">Loading…</p></div></section>
    <section class="panel"><h2>Dependencies</h2><div id="dependencies"><p class="note">Loading…</p></div></section>
  </div>
  <section class="panel"><h2>Audit</h2><div id="timeline"><p class="note">Loading…</p></div></section>
  <details class="panel creds">
    <summary>Operator credentials</summary>
    <p class="note">Local mode signs you in as the operator. Paste an Auth0 access token only when AUTH_PROVIDER=auth0. Tokens stay in this tab.</p>
    <div class="fields">
      <label>Access token<input id="access-token" type="password" autocomplete="off" placeholder="Bearer token"></label>
      <div class="auth-row"><button id="connect-btn" type="button">Connect</button><span id="auth-status" class="note"></span></div>
    </div>
  </details>
</main>
<script>
const TOKEN_KEY = 'prahari.access';
const APPROVER_KEY = 'prahari.approver';
const cache = {state:null, audit:[], alerts:[], slo:null, integrations:null, dependencies:null, verification:null, patch:null, trace:null};
const snapshots = {};
const openAudit = new Set();
let auditLimit = 8;
let working = false;
let refreshing = false;
let online = true;
let ready = false;
let lastDiff = '';
let toastTimer = 0;

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value == null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = String(value);
      else if (key === 'hidden') node.hidden = Boolean(value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
  }
  for (const child of children) append(node, child);
  return node;
}
function append(node, child) {
  if (child == null || child === false) return;
  if (Array.isArray(child)) { child.forEach(item => append(node, item)); return; }
  node.append(child.nodeType ? child : document.createTextNode(String(child)));
}
function empty(title, body) {
  return h('div', {class:'empty'}, h('strong', {text:title}), h('p', {text:body}));
}
function labelize(name) { return String(name || '').replaceAll('_', ' '); }
function cleanText(value) {
  let text = String(value ?? '').trim();
  if (text.startsWith("['") && text.endsWith("']")) text = text.slice(2, -2);
  return text;
}
function parseDate(iso) {
  if (!iso) return null;
  const text = String(iso);
  const hasZone = text.endsWith('Z') || text.includes('+') || text.slice(10).includes('-');
  const date = new Date(hasZone ? text : text + 'Z');
  return Number.isNaN(date.getTime()) ? null : date;
}
function ago(iso) {
  const date = parseDate(iso);
  if (!date) return '';
  const seconds = (Date.now() - date.getTime()) / 1000;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
  return date.toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
}
function rawText(value) {
  const text = JSON.stringify(value, null, 2) || '';
  return text.length > 4000 ? text.slice(0, 4000) + '…' : text;
}
function toast(message, kind) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = 'toast show' + (kind ? ' ' + kind : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 4800);
}
function headers() { return {'Content-Type':'application/json'}; }
async function api(url, options={}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({detail: response.statusText}));
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg || 'Invalid request').join(' ') : response.statusText;
    throw Error(message || 'Request failed');
  }
  return body;
}
function metaFor(id) {
  const button = document.querySelector('[data-scenario="' + id + '"]');
  if (!button) return null;
  return {id, name: button.querySelector('strong').childNodes[0].textContent.trim(), banner: button.dataset.banner, hint: button.dataset.hint};
}
function faultChangedAt() {
  const match = (cache.audit || []).find(event => event.event_type === 'fault_state_changed');
  return match ? Date.parse(match.created_at) || 0 : 0;
}
function traceTime(trace) {
  const steps = trace && Array.isArray(trace.trace) ? trace.trace : [];
  const last = steps.length ? steps[steps.length - 1] : null;
  return last ? Date.parse(last.time) || 0 : 0;
}
function traceIsCurrent(trace) {
  if (!trace || !trace.status || trace.status === 'idle') return false;
  if (!cache.state || !cache.state.scenario) return true;
  const at = traceTime(trace);
  return at === 0 || at >= faultChangedAt() - 2000;
}
function verificationIsCurrent() {
  const report = cache.verification;
  if (!report) return false;
  if (!report.created_at || !cache.state || !cache.state.scenario) return true;
  const at = Date.parse(report.created_at || '');
  return Boolean(at) && at >= faultChangedAt() - 2000;
}
function recentlyApproved() {
  if (!verificationIsCurrent() || !cache.verification || cache.verification.passed !== true) return false;
  const at = Date.parse(cache.verification.created_at || '');
  if (!at) return false;
  return (cache.audit || []).some(event => event.event_type === 'approval_granted' && (Date.parse(event.created_at) || 0) >= at);
}
function currentStep() {
  if (!cache.state || !cache.state.scenario) return 1;
  if (recentlyApproved()) return 5;
  if (verificationIsCurrent() && cache.verification.passed) return 4;
  if (traceIsCurrent(cache.trace) && cache.trace.status !== 'no_incident') return 3;
  return 2;
}
function renderSteps(step, escalated) {
  document.querySelectorAll('#steps li').forEach(item => {
    const n = Number(item.dataset.step);
    item.classList.toggle('is-done', escalated ? n < 3 : n < step);
    item.classList.toggle('is-current', !escalated && n === step && step < 5);
    item.classList.toggle('is-skipped', Boolean(escalated && n >= 3));
  });
}
function renderBanner() {
  const scenario = cache.state && cache.state.scenario;
  const meta = scenario ? metaFor(scenario) : null;
  const escalated = traceIsCurrent(cache.trace) && cache.trace.status === 'escalated';
  const banner = document.getElementById('banner');
  banner.className = 'banner ' + (!scenario ? 'is-healthy' : escalated ? 'is-escalated' : 'is-incident');
  document.getElementById('banner-kicker').textContent = scenario ? (escalated ? 'Escalated' : 'Incident') : 'Healthy';
  document.getElementById('banner-title').textContent = meta ? meta.banner : 'Checkout is healthy';
  let hint = 'The sample checkout service is healthy. Inject a fault to walk through an incident.';
  if (meta && recentlyApproved()) hint = 'A human approved the verified change. Prahari does not deploy it.';
  else if (meta && verificationIsCurrent() && cache.verification.passed) hint = 'Verification passed. Approve the change if you accept it.';
  else if (meta && verificationIsCurrent() && cache.verification.passed === false) hint = 'Verification did not pass. Read the gates before you approve anything.';
  else if (meta && escalated) hint = 'Prahari escalated this incident. Review the evidence, then heal the sample service.';
  else if (meta && traceIsCurrent(cache.trace) && cache.trace.status === 'needs_llm') hint = 'Evidence is collected. No model key is configured, so Prahari did not write a patch.';
  else if (meta) hint = meta.hint;
  document.getElementById('banner-hint').textContent = hint;
  document.title = (meta ? meta.name : 'Healthy') + ' · Prahari';
  const pill = document.getElementById('health');
  pill.textContent = meta ? meta.name : 'Healthy';
  pill.className = 'pill ' + (!scenario ? 'good' : escalated ? 'warn' : 'bad');
  renderSteps(currentStep(), escalated);
  renderControls();
}
function renderControls() {
  const scenario = cache.state && cache.state.scenario;
  document.querySelectorAll('[data-scenario]').forEach(button => {
    const active = button.dataset.scenario === scenario;
    button.classList.toggle('is-active', active);
    button.disabled = working;
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    const badge = button.querySelector('.badge');
    if (badge) badge.hidden = !active;
  });
  document.getElementById('heal-btn').disabled = working || !scenario;
  document.getElementById('investigate-btn').disabled = working;
  document.getElementById('investigate-btn').classList.toggle('is-ready', !working && currentStep() === 2);
  document.getElementById('verify-btn').disabled = working;
  document.getElementById('approve-toggle').disabled = working;
}
function clusterText(clusters) {
  if (!Array.isArray(clusters) || !clusters.length) return 'No error clusters';
  return clusters.slice(0, 3).map(item => {
    if (typeof item === 'string') return item;
    if (item && typeof item === 'object') {
      const bits = [item.route, item.status, item.error || item.message || item.detail].filter(Boolean);
      return bits.length ? bits.join(' ') : JSON.stringify(item);
    }
    return String(item);
  }).join(' · ');
}
function summarize(step) {
  const result = step.result || {};
  if (step.tool === 'query_metrics' && result.values) {
    const values = result.values;
    const rate = typeof values.error_rate === 'number' ? Math.round(values.error_rate * 100) + '% error' : 'error —';
    const p95 = typeof values.p95_latency_ms === 'number' ? Math.round(values.p95_latency_ms) + ' ms p95' : 'p95 —';
    return rate + ' · ' + p95 + ' · db ' + (values.db_connections ?? '—');
  }
  if (step.tool === 'query_logs') return clusterText(result.clusters);
  if (step.tool === 'get_recent_deploys' && Array.isArray(result.deploys)) {
    if (!result.deploys.length) return 'No recent deploys';
    const latest = result.deploys[0];
    return result.deploys.length + ' deploys · latest ' + [latest.environment, latest.state, latest.revision].filter(Boolean).join(' ');
  }
  if (step.tool === 'search_code') {
    const count = Array.isArray(result.matches) ? result.matches.length : 0;
    return 'Pattern ' + (result.pattern || '') + ' · ' + count + (count === 1 ? ' match' : ' matches');
  }
  if (step.tool === 'search_past_incidents') {
    const names = Array.isArray(result.matches) ? result.matches : [];
    return names.length ? names.join(', ') : 'No matching incident notes';
  }
  if (step.tool === 'escalate') return cleanText(result.reason || 'Escalated to a human');
  if (step.tool === 'propose_patch') return result.applied === false ? (result.reason || 'Patch was not applied') : ('Patch proposed for ' + (result.path || 'the sample service'));
  if (typeof result.reason === 'string') return cleanText(result.reason);
  if (result.error) return String(result.error);
  return '';
}
function statusLabel(status) {
  const labels = {idle:'Waiting', no_incident:'No incident', escalated:'Escalated', needs_llm:'Evidence only'};
  return labels[status] || labelize(status || 'Waiting');
}
function renderTrace(trace) {
  const key = JSON.stringify(trace);
  if (snapshots.trace === key) { if (ready) renderBanner(); return; }
  snapshots.trace = key;
  const root = document.getElementById('trace');
  const pill = document.getElementById('trace-status');
  root.replaceChildren();
  const status = trace && trace.status;
  pill.textContent = statusLabel(status);
  pill.className = 'pill ' + (status === 'escalated' || status === 'needs_llm' ? 'warn' : status === 'no_incident' || !status || status === 'idle' ? '' : 'bad');
  if (!trace || status === 'idle') {
    root.append(empty('No investigation yet', 'Inject a fault, then run Investigate.'));
    if (ready) renderBanner();
    return;
  }
  if (cache.state && cache.state.scenario && !traceIsCurrent(trace)) root.append(h('p', {class:'note', text:'This is from an earlier investigation.'}));
  else if (cache.state && !cache.state.scenario && status !== 'no_incident') root.append(h('p', {class:'note', text:'Last investigation. The service is healthy now.'}));
  if (trace.diagnosis) root.append(h('p', {class:'diagnosis', text:cleanText(trace.diagnosis)}));
  if (trace.summary) root.append(h('p', {class:'note', text:cleanText(trace.summary)}));
  const steps = Array.isArray(trace.trace) ? trace.trace : [];
  if (!steps.length) root.append(empty('No tool calls', 'The investigation did not record any tool calls.'));
  else {
    const list = h('ol', {class:'trace-list'});
    steps.forEach((step, index) => {
      const summary = summarize(step);
      const body = h('div', {},
        h('div', {class:'trace-title'}, h('strong', {text:labelize(step.tool)}), h('time', {text:ago(step.time)}))
      );
      if (summary) body.append(h('p', {text:summary}));
      const details = h('details');
      details.append(h('summary', {text:'Raw result'}), h('pre', {class:'raw', text:rawText(step.result)}));
      body.append(details);
      list.append(h('li', {}, h('span', {class:'seq', text:String(index + 1)}), body));
    });
    root.append(list);
  }
  if (ready) renderBanner();
}
function gate(label, value) {
  const known = typeof value === 'boolean';
  const word = !known ? 'Unknown' : value ? 'Pass' : 'Fail';
  return h('li', {class:'gate ' + (!known ? '' : value ? 'ok' : 'bad')}, h('span', {class:'dot'}), h('span', {text:label}), h('strong', {text:word}));
}
function renderVerification(report) {
  const root = document.getElementById('verification');
  root.replaceChildren();
  if (!report) {
    root.append(empty('No report yet', 'Verify checks the suite, the regression, and a traffic replay.'));
    return;
  }
  const current = verificationIsCurrent();
  const passed = report.passed === true;
  root.append(h('p', {class:'verdict ' + (passed ? 'good' : 'bad'), text:(current ? '' : 'Previous report · ') + (passed ? 'All gates passed' : 'Verification failed')}));
  root.append(h('ul', {class:'gates'}, gate('Test suite', report.suite_green), gate('Regression', report.regression_proven), gate('Traffic replay', report.replay_baseline)));
  if (Array.isArray(report.details) && report.details.length) {
    const details = h('details');
    details.append(h('summary', {text:'Technical details'}));
    report.details.forEach(line => details.append(h('p', {class:'note', text:String(line)})));
    root.append(details);
  }
  if (report.created_at) root.append(h('p', {class:'note', text:ago(report.created_at)}));
}
function renderPatch(patch) {
  const root = document.getElementById('patch');
  const copy = document.getElementById('copy-diff');
  root.replaceChildren();
  const diff = patch && patch.diff;
  if (!diff) {
    copy.hidden = true;
    lastDiff = '';
    root.append(empty('No proposed change', 'A diff shows up here when the agent prepares a branch-only fix.'));
    return;
  }
  lastDiff = diff;
  copy.hidden = false;
  const view = h('div', {class:'diff'});
  diff.split('\\n').forEach(line => {
    let cls = '';
    if (line.startsWith('@@')) cls = 'hunk';
    else if (line.startsWith('+') && !line.startsWith('+++')) cls = 'add';
    else if (line.startsWith('-') && !line.startsWith('---')) cls = 'del';
    view.append(h('div', {class:cls, text:line || ' '}));
  });
  root.append(view);
}
function renderAlerts(alerts) {
  const root = document.getElementById('alerts');
  root.replaceChildren();
  if (!alerts || !alerts.length) {
    root.append(empty('No alerts', 'SLO breaches and detector findings show up here.'));
    return;
  }
  const list = h('ul', {class:'rows'});
  alerts.slice(0, 8).forEach(alert => {
    list.append(h('li', {},
      h('span', {class:'sev sev-' + (alert.severity || 'info'), text:alert.severity || 'info'}),
      h('div', {}, h('strong', {text:alert.summary || alert.fingerprint || 'Alert'}), h('span', {class:'note', text:[alert.status, ago(alert.last_seen_at)].filter(Boolean).join(' · ')}))
    ));
  });
  root.append(list);
}
function renderSlo(slo) {
  const root = document.getElementById('slo');
  root.replaceChildren();
  if (!slo) {
    root.append(empty('No sample yet', 'SLO status appears after the target service answers /metrics.'));
    return;
  }
  const rate = typeof slo.error_rate === 'number' ? (slo.error_rate * 100).toFixed(1) + '%' : '—';
  const p95 = typeof slo.p95_latency_ms === 'number' ? Math.round(slo.p95_latency_ms) + ' ms' : '—';
  const budget = typeof slo.error_budget_remaining === 'number' ? Math.round(slo.error_budget_remaining * 100) + '% budget left' : '';
  const violations = Array.isArray(slo.violations) ? slo.violations : [];
  root.append(h('div', {class:'meters'},
    h('div', {class:'meter' + (violations.some(item => item.slo === 'error_rate') ? ' bad' : '')}, h('span', {class:'meter-label', text:'Error rate'}), h('strong', {text:rate}), h('span', {class:'note', text:budget})),
    h('div', {class:'meter' + (violations.some(item => item.slo === 'p95_latency_ms') ? ' bad' : '')}, h('span', {class:'meter-label', text:'p95 latency'}), h('strong', {text:p95}), h('span', {class:'note', text:slo.latency_target_ms ? 'target ' + slo.latency_target_ms + ' ms' : ''}))
  ));
  root.append(h('p', {class:'note', text:slo.healthy ? (slo.request_count || 0) + ' requests in the window' : 'An SLO is outside its threshold'}));
}
function renderIntegrations(data) {
  const root = document.getElementById('integrations');
  const wrap = h('div', {class:'chips'});
  for (const [key, value] of Object.entries(data || {})) {
    let ready = false;
    let detail = 'off';
    if (typeof value === 'boolean') { ready = value; detail = value ? 'ready' : 'off'; }
    else if (value && typeof value === 'object') {
      if (key === 'auth') {
        const provider = String(value.provider || 'local');
        const local = provider === 'none' || provider === 'local-token' || provider === 'local';
        ready = local || Boolean(value.issuer_configured && value.audience_configured);
        detail = local ? 'local' : provider;
      } else {
        ready = Boolean(value.enabled || value.configured);
        detail = value.provider ? String(value.provider) : (ready ? 'ready' : 'off');
      }
    }
    wrap.append(h('span', {class:'chip' + (ready ? ' ready' : '')}, h('b', {text:labelize(key)}), detail));
  }
  root.replaceChildren(wrap);
}
function renderDependencies(data) {
  const root = document.getElementById('dependencies');
  const items = data && Array.isArray(data.dependencies) ? data.dependencies : [];
  root.replaceChildren();
  if (!items.length) {
    root.append(empty('None configured', 'Dependency probes appear here when deps.yml lists them.'));
    return;
  }
  const list = h('ul', {class:'rows'});
  items.forEach(item => {
    list.append(h('li', {class:item.healthy ? 'ok' : 'bad'},
      h('span', {class:'dot'}),
      h('div', {}, h('strong', {text:item.name}), h('span', {class:'note', text:item.healthy ? 'Healthy' : (item.error || ('HTTP ' + (item.status_code ?? '')))}))
    ));
  });
  root.append(h('p', {class:'note', text:data.healthy ? 'All dependencies responded' : 'A dependency is unhealthy'}));
  root.append(list);
}
function renderAudit(events) {
  const root = document.getElementById('timeline');
  root.replaceChildren();
  if (!events || !events.length) {
    root.append(empty('No events yet', 'Controls, investigations, and approvals are recorded here.'));
    return;
  }
  const list = h('div', {class:'timeline'});
  events.slice(0, auditLimit).forEach(event => {
    const details = h('details');
    if (openAudit.has(event.id)) details.open = true;
    details.addEventListener('toggle', () => { if (details.open) openAudit.add(event.id); else openAudit.delete(event.id); });
    details.append(
      h('summary', {}, h('strong', {text:labelize(event.event_type)}), h('span', {class:'muted', text:[event.actor, ago(event.created_at)].filter(Boolean).join(' · ')})),
      h('pre', {class:'raw', text:rawText(event.payload)})
    );
    list.append(details);
  });
  root.append(list);
  if (events.length > auditLimit) {
    const more = h('button', {class:'ghost', type:'button', text:'Show all ' + events.length + ' events'});
    more.addEventListener('click', () => { auditLimit = events.length; snapshots.audit = ''; renderAudit(events); });
    root.append(more);
  }
}
function renderIfChanged(key, value, render) {
  const next = JSON.stringify(value);
  if (snapshots[key] === next) return;
  snapshots[key] = next;
  render(value);
}
function lockLabel(button, label) {
  if (!button.dataset.idle) button.dataset.idle = button.textContent.trim();
  button.textContent = label;
}
function unlockLabel(button) {
  if (button.dataset.idle) button.textContent = button.dataset.idle;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const resources = [
      {key:'state', path:'/api/state', label:'service state'},
      {key:'audit', path:'/api/incidents', label:'audit timeline', target:'timeline', render:renderAudit},
      {key:'alerts', path:'/api/alerts', label:'alerts', target:'alerts', render:renderAlerts},
      {key:'slo', path:'/api/slo/status', label:'service level', target:'slo', render:renderSlo},
      {key:'integrations', path:'/api/integrations', label:'integrations', target:'integrations', render:renderIntegrations},
      {key:'dependencies', path:'/api/dependencies/health', label:'dependencies', target:'dependencies', render:renderDependencies},
      {key:'verification', path:'/api/verification/latest', label:'verification', target:'verification', render:renderVerification},
      {key:'patch', path:'/api/patch', label:'proposed change', target:'patch', render:renderPatch}
    ];
    const results = await Promise.allSettled(resources.map(resource => api(resource.path)));
    const failures = [];
    let stateError = null;
    results.forEach((result, index) => {
      const resource = resources[index];
      if (result.status === 'fulfilled') {
        cache[resource.key] = result.value;
        if (resource.render) renderIfChanged(resource.key, result.value, resource.render);
        return;
      }
      failures.push(resource.label);
      if (resource.key === 'state') {
        stateError = result.reason;
        return;
      }
      delete snapshots[resource.key];
      document.getElementById(resource.target).replaceChildren(
        h('p', {class:'load-error', role:'status', text:'Unable to load ' + resource.label + ': ' + (result.reason.message || 'request failed')})
      );
    });
    const connection = document.getElementById('connection');
    if (stateError) {
      const wasOnline = online;
      online = false;
      ready = false;
      connection.textContent = 'Offline';
      connection.className = 'pill bad';
      document.getElementById('banner-title').textContent = 'Dashboard is offline';
      document.getElementById('banner-hint').textContent = stateError.message || 'Unable to load service state.';
      if (wasOnline) toast('Dashboard connection lost', 'bad');
      return;
    }
    const wasOnline = online;
    online = true;
    ready = true;
    connection.textContent = failures.length ? 'Partial · ' + failures.length + ' unavailable' : 'Live';
    connection.className = 'pill ' + (failures.length ? 'warn' : 'good');
    document.getElementById('updated').textContent = 'Updated ' + new Date().toLocaleTimeString(undefined, {hour:'2-digit', minute:'2-digit'});
    if (!wasOnline) toast(failures.length ? 'Connection restored; some panels are unavailable' : 'Connection restored');
    renderBanner();
    if (cache.trace) renderTrace(cache.trace);
  } catch (error) {
    const wasOnline = online;
    online = false;
    ready = false;
    const connection = document.getElementById('connection');
    connection.textContent = 'Offline';
    connection.className = 'pill bad';
    document.getElementById('banner-title').textContent = 'Dashboard is offline';
    document.getElementById('banner-hint').textContent = error.message || 'Unable to refresh dashboard data.';
    if (wasOnline) toast(error.message || 'Dashboard is offline', 'bad');
  } finally {
    refreshing = false;
  }
}
async function runControl(name) {
  if (working) return;
  working = true;
  const button = name === 'heal' ? document.getElementById('heal-btn') : document.querySelector('[data-scenario="' + name + '"]');
  if (name === 'heal') lockLabel(button, 'Healing…');
  const activity = document.getElementById('control-activity');
  activity.hidden = false;
  activity.textContent = name === 'heal' ? 'Clearing the fault…' : 'Injecting ' + (metaFor(name) ? metaFor(name).name : 'fault') + '…';
  renderControls();
  try {
    await api('/api/control/' + name, {method:'POST'});
    toast(name === 'heal' ? 'Fault cleared' : (metaFor(name) ? metaFor(name).name + ' injected' : 'Updated'));
    await refresh();
  } catch (error) {
    toast(error.message || 'Request failed', 'bad');
  } finally {
    working = false;
    if (name === 'heal') unlockLabel(button);
    activity.hidden = true;
    renderControls();
  }
}
async function investigate() {
  if (working) return;
  working = true;
  const button = document.getElementById('investigate-btn');
  lockLabel(button, 'Investigating…');
  const note = document.getElementById('trace-activity');
  note.hidden = false;
  note.textContent = 'Reading metrics, logs, and recent deploys…';
  renderControls();
  try {
    cache.trace = await api('/api/investigate', {method:'POST'});
    snapshots.trace = '';
    renderTrace(cache.trace);
    const status = cache.trace && cache.trace.status;
    toast(status === 'escalated' ? 'Incident escalated' : status === 'no_incident' ? 'No active incident' : 'Investigation finished');
    await refresh();
  } catch (error) {
    toast(error.message || 'Investigation failed', 'bad');
  } finally {
    working = false;
    note.hidden = true;
    unlockLabel(button);
    renderControls();
  }
}
async function verifyNow() {
  if (working) return;
  working = true;
  const button = document.getElementById('verify-btn');
  lockLabel(button, 'Verifying…');
  const note = document.getElementById('verify-activity');
  note.hidden = false;
  note.textContent = 'Running the suite, the regression test, and a traffic replay…';
  renderControls();
  try {
    const report = await api('/api/verify', {method:'POST'});
    cache.verification = report;
    snapshots.verification = '';
    renderVerification(report);
    toast(report.passed ? 'Verification passed' : 'Verification failed', report.passed ? '' : 'bad');
    await refresh();
  } catch (error) {
    toast(error.message || 'Verification failed', 'bad');
  } finally {
    working = false;
    note.hidden = true;
    unlockLabel(button);
    renderControls();
  }
}
async function approve(event) {
  event.preventDefault();
  if (working) return;
  const reason = document.getElementById('approval-reason').value.trim();
  if (reason.length < 8) { toast('Write a reason of at least 8 characters.', 'bad'); return; }
  const token = document.getElementById('approval-token').value;
  sessionStorage.setItem(APPROVER_KEY, token);
  working = true;
  const button = document.getElementById('approve-btn');
  lockLabel(button, 'Approving…');
  renderControls();
  try {
    const result = await api('/api/approve', {method:'POST', headers:{...headers(), ...(token ? {'X-Prahari-Approver-Token': token} : {})}, body:JSON.stringify({reason})});
    if (result.verification) { cache.verification = result.verification; snapshots.verification = ''; renderVerification(result.verification); }
    toast(result.approved ? 'Change approved' : (result.reason || 'Approval was not granted'), result.approved ? '' : 'bad');
    await refresh();
  } catch (error) {
    toast(error.message || 'Approval failed', 'bad');
  } finally {
    working = false;
    unlockLabel(button);
    renderControls();
  }
}
async function establishSession() {
  const token = document.getElementById('access-token').value.trim();
  sessionStorage.setItem(TOKEN_KEY, token);
  try {
    await api('/api/session', {method:'POST', headers:{...headers(), ...(token ? {Authorization:'Bearer ' + token} : {})}});
    document.getElementById('auth-status').textContent = token ? 'Token saved for this tab' : 'Using local operator';
    toast('Connected');
    await refresh();
  } catch (error) {
    document.getElementById('auth-status').textContent = error.message;
    toast(error.message, 'bad');
  }
}
document.getElementById('refresh-btn').addEventListener('click', () => { if (!working) refresh(); });
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', () => runControl(button.dataset.scenario)));
document.getElementById('heal-btn').addEventListener('click', () => runControl('heal'));
document.getElementById('investigate-btn').addEventListener('click', investigate);
document.getElementById('verify-btn').addEventListener('click', verifyNow);
document.getElementById('approve-toggle').addEventListener('click', () => {
  const form = document.getElementById('approve-form');
  form.hidden = !form.hidden;
  document.getElementById('approve-toggle').setAttribute('aria-expanded', form.hidden ? 'false' : 'true');
  if (!form.hidden) document.getElementById('approval-reason').focus();
});
document.getElementById('approve-form').addEventListener('submit', approve);
document.getElementById('connect-btn').addEventListener('click', establishSession);
document.getElementById('copy-diff').addEventListener('click', async () => {
  if (!lastDiff) return;
  try { await navigator.clipboard.writeText(lastDiff); toast('Diff copied'); }
  catch { toast('Could not copy the diff', 'bad'); }
});
document.getElementById('access-token').value = sessionStorage.getItem(TOKEN_KEY) || '';
document.getElementById('approval-token').value = sessionStorage.getItem(APPROVER_KEY) || '';
const stream = new EventSource('/events');
stream.onmessage = event => { try { cache.trace = JSON.parse(event.data); if (ready) renderTrace(cache.trace); } catch { /* ignore a partial event */ } };
refresh();
setInterval(() => { if (!working) refresh(); }, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.post("/api/session")
def create_session(
    response: Response,
    _principal: dict[str, object] = operator_auth,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    token = authorization.removeprefix("Bearer ").strip() if authorization and authorization.startswith("Bearer ") else ""
    response.set_cookie(
        "prahari_access_token",
        token,
        httponly=True,
        secure=os.getenv("PRAHARI_ENV", "development").lower() == "production",
        samesite="strict",
        max_age=3600,
    )
    return {"status": "connected"}


@app.get("/api/state")
def state(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    return read_state()


@app.get("/api/incidents")
def incidents(_principal: dict[str, object] = operator_auth) -> list[dict[str, object]]:
    return recent_audit()


@app.get("/api/alerts")
def alerts(_principal: dict[str, object] = operator_auth) -> list[dict[str, object]]:
    return recent_alerts()


@app.get("/api/verification/latest")
def verification_latest(_principal: dict[str, object] = operator_auth) -> dict[str, object] | None:
    return latest_verification()


@app.get("/api/patch")
def patch(_principal: dict[str, object] = operator_auth) -> dict[str, str] | None:
    path = ROOT / "artifacts" / "proposed_fix.diff"
    if not path.is_file():
        return None
    return {"diff": path.read_text(encoding="utf-8")[:64_000]}


@app.get("/api/integrations")
def integrations(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    try:
        DatadogConfig.from_environment()
        datadog_configured = True
    except RuntimeError:
        datadog_configured = False
    return {
        "sentry": SentryClient().configured(),
        "slack": SlackNotifier().configured(),
        "telegram": TelegramNotifier().configured(),
        "pagerduty": PagerDutyNotifier().configured(),
        "postgres": postgres_configured(),
        "deployment": DeploymentClient().readiness(),
        "auth": provider_status(),
        "otel": otel_status(),
        "loki": LokiClient().configured(),
        "datadog": datadog_configured,
    }


@app.get("/api/platform-status/koyeb")
def koyeb_status(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    return platform_status()


@app.get("/api/dependencies/health")
def dependency_health(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    dependencies = check_dependencies()
    return {"healthy": all(item["healthy"] for item in dependencies), "dependencies": dependencies}


@app.get("/api/slo/status")
def slo_status(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    try:
        return evaluate_slo(os.getenv("TARGET_BASE_URL", "http://localhost:8000").rstrip("/") + "/metrics")
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Unable to query service metrics for SLO evaluation.") from error


@app.post("/api/webhooks/github")
async def github_webhook(request: Request) -> dict[str, object]:
    return await handle_github_webhook(request)


@app.post("/api/webhooks/gitlab")
async def gitlab_webhook(request: Request) -> dict[str, object]:
    return await handle_gitlab_webhook(request)


@app.post("/api/control/{scenario}")
def control(scenario: str, principal: dict[str, object] = operator_auth) -> dict[str, object]:
    result = heal() if scenario == "heal" else inject(scenario)
    audit("dashboard_control", {"scenario": scenario}, actor=str(principal["sub"]))
    return result


@app.post("/api/investigate")
def investigate(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    return run()


@app.post("/api/verify")
def verification(_principal: dict[str, object] = operator_auth) -> dict[str, object]:
    return verify().to_dict()


@app.post("/api/approve")
def approve(
    payload: ApprovalRequest,
    x_prahari_approver_token: str | None = Header(default=None),
    principal: dict[str, object] = approver_auth,
) -> dict[str, object]:
    if not authorise_approval(x_prahari_approver_token):
        raise HTTPException(status_code=401, detail="A valid approver token is required.")
    report = verify().to_dict()
    recorded_patch = latest_tool_call("propose_patch")
    candidate_value = recorded_patch.get("patch", recorded_patch) if recorded_patch else None
    candidate: dict[str, object] | None = candidate_value if isinstance(candidate_value, dict) else None
    candidate_verification = candidate.get("verification") if isinstance(candidate, dict) else None
    if not isinstance(candidate_verification, dict) or not candidate_verification.get("passed"):
        return {
            "approved": False,
            "reason": "No candidate branch has passed isolated suite and traffic-replay verification.",
            "verification": report,
        }
    approver = str(principal["sub"])
    decision = allow_approval(bool(report["passed"]), approver)
    if not decision.allowed:
        return {"approved": False, "reason": decision.reason, "verification": report}
    approval = create_signed_approval(approver, payload.reason)
    result = {
        "approved": True,
        "approval": approval,
        "pr": create_pr("Local incident remediation.", report, candidate),
    }
    audit("approval_granted", {"approver": approver, "reason": payload.reason}, actor=approver)
    return result


@app.get("/events")
async def events(_principal: dict[str, object] = operator_auth) -> StreamingResponse:
    async def stream():
        trace = ROOT / "artifacts" / "incident_trace.json"
        last_payload = ""
        while True:
            data = trace.read_text(encoding="utf-8") if trace.exists() else json.dumps({"status": "idle"})
            if data != last_payload:
                yield f"data: {data}\n\n"
                last_payload = data
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")
