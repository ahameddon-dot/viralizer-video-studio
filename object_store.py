import asyncio
import os
from pathlib import Path


class ObjectStoreError(RuntimeError):
    pass


def configured() -> bool:
    return all(os.getenv(name, "").strip() for name in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME",
    ))


def _client():
    if not configured():
        return None
    try:
        import boto3
    except ImportError as exc:
        raise ObjectStoreError("R2 support requires the boto3 package.") from exc
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID'].strip()}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
    )


async def upload_file(path: Path, key: str, content_type: str = "application/octet-stream") -> bool:
    client = _client()
    if client is None:
        return False
    try:
        await asyncio.to_thread(
            client.upload_file, str(path), os.environ["R2_BUCKET_NAME"].strip(), key,
            ExtraArgs={"ContentType": content_type},
        )
    except Exception as exc:
        raise ObjectStoreError(f"Could not save media to permanent storage: {exc}") from exc
    return True


async def restore_file(path: Path, key: str) -> bool:
    client = _client()
    if client is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".restore")
    try:
        await asyncio.to_thread(client.download_file, os.environ["R2_BUCKET_NAME"].strip(), key, str(temporary))
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        return False
    return True
