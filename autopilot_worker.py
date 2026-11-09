import asyncio
from pathlib import Path

from autopilot_operations import run_worker


ROOT = Path(__file__).resolve().parent


if __name__ == "__main__":
    asyncio.run(run_worker(ROOT))
