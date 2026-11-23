
from dotenv import load_dotenv

load_dotenv()

from prahari.runtime import configure_runtime

configure_runtime("prahari")

from prahari.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
