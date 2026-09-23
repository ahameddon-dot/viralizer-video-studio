import asyncio
from pathlib import Path
from durable_media_pipeline import scheduler

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    asyncio.run(scheduler(ROOT))