import asyncio
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit


class ObjectStoreError(RuntimeError):
    pass


def configured() -> bool:
    return all(os.getenv(name, "").strip() for name in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME",
    ))


def _endpoint_url() -> str:
    """Accept either a Cloudflare account ID or its full R2 S3 endpoint."""
    raw = os.getenv("R2_ACCOUNT_ID", "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlsplit(raw)
        host = parsed.netloc or parsed.path
    else:
        host = raw
    host = host.strip("/").split("/", 1)[0]
    suffix = ".r2.cloudflarestorage.com"
    if host.endswith(suffix):
        return f"https://{host}"
    return f"https://{host}{suffix}"


def _client():
    if not configured():
        return None
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ObjectStoreError("R2 support requires the boto3 package.") from exc
    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
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


async def health() -> dict[str, object]:
    """Verify real object write/delete access without exposing credentials."""
    client = _client()
    if client is None:
        return {"configured": False, "ready": False, "error": "not_configured"}
    bucket = os.environ["R2_BUCKET_NAME"].strip()
    key = f"healthchecks/{uuid.uuid4().hex}.txt"
    uploaded = False
    try:
        await asyncio.to_thread(client.put_object, Bucket=bucket, Key=key, Body=b"ok", ContentType="text/plain")
        uploaded = True
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
        return {"configured": True, "ready": True, "error": ""}
    except Exception as exc:
        message = str(exc).lower()
        if "credential" in message or "signature" in message or "accessdenied" in message or "access denied" in message:
            category = "authentication_failed"
        elif "endpoint" in message or "connect" in message or "timeout" in message:
            category = "connection_failed"
        elif "nosuchbucket" in message or "not found" in message:
            category = "bucket_not_found"
        else:
            category = type(exc).__name__.lower() or "storage_unavailable"
        if uploaded:
            try:
                await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=key)
            except Exception:
                pass
        return {"configured": True, "ready": False, "error": category}


def share_url(key: str, expires_in: int = 7 * 24 * 60 * 60) -> str:
    """Return a time-limited R2 URL which can be opened without app sign-in."""
    client = _client()
    if client is None:
        raise ObjectStoreError("Permanent media storage is not configured.")
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": os.environ["R2_BUCKET_NAME"].strip(), "Key": key, "ResponseContentType": "video/mp4", "ResponseContentDisposition": "inline"},
            ExpiresIn=max(60, min(int(expires_in), 7 * 24 * 60 * 60)),
        )
    except Exception as exc:
        raise ObjectStoreError(f"Could not create a shareable video link: {exc}") from exc
