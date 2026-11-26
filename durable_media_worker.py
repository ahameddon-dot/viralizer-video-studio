import asyncio
from pathlib import Path
from autopilot_finalization_worker import scheduler as finalization_scheduler
from durable_media_pipeline import scheduler as media_scheduler

ROOT = Path(__file__).resolve().parent

async def main() -> None:
    # Both queues share the existing 2 GB worker. They remain isolated durable
    # database queues, and each resumes expired leases after restarts/deploys.
    # Isolate the durable consumers: a transient failure in the Autopilot queue
    # must never terminate Creatorthon video finishing, and vice versa.
    async def supervise(name: str, scheduler) -> None:
        while True:
            try:
                await scheduler(ROOT)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"{name} scheduler crashed; restarting: {exc}", flush=True)
                await asyncio.sleep(5)

    await asyncio.gather(
        supervise("media", media_scheduler),
        supervise("finalization", finalization_scheduler),
    )

if __name__ == "__main__":
    asyncio.run(main())
