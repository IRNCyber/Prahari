import os

from dotenv import load_dotenv
import sentry_sdk

load_dotenv()

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    traces_sample_rate=0.1,
)

from prahari.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
