from __future__ import annotations
import asyncio, os, shutil, subprocess, uuid
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv
from heygen_client import HeyGenClient
from long_video import start as start_visuals, status as visual_status

load_dotenv(Path(__file__).resolve().parent/'.env')
JOBS:dict[str,dict[str,Any]]={}

def _folder()->Path:
    p=Path(os.getenv('APP_DATA_DIR',str(Path(__file__).parent/'data')))/'finished_videos';p.mkdir(parents=True,exist_ok=True);return p

async def _download(url:str,path:Path):
    async with httpx.AsyncClient(timeout=180,follow_redirects=True) as c:r=await c.get(url);r.raise_for_status();path.write_bytes(r.content)

async def _poll_heygen(client:HeyGenClient,video_id:str,job:dict[str,Any]):
    for _ in range(240):
        result=await client.status(video_id)
        if result['status']=='complete' and result.get('url'):return result['url']
        if result['status']=='failed':raise RuntimeError('HeyGen presenter generation failed.')
        job['stage']='Generating presenter and content visuals';await asyncio.sleep(5)
    raise RuntimeError('HeyGen presenter generation timed out.')

async def _poll_visuals(job_id:str,job:dict[str,Any]):
    for _ in range(360):
        state=visual_status(job_id) or {}
        if state.get('stage'):job['visual_stage']=state['stage']
        if state.get('status')=='complete':return state['url'],state
        if state.get('status')=='failed':raise RuntimeError(state.get('error') or 'Content visual generation failed.')
        await asyncio.sleep(5)
    raise RuntimeError('Content visual generation timed out.')

def _intervals(duration:int)->str:
    if duration<=8:return f'between(t,2,{max(3,duration-2)})'
    blocks=[];start=3
    while start<duration-3:
        end=min(start+max(3,min(7,duration//4)),duration-3);blocks.append(f'between(t,{start},{end})');start=end+3
    return '+'.join(blocks) or f'between(t,2,{duration-2})'

def _compose(presenter:Path,visuals:Path,output:Path,duration:int):
    enable=_intervals(duration)
    filt=("[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1[p];"+"[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[b];"+f"[p][b]overlay=0:0:enable='{enable}'[v]")
    cmd=['ffmpeg','-y','-i',str(presenter),'-stream_loop','-1','-i',str(visuals),'-filter_complex',filt,'-map','[v]','-map','0:a?','-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:raise RuntimeError('Could not edit the presenter and content visuals together.')

async def _run(job_id:str,content:dict[str,Any],duration:int,quality:str,script:str,avatar_id:str,voice_id:str,background:str,quality_mode:bool):
    job=JOBS[job_id];folder=_folder();presenter_path=folder/f'{job_id}-presenter.mp4';output=folder/f'viralizer-hybrid-{uuid.uuid4().hex}.mp4'
    try:
        job['stage']='Planning presenter and content visuals';heygen=HeyGenClient();presenter_id=await heygen.generate(script,avatar_id,voice_id,background=background);visual_job=start_visuals(content,duration,quality,quality_mode=quality_mode,production={'generation_mode':'hybrid'})
        presenter_task=asyncio.create_task(_poll_heygen(heygen,presenter_id,job));visual_task=asyncio.create_task(_poll_visuals(visual_job,job));presenter_url=await presenter_task
        try:visual_url,visual_meta=await visual_task
        except Exception as visual_error:
            job.update(best_available=True,warning=str(visual_error));await _download(presenter_url,output);job.update(status='complete',url=f'/api/finished-video/{output.name}',stage='Best available presenter video ready',presenter_audio=True);return
        await _download(presenter_url,presenter_path);visuals_path=folder/Path(visual_url).name
        job['stage']='Editing presenter with content visuals';await asyncio.to_thread(_compose,presenter_path,visuals_path,output,duration);presenter_path.unlink(missing_ok=True)
        job.update(status='complete',url=f'/api/finished-video/{output.name}',stage='Hybrid video ready',presenter_audio=True,visual_qc_score=visual_meta.get('qc_score'),retry_count=visual_meta.get('retry_count',0))
    except Exception as exc:presenter_path.unlink(missing_ok=True);job.update(status='failed',stage='Hybrid video generation failed',error=str(exc))

def start(content:dict[str,Any],duration:int,quality:str,script:str,avatar_id:str,voice_id:str,background:str,quality_mode:bool=True)->str:
    job_id='hybrid-'+uuid.uuid4().hex;JOBS[job_id]={'status':'processing','stage':'Analyzing content','presenter_audio':True,'best_available':False};asyncio.create_task(_run(job_id,content,duration,quality,script,avatar_id,voice_id,background,quality_mode));return job_id

def status(job_id:str):return JOBS.get(job_id)