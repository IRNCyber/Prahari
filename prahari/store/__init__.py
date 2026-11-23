"""SQLAlchemy-backed persistence with SQLite as the local default."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        data_dir = Path(os.getenv("PRAHARI_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(data_dir / 'prahari.db').as_posix()}"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class State(Base):
    __tablename__ = "state"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scenario: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="firing")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyBudget(Base):
    __tablename__ = "daily_budget"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    spent_usd: Mapped[float] = mapped_column(nullable=False, default=0.0)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    repository: Mapped[str] = mapped_column(String(256), nullable=False)
    revision: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    signer: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VerificationReport(Base):
    __tablename__ = "verification_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    passed: Mapped[bool] = mapped_column(nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _now() -> datetime:
    return datetime.now(UTC)


def get_state() -> dict[str, object]:
    with SessionLocal() as db:
        row = db.get(State, "fault")
        return json.loads(row.value) if row else {"scenario": None}


def set_state(value: dict[str, object]) -> dict[str, object]:
    with SessionLocal.begin() as db:
        row = db.get(State, "fault")
        if row is None:
            row = State(key="fault", value="", updated_at=_now())
            db.add(row)
        row.value = json.dumps(value)
        row.updated_at = _now()
        active = db.get(State, "active_incident_id")
        previous_id = active.value if active else None
        scenario = value.get("scenario")
        if scenario:
            if previous_id:
                incident = db.get(Incident, previous_id)
            else:
                incident = None
            if incident is None or incident.status != "open" or incident.scenario != scenario:
                if incident is not None and incident.status == "open":
                    incident.status = "superseded"
                    incident.updated_at = _now()
                incident = Incident(
                    scenario=str(scenario),
                    status="open",
                    severity="unknown",
                    summary=f"Injected scenario: {scenario}",
                    created_at=_now(),
                    updated_at=_now(),
                )
                db.add(incident)
                db.flush()
                if active is None:
                    active = State(key="active_incident_id", value=incident.id, updated_at=_now())
                    db.add(active)
                else:
                    active.value = incident.id
                    active.updated_at = _now()
            else:
                incident.updated_at = _now()
        elif previous_id:
            incident = db.get(Incident, previous_id)
            if incident is not None and incident.status == "open":
                incident.status = "resolved"
                incident.updated_at = _now()
            db.delete(active)
    return value


def audit(
    event_type: str,
    payload: dict[str, object],
    actor: str = "system",
    incident_id: str | None = None,
) -> None:
    safe_payload = _redact(payload)
    with SessionLocal.begin() as db:
        if incident_id is None:
            active = db.get(State, "active_incident_id")
            incident_id = active.value if active else None
        db.add(
            AuditEvent(
                incident_id=incident_id,
                event_type=event_type,
                actor=actor,
                payload=json.dumps(safe_payload, default=str),
                created_at=_now(),
            )
        )


def prune_audit_events(retention_days: int | None = None) -> int:
    from datetime import timedelta

    days = retention_days if retention_days is not None else int(os.getenv("PRAHARI_AUDIT_RETENTION_DAYS", "180"))
    if days < 1:
        raise ValueError("Audit retention must be at least one day.")
    cutoff = _now() - timedelta(days=days)
    with SessionLocal.begin() as db:
        result = db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
        return int(cast(CursorResult[Any], result).rowcount or 0)


def record_tool_call(
    tool: str,
    inputs: dict[str, object],
    output: dict[str, object] | None = None,
    status: str = "completed",
    incident_id: str | None = None,
) -> str:
    call_id = str(uuid4())
    with SessionLocal.begin() as db:
        if incident_id is None:
            active = db.get(State, "active_incident_id")
            incident_id = active.value if active else None
        db.add(
            ToolCall(
                id=call_id,
                incident_id=incident_id,
                tool=tool,
                status=status,
                input_json=json.dumps(_redact(inputs), default=str),
                output_json=json.dumps(_redact(output), default=str) if output is not None else None,
                created_at=_now(),
            )
        )
    return call_id


def _redact(value: Any) -> Any:
    import re

    credential_url = re.compile(r"(?i)\b((?:postgres(?:ql)?|mysql)://[^:/@\s]+:)[^@\s]+(@)")
    secret_assignment = re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization|webhook|dsn|private[_-]?key|routing[_-]?key|client[_-]?secret|signing[_-]?secret|verification[_-]?token|bot[_-]?token)\b(\s*[:=]\s*)([^\s,;]+)"
    )
    bearer = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if re.search(r"(?i)(api[_-]?key|token|secret|password|authorization|webhook|dsn|private[_-]?key|routing[_-]?key|client[_-]?secret|signing[_-]?secret|verification[_-]?token|bot[_-]?token|email)", str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+[.][A-Z]{2,}", "[REDACTED]", value, flags=re.IGNORECASE)
        value = credential_url.sub(r"\1[REDACTED]\2", value)
        return bearer.sub("Bearer [REDACTED]", secret_assignment.sub(r"\1\2[REDACTED]", value))
    return value


def record_alert(
    fingerprint: str,
    severity: str,
    summary: str,
    evidence: list[str],
    suppression_seconds: int = 300,
) -> tuple[dict[str, object], bool]:
    from datetime import timedelta

    timestamp = _now()
    with SessionLocal.begin() as db:
        alert = db.scalar(select(Alert).where(Alert.fingerprint == fingerprint))
        created = alert is None
        if alert is None:
            active = db.get(State, "active_incident_id")
            incident_id = active.value if active else None
            if incident_id is None:
                incident = Incident(
                    scenario=None,
                    status="open",
                    severity=severity,
                    summary=summary,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                db.add(incident)
                db.flush()
                incident_id = incident.id
                db.add(State(key="active_incident_id", value=incident_id, updated_at=timestamp))
            alert = Alert(
                fingerprint=fingerprint,
                incident_id=incident_id,
                severity=severity,
                summary=summary,
                evidence_json=json.dumps(evidence),
                status="firing",
                first_seen_at=timestamp,
                last_seen_at=timestamp,
            )
            db.add(alert)
        else:
            last_seen = alert.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            created = timestamp - last_seen >= timedelta(seconds=suppression_seconds)
            alert.severity = severity
            alert.summary = summary
            alert.evidence_json = json.dumps(evidence)
            alert.status = "firing"
            alert.last_seen_at = timestamp
    return (
        {
            "id": alert.id,
            "incident_id": alert.incident_id,
            "fingerprint": alert.fingerprint,
            "severity": alert.severity,
            "summary": alert.summary,
            "evidence": json.loads(alert.evidence_json),
            "status": alert.status,
            "first_seen_at": alert.first_seen_at.isoformat(),
            "last_seen_at": alert.last_seen_at.isoformat(),
        },
        created,
    )


def record_deployment(
    provider: str,
    repository: str,
    revision: str,
    environment: str,
    state: str,
    url: str | None = None,
) -> str:
    deployment_id = str(uuid4())
    with SessionLocal.begin() as db:
        db.add(
            Deployment(
                id=deployment_id,
                provider=provider,
                repository=repository,
                revision=revision,
                environment=environment,
                state=state,
                url=url,
                created_at=_now(),
            )
        )
    return deployment_id


def recent_deployments(limit: int = 10) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with SessionLocal() as db:
        rows = db.scalars(select(Deployment).order_by(Deployment.created_at.desc()).limit(limit)).all()
        return [
            {
                "id": row.id,
                "provider": row.provider,
                "repository": row.repository,
                "revision": row.revision,
                "environment": row.environment,
                "state": row.state,
                "url": row.url,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


def daily_spend() -> float:
    with SessionLocal() as db:
        row = db.get(DailyBudget, _now().date().isoformat())
        return float(row.spent_usd) if row else 0.0


def add_daily_spend(amount_usd: float) -> float:
    if amount_usd < 0:
        raise ValueError("Budget spend cannot be negative.")
    day = _now().date().isoformat()
    with SessionLocal.begin() as db:
        row = db.get(DailyBudget, day)
        if row is None:
            row = DailyBudget(day=day, spent_usd=0.0)
            db.add(row)
        row.spent_usd += amount_usd
        return float(row.spent_usd)


def resolve_alert(fingerprint: str) -> bool:
    with SessionLocal.begin() as db:
        alert = db.scalar(select(Alert).where(Alert.fingerprint == fingerprint))
        if alert is None or alert.status == "resolved":
            return False
        alert.status = "resolved"
        active = db.get(State, "active_incident_id")
        if alert.incident_id:
            remaining = db.scalar(
                select(Alert.id)
                .where(Alert.incident_id == alert.incident_id, Alert.status == "firing")
                .limit(1)
            )
            if remaining is None:
                incident = db.get(Incident, alert.incident_id)
                if incident is not None and incident.status == "open":
                    incident.status = "resolved"
                    incident.updated_at = _now()
                if active and active.value == alert.incident_id:
                    db.delete(active)
        return True


def record_verification(report: dict[str, Any], incident_id: str | None = None) -> str:
    report_id = str(uuid4())
    with SessionLocal.begin() as db:
        if incident_id is None:
            active = db.get(State, "active_incident_id")
            incident_id = active.value if active else None
        db.add(
            VerificationReport(
                id=report_id,
                incident_id=incident_id,
                passed=bool(report.get("passed")),
                report_json=json.dumps(_redact(report), default=str),
                created_at=_now(),
            )
        )
    return report_id


def create_signed_approval(signer: str, reason: str, ttl_seconds: int = 900) -> dict[str, str]:
    secret = os.getenv("PRAHARI_APPROVER_TOKEN", "")
    if not secret:
        raise RuntimeError("PRAHARI_APPROVER_TOKEN is not configured.")
    if not signer.strip() or not reason.strip() or ttl_seconds < 1:
        raise ValueError("A signer, reason, and positive expiry are required.")
    created = _now()
    expires = datetime.fromtimestamp(created.timestamp() + ttl_seconds, UTC)
    approval_id = str(uuid4())
    signed_content = f"{approval_id}\n{signer}\n{reason}\n{expires.isoformat()}".encode()
    signature = hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
    with SessionLocal.begin() as db:
        active = db.get(State, "active_incident_id")
        db.add(
            Approval(
                id=approval_id,
                incident_id=active.value if active else None,
                signer=signer,
                reason=reason,
                signature=signature,
                expires_at=expires,
                created_at=created,
            )
        )
    return {"id": approval_id, "signature": signature, "expires_at": expires.isoformat()}


def recent_audit(limit: int = 100) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all()
        return [
            {
                "id": row.id,
                "incident_id": row.incident_id,
                "event_type": row.event_type,
                "actor": row.actor,
                "payload": json.loads(row.payload),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


def recent_alerts(limit: int = 50) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with SessionLocal() as db:
        rows = db.scalars(select(Alert).order_by(Alert.last_seen_at.desc()).limit(limit)).all()
        return [
            {
                "id": row.id,
                "incident_id": row.incident_id,
                "fingerprint": row.fingerprint,
                "severity": row.severity,
                "summary": row.summary,
                "evidence": json.loads(row.evidence_json),
                "status": row.status,
                "first_seen_at": row.first_seen_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in rows
        ]


def latest_verification() -> dict[str, object] | None:
    with SessionLocal() as db:
        row = db.scalar(select(VerificationReport).order_by(VerificationReport.created_at.desc()).limit(1))
        if row is None:
            return None
        report = json.loads(row.report_json)
        report.update({"id": row.id, "passed": row.passed, "created_at": row.created_at.isoformat()})
        return report


def latest_tool_call(tool: str) -> dict[str, object] | None:
    with SessionLocal() as db:
        row = db.scalar(
            select(ToolCall)
            .where(ToolCall.tool == tool, ToolCall.status == "completed")
            .order_by(ToolCall.created_at.desc())
            .limit(1)
        )
        if row is None or row.output_json is None:
            return None
        return json.loads(row.output_json)
