"""Add alerts, usage budgets, and deployment metadata."""

from alembic import op

from prahari.store import Base

revision = "0002_alert_budget_deployment"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in ("alerts", "daily_budget", "deployments"):
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("deployments", "daily_budget", "alerts"):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
