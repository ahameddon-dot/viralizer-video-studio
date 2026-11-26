"""Dedicated, restart-safe consumer for long Autopilot final assembly jobs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import HTTPException

from autopilot_finalization_store import claim_due, finish, renew, retry
from media_finisher import MediaFinisherError
from object_store import ObjectStoreError

LOG = logging.getLogger(__name__)


async def _renew(root: Path, customer_id: str, concept_id: str) -> None:
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(renew, root, customer_id, concept_id, 600)


async def process_claimed(root: Path, job: dict) -> None:
    # Importing here avoids a circular import while keeping one canonical
    # assembly implementation for both historical recovery and new jobs.
    from app import AutopilotDemoAssetRequest, _finalize_autopilot_concept

    customer_id = str(job.get("customer_id") or "")
    concept_id = str(job.get("concept_id") or "")
    lease = asyncio.create_task(_renew(root, customer_id, concept_id))
    try:
        payload = AutopilotDemoAssetRequest.model_validate(job.get("payload") or {})
        result = await _finalize_autopilot_concept(customer_id, concept_id, payload)
        await asyncio.to_thread(finish, root, customer_id, concept_id, result=result)
    except HTTPException as exc:
        message = str(exc.detail)
        if exc.status_code >= 500 and int(job.get("attempt") or 0) < 20:
            await asyncio.to_thread(retry, root, customer_id, concept_id, message)
        else:
            await asyncio.to_thread(finish, root, customer_id, concept_id, error=message)
    except (ObjectStoreError, MediaFinisherError, OSError) as exc:
        if int(job.get("attempt") or 0) < 20:
            await asyncio.to_thread(retry, root, customer_id, concept_id, str(exc))
        else:
            await asyncio.to_thread(finish, root, customer_id, concept_id, error=str(exc))
    except Exception as exc:
        LOG.exception("Autopilot final assembly failed")
        await asyncio.to_thread(finish, root, customer_id, concept_id, error=str(exc) or "Final assembly failed.")
    finally:
        lease.cancel()
        await asyncio.gather(lease, return_exceptions=True)


async def scheduler(root: Path) -> None:
    """Continuously consume durable finalization jobs, one memory-heavy job at a time."""
    while True:
        try:
            jobs = await asyncio.to_thread(claim_due, root, 1, 600)
            if jobs:
                await process_claimed(root, jobs[0])
        except asyncio.CancelledError:
            raise
        except Exception:
            # A deadlock aborts only this transaction. Retrying is safe because
            # jobs are durable and protected by expiring leases.
            LOG.exception("Autopilot finalization queue poll failed; retrying")
            await asyncio.sleep(5)
            continue
        await asyncio.sleep(2 if jobs else 5)
