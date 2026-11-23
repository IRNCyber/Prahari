import os
import shutil
import tempfile
import uuid
from pathlib import Path

database_path = Path(tempfile.gettempdir()) / f"prahari-tests-{uuid.uuid4().hex}.sqlite"
data_dir = Path(tempfile.gettempdir()) / f"prahari-data-{uuid.uuid4().hex}"
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["PRAHARI_DATA_DIR"] = str(data_dir)
os.environ["PRAHARI_ENV"] = "development"
os.environ["AUTH_PROVIDER"] = "none"
os.environ["AUTH_ISSUER_URL"] = ""
os.environ["AUTH_AUDIENCE"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["PRAHARI_SEND_NOTIFICATIONS"] = "false"

from prahari.store import Base, engine

Base.metadata.create_all(engine)


def pytest_sessionfinish(session, exitstatus) -> None:
    engine.dispose()
    database_path.unlink(missing_ok=True)
    shutil.rmtree(data_dir, ignore_errors=True)
