from __future__ import annotations
import asyncio, base64, json, re, tempfile, time, uuid, threading
from pathlib import Path
from typing import Any
from creatorthon_store import _connect, update_project
from media_finisher import MediaFinisherError, _download, finish_video
from object_store import ObjectStoreError, upload_file
from video_providers import VideoProviderError, video_status
ACTIVE=("queued","waiting_provider","raw_archiving","finishing","retrying")
_SCHEMA_READY=False
_SCHEMA_LOCK=threading.Lock()
def _ensure(db: Any)->None:
 global _SCHEMA_READY
 if _SCHEMA_READY:return
 with _SCHEMA_LOCK:
  if _SCHEMA_READY:return
  db.execute("""CREATE TABLE IF NOT EXISTS creatorthon_media_jobs (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,project_id TEXT NOT NULL DEFAULT '',provider TEXT NOT NULL DEFAULT '',provider_job_id TEXT NOT NULL DEFAULT '',raw_video_url TEXT NOT NULL DEFAULT '',payload_json TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'queued',stage TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',raw_object_key TEXT NOT NULL DEFAULT '',output_url TEXT NOT NULL DEFAULT '',retry_count BIGINT NOT NULL DEFAULT 0,next_attempt_at BIGINT NOT NULL DEFAULT 0,lease_until BIGINT NOT NULL DEFAULT 0,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL)""")
  db.execute("CREATE INDEX IF NOT EXISTS idx_creatorthon_media_jobs_due ON creatorthon_media_jobs(status,next_attempt_at)")
  _SCHEMA_READY=True
def _row(row: Any)->dict[str,Any]:
 item=dict(row)
 try:item["payload"]=json.loads(item.pop("payload_json") or "{}")
 except (TypeError,ValueError):item["payload"]={}
 return item
def enqueue(root:Path,user_id:str,*,project_id="",provider="",provider_job_id="",raw_video_url="",narration="",voice="coral",official_logo_data=""):
 job_id,now=uuid.uuid4().hex,int(time.time());payload={"narration":narration[:4096],"voice":voice[:40],"official_logo_data":official_logo_data}
 with _connect(root) as db:
  _ensure(db);db.execute("INSERT INTO creatorthon_media_jobs (id,user_id,project_id,provider,provider_job_id,raw_video_url,payload_json,status,stage,next_attempt_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,user_id,project_id,provider,provider_job_id,raw_video_url,json.dumps(payload),"queued","Waiting for the provider media file…",now,now,now));row=db.execute("SELECT * FROM creatorthon_media_jobs WHERE id=?",(job_id,)).fetchone()
 return _row(row)
def get(root:Path,user_id:str,job_id:str):
 with _connect(root) as db:
  _ensure(db);row=db.execute("SELECT * FROM creatorthon_media_jobs WHERE id=? AND user_id=?",(job_id,user_id)).fetchone()
 return _row(row) if row else None
def _update(root:Path,job_id:str,**values):
 values["updated_at"]=int(time.time());allowed={k:v for k,v in values.items() if k in {"raw_video_url","status","stage","error","raw_object_key","output_url","retry_count","next_attempt_at","lease_until","updated_at"}}
 with _connect(root) as db:
  _ensure(db);db.execute("UPDATE creatorthon_media_jobs SET "+",".join(f"{k}=?" for k in allowed)+" WHERE id=?",[*allowed.values(),job_id]);row=db.execute("SELECT * FROM creatorthon_media_jobs WHERE id=?",(job_id,)).fetchone()
 return _row(row) if row else None
def due(root:Path,limit=4):
 now=int(time.time())
 with _connect(root) as db:
  _ensure(db);marks=",".join("?" for _ in ACTIVE);rows=db.execute(f"SELECT * FROM creatorthon_media_jobs WHERE status IN ({marks}) AND next_attempt_at<=? AND lease_until<=? ORDER BY updated_at LIMIT ?",[*ACTIVE,now,now,limit]).fetchall();items=[_row(row) for row in rows]
  for item in items:db.execute("UPDATE creatorthon_media_jobs SET lease_until=?,updated_at=? WHERE id=?",(now+180,now,item["id"]))
 return items
def _retry(root:Path,job:dict,error:str):
 count=int(job.get("retry_count") or 0)+1
 if count>=40:_update(root,job["id"],status="failed",stage="Automatic recovery could not complete this video.",error=error[:1000],retry_count=count,lease_until=0);return
 delay=min(900,15*(2**min(count,5)));_update(root,job["id"],status="retrying",stage="Waiting for the provider media file before finishing your video…",error=error[:1000],retry_count=count,next_attempt_at=int(time.time())+delay,lease_until=0)
def _official_logo(data: str) -> bytes | None:
 match=re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\\r\\n]+)",str(data or ""))
 if not match:return None
 try:return base64.b64decode(match.group(1),validate=True)
 except Exception:return None
async def process_one(root:Path,job:dict):
 try:
  raw=str(job.get("raw_video_url") or "")
  if not raw:
   if not job.get("provider") or not job.get("provider_job_id"):raise RuntimeError("The provider job reference was not saved.")
   state=await video_status(str(job["provider"]),str(job["provider_job_id"]))
   if str(state.get("status") or "").lower() in {"failed","error","cancelled","canceled"}:_update(root,job["id"],status="failed",stage="Video provider reported a failure.",error=str(state.get("error") or "Provider generation failed."),lease_until=0);return
   raw=str(state.get("video_url") or state.get("url") or state.get("output_url") or "")
   if not raw:_update(root,job["id"],status="waiting_provider",stage="PixVerse is still publishing the completed media file…",next_attempt_at=int(time.time())+20,lease_until=0);return
   job=_update(root,job["id"],raw_video_url=raw,status="raw_archiving",stage="Securing the original provider video…",next_attempt_at=int(time.time()),lease_until=0) or job
  payload=job.get("payload") or {}
  with tempfile.TemporaryDirectory(prefix="viralizer-durable-") as folder:
   source=Path(folder)/"source.mp4"
   try:await _download(raw,source)
   except MediaFinisherError as exc:_retry(root,job,str(exc));return
   raw_key=str(job.get("raw_object_key") or f"raw_videos/{job['id']}.mp4")
   if not await upload_file(source,raw_key,"video/mp4"):
    raise ObjectStoreError("Permanent media storage is not configured.")
   _update(root,job["id"],raw_object_key=raw_key,status="finishing",stage="Adding narration, branding, and final encoding…",lease_until=0)
   output=await finish_video(raw,str(payload.get("narration") or ""),str(payload.get("voice") or "coral"),(root/"static"/"viralizer-original-logo.png").read_bytes(),secondary_logo_bytes=_official_logo(str(payload.get("official_logo_data") or "")),source_path=source)
   if not await upload_file(output,f"finished_videos/{output.name}","video/mp4"):
    raise ObjectStoreError("Permanent media storage is not configured.")
   final=f"/api/finished-video/{output.name}"
  _update(root,job["id"],status="completed",stage="Your narrated video is ready.",output_url=final,error="",lease_until=0)
  if job.get("project_id"):update_project(root,str(job["user_id"]),str(job["project_id"]),{"video_url":final,"status":"completed","production":{"provider":job.get("provider"),"provider_job_id":job.get("provider_job_id"),"raw_video_url":raw,"raw_object_key":raw_key,"media_job_id":job["id"],"status":"completed"}})
 except (MediaFinisherError,ObjectStoreError,VideoProviderError,OSError) as exc:_retry(root,job,str(exc))
 except Exception as exc:_retry(root,job,f"Unexpected media worker error: {exc}")
async def scheduler(root:Path):
 while True:
  try:
   jobs=await asyncio.to_thread(due,root)
   for job in jobs:await process_one(root,job)
  except Exception:pass
  await asyncio.sleep(8)