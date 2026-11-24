import asyncio
from pathlib import Path
from autopilot_finalization_worker import scheduler as finalization_scheduler
from durable_media_pipeline import scheduler as media_scheduler

ROOT = Path(__file__).resolve().parent

async def main() -> None:
    # Both queues share the existing 2 GB worker. They remain isolated durable
    # database queues, and each resumes expired leases after restarts/deploys.
    await asyncio.gather(media_scheduler(ROOT), finalization_scheduler(ROOT))

if __name__ == "__main__":
    asyncio.run(main())
