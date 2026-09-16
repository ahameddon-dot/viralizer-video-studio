import asyncio, json, os, re, shutil, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx
from pixverse_client import PixVerseClient, build_video_prompt
from openai_image_client import OpenAIImageError, generate_instagram_image
from quality_pipeline import build_plan, repair_prompt, score_reference, score_video

JOBS: dict[str, dict[str, Any]] = {}
PURPOSES = ['visual hook','context','main development','important detail','human impact','wider impact','future implication','closing visual']

def clip(value, limit=30):
    return ' '.join(re.sub(r'\s+',' ',str(value or '')).strip().split()[:limit])

def durations(total):
    return {20:[5,5,5,5],30:[10,5,5,5,5],45:[8,8,8,8,8,5],60:[10,10,10,10,5,5,5,5]}[total]

MODEL_NEGATIVE = "readable text, letters, words, numbers, captions, subtitles, title cards, labels, signs, posters, newspapers, charts, graphs, dashboards, phone UI, visible app interface, keyboard letters, brand names, fake logos, watermarks, pseudo-text, malformed glyphs, scrambled typography, distorted hands, extra fingers, missing fingers, warped phones, duplicated objects, flicker, unstable camera, inconsistent clothing, abrupt transformation"
def _persist_generation_trace(folder:Path,entry:dict[str,Any])->None:
    trace_file=folder/'generation-trace.jsonl'
    record={'timestamp':datetime.now(timezone.utc).isoformat(),**entry}
    with trace_file.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(record,ensure_ascii=True)+'\n')

def prompts(content,total,creative_prompt=""):
    topic=clip(content.get('topic') or content.get('suggested_title') or content.get('hook'),20)
    context=' '.join(str(content.get(key) or '') for key in ('topic','category','entity_type_label')).lower()
    if any(word in context for word in ('iphone','smartphone photography','mobile photography','camera tips','photography')):
        style='premium mobile-photography commercial'; profile='the same skilled photographer in a charcoal jacket using the same unbranded triple-lens smartphone, rear camera module visible and screen always turned away or completely black'; light='warm golden-hour side light, soft lens reflections, natural city bokeh'; actions=[
            'raises the phone toward a sunlit city subject and settles into a stable two-handed grip',
            'steps sideways to improve composition while the real subject moves naturally through the background',
            'crouches near a clean puddle reflection and angles the rear camera lenses toward the scene',
            'moves beside a window-lit portrait subject and gently adjusts physical distance instead of touching any visible interface',
            'tracks a moving cyclist with controlled body rotation while keeping the phone display hidden',
            'frames architecture from a low angle as clouds and reflections move subtly overhead',
            'captures warm night lights with the rear cameras facing the scene and no screen content visible',
            'lowers the phone and studies the real scene with a satisfied expression, ending on the camera lenses catching light',
        ]
    elif any(word in context for word in ('match','football','soccer','liverpool','league','sport')):
        style='cinematic sports documentary'; profile='the same focused football player in a dark training kit inside one modern stadium and tunnel complex'; light='cool tunnel illumination opening into bright white stadium floodlights with soft atmospheric haze'; actions=[
            'tightens his boots and rises from the bench as teammates pass naturally behind him','walks from the tunnel toward the pitch with a steady purposeful stride','accelerates into a pressing drill while nearby players shift position naturally','controls the ball with one clean touch and changes direction','looks toward teammates and signals with a simple hand gesture','sprints into open space under the floodlights','slows near the touchline and takes in the moving stadium atmosphere','stands composed at the pitch edge as the camera settles behind him']
    else:
        style='cinematic editorial documentary'; profile='the same main subject, wardrobe, key object, and coherent real-world location established for this story'; light='directional natural key light balanced by practical background sources and realistic reflections'; actions=[
            'performs one immediate physical action that establishes the subject and creates curiosity','moves through the environment while interacting with one relevant physical object','reveals the central development through a second clear and observable action','examines one meaningful material detail as the camera moves closer','reacts naturally through posture and movement while background people continue believable activity','crosses into a wider environment that shows the consequence through physical change','pauses as surrounding motion suggests what may happen next','ends on one clean memorable composition with continuing natural motion']
    result=[]
    for i,length in enumerate(durations(total)):
        purpose=PURPOSES[min(i,len(PURPOSES)-1)]; action=actions[min(i,len(actions)-1)]; camera=('slow controlled push-in' if i%3==0 else 'gentle lateral tracking' if i%3==1 else 'locked camera with purposeful subject motion')
        shot_content=dict(content)
        shot_content["video_idea"]=f"{creative_prompt} {purpose}: {action}. Keep continuity with adjacent scenes.".strip()
        prompt=build_video_prompt(shot_content,length,generation_type="text_to_video",quality_mode=False)
        result.append((length,prompt))
    return result
async def _poll(client,video_id):
    for _ in range(180):
        await asyncio.sleep(5)
        result=await client.status(video_id)
        if result.get('status')==1 and result.get('url'): return result['url']
        if result.get('status') in (7,8): raise RuntimeError('A PixVerse scene failed.')
    raise RuntimeError('PixVerse scene generation timed out.')

async def _download(url,path):
    async with httpx.AsyncClient(timeout=120,follow_redirects=True) as client:
        response=await client.get(url);response.raise_for_status();path.write_bytes(response.content)

def _combine(clips,output):
    if not shutil.which('ffmpeg'): raise RuntimeError('FFmpeg is not installed.')
    listing=output.parent/f'{output.stem}-clips.txt'
    listing.write_text('\n'.join("file '"+str(p).replace("'","'\\''")+"'" for p in clips),encoding='utf-8')
    command=['ffmpeg','-y','-f','concat','-safe','0','-i',str(listing),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    result=subprocess.run(command,capture_output=True,text=True)
    listing.unlink(missing_ok=True)
    if result.returncode: raise RuntimeError('Could not combine the generated scenes.')

async def _quality_shot(client,shot,quality,folder,job_id,index,job):
    reference_bytes=None; reference_score=None; reference_retries=0; route=shot['route']
    preflight=shot.get('preflight_consistency') or {"status":"FAIL","reason":"Missing shot consistency validation"}
    job.update(current_job_id=job_id,generation_mode=route,core_subject=shot.get('shot_specification',{}).get('core_subject'),visual_concept=shot.get('motion_debug',{}).get('selected_visual_concept'),shot_specification=shot.get('shot_specification'),reference_image_prompt=shot.get('reference_prompt'),reference_prompt_consistency=preflight,final_pixverse_prompt=shot.get('motion_prompt'))
    job.setdefault('generation_trace',[]).append({'job_id':job_id,'scene_index':index,'core_subject':job.get('core_subject'),'category':shot.get('shot_specification',{}).get('category'),'visual_concept':job.get('visual_concept'),'concrete_action':shot.get('motion_debug',{}).get('concrete_visual_action'),'generation_mode':route,'shot_specification':shot.get('shot_specification'),'reference_image_prompt':shot.get('reference_prompt'),'reference_prompt_consistency':preflight,'final_pixverse_prompt':shot.get('motion_prompt')})
    if route=='image_to_video' and preflight.get('status')!='PASS':
        route='text_to_video';job['generation_mode']='text_to_video';job['reference_semantic_validation']={'status':'FAIL','reason':'Reference prompt and motion prompt failed canonical shot preflight; routed to text-to-video.'}
    if route=='image_to_video':
        job['stage']=f'Preparing reference frame {index+1} of {job["scenes_total"]}'
        try:
            reference_bytes=await generate_instagram_image({},shot['reference_prompt'],purpose='pixverse')
            reference_path=folder/f"reference-{job_id}-{index}.png"
            reference_path.write_bytes(reference_bytes)
            job['reference_image_path']=str(reference_path)
            job['reference_image_url']=f"/api/video/reference/{job_id}/{index}"
            reference_score=await score_reference(reference_bytes,shot.get('shot_specification'))
            job['reference_semantic_validation']={'status':reference_score.get('semantic_validation_status','FAIL') if reference_score.get('available') else 'UNAVAILABLE','semantic_alignment_score':reference_score.get('semantic_alignment_score'),'detected_subjects':reference_score.get('detected_subjects',[]),'conflicting_objects':reference_score.get('conflicting_objects',[]),'reason':reference_score.get('failure_reason','')}
            if reference_score.get('available') and (float(reference_score.get('overall_quality_score',0))<85 or job['reference_semantic_validation']['status']!='PASS'):
                reference_retries=1
                repaired=repair_prompt(shot['reference_prompt'],str(reference_score.get('failure_reason') or 'semantic mismatch'))
                reference_bytes=await generate_instagram_image({},repaired,purpose='pixverse')
                reference_score=await score_reference(reference_bytes,shot.get('shot_specification'))
                job['reference_semantic_validation']={'status':reference_score.get('semantic_validation_status','FAIL') if reference_score.get('available') else 'UNAVAILABLE','semantic_alignment_score':reference_score.get('semantic_alignment_score'),'detected_subjects':reference_score.get('detected_subjects',[]),'conflicting_objects':reference_score.get('conflicting_objects',[]),'reason':reference_score.get('failure_reason','')}
            reference_path.write_bytes(reference_bytes)
        except OpenAIImageError:
            route='text_to_video';reference_bytes=None;reference_score={'available':False,'status':'unavailable'}
    if route=='image_to_video' and job.get('reference_semantic_validation',{}).get('status')!='PASS':
        route='text_to_video'
        job['generation_mode']='text_to_video'
        job['reference_fallback_reason']='Reference image was not pixel-validated; using text-to-video instead of risking an unrelated start frame.'
        job['generation_trace'][-1].update(generation_mode='text_to_video',reference_fallback_reason=job['reference_fallback_reason'])
    best=None; best_score=-1; retries=0; failure=''
    for attempt in range(2):
        job['stage']=f'Generating scene {index+1} of {job["scenes_total"]}' if attempt==0 else f'Improving scene {index+1} of {job["scenes_total"]}'
        base_prompt=shot['motion_prompt'] if route=='image_to_video' and reference_bytes else shot['prompt']
        active_prompt=base_prompt if attempt==0 else repair_prompt(base_prompt,failure)
        if route=='image_to_video' and reference_bytes:
            image_id=await client.upload_image(image_bytes=reference_bytes,filename=f'{job_id}-reference-{index}.png',content_type='image/png')
            job['reference_image_id']=image_id
            request_payload={'mode':'image_to_video','image_id':image_id,'prompt':active_prompt,'duration':shot['duration'],'quality':quality,'model':'v6'}
            job['pixverse_request_payload']=request_payload
            job['generation_trace'][-1].update(reference_image_id=image_id,reference_image_path=job.get('reference_image_path'),reference_semantic_validation=job.get('reference_semantic_validation'),pixverse_request_payload=request_payload)
            _persist_generation_trace(folder,job['generation_trace'][-1])
            video_id=await client.generate_from_image(image_id,active_prompt,duration=shot['duration'],quality=quality)
        else:
            request_payload={'mode':'text_to_video','prompt':active_prompt,'duration':shot['duration'],'quality':quality,'model':'v6','negative_prompt':MODEL_NEGATIVE}
            job['pixverse_request_payload']=request_payload
            job['generation_trace'][-1].update(pixverse_request_payload=request_payload)
            _persist_generation_trace(folder,job['generation_trace'][-1])
            video_id=await client.generate(active_prompt,duration=shot['duration'],quality=quality,negative_prompt=MODEL_NEGATIVE)
        url=await _poll(client,video_id); path=folder/f'{job_id}-scene-{index}-attempt-{attempt}.mp4';await _download(url,path)
        job['stage']=f'Checking scene {index+1} of {job["scenes_total"]}'
        qc=await score_video(path); score=float(qc.get('overall_quality_score',100 if not qc.get('available') else 0))
        if score>best_score:
            if best:best.unlink(missing_ok=True)
            best,best_score=path,score
        else:path.unlink(missing_ok=True)
        if not qc.get('available') or score>=85:
            job['qc_results'].append(qc);break
        failure=str(qc.get('failure_reason') or 'stability');retries=1
    job['retry_count']+=retries;job['reference_retry_count']+=reference_retries
    job['qc_results'].append(reference_score) if reference_score else None
    return best

async def _run(job_id,content,total,quality,quality_mode=False,production=None):
    job=JOBS[job_id]
    folder=Path(os.getenv('APP_DATA_DIR',str(Path(__file__).parent/'data')))/'finished_videos';folder.mkdir(parents=True,exist_ok=True)
    clip_paths=[]
    try:
        client=PixVerseClient()
        if quality_mode:
            planned=build_plan(content,total,creative_prompt=(production or {}).get("prompt","")); plan=planned['shots'];job.update(scenes_total=len(plan),visual_bible=planned['visual_bible'],generation_route=planned['route'],stage='Creating visual direction')
            for index,shot in enumerate(plan):
                clip_paths.append(await _quality_shot(client,shot,quality,folder,job_id,index,job));job['scenes_complete']=index+1
        else:
            plan=prompts(content,total,creative_prompt=(production or {}).get("prompt",""));job.update(scenes_total=len(plan),stage='Preparing scenes')
            for index,(length,prompt) in enumerate(plan):
                job['stage']=f'Generating scene {index+1} of {len(plan)}';video_id=await client.generate(prompt,duration=length,quality=quality,negative_prompt=MODEL_NEGATIVE);url=await _poll(client,video_id);path=folder/f'{job_id}-scene-{index}.mp4';await _download(url,path);clip_paths.append(path);job['scenes_complete']=index+1
        job['stage']='Rendering final video';output=folder/f'viralizer-{uuid.uuid4().hex}.mp4'
        if len(clip_paths)==1: shutil.copyfile(clip_paths[0],output)
        else: await asyncio.to_thread(_combine,clip_paths,output)
        for path in clip_paths:path.unlink(missing_ok=True)
        scores=[float(x.get('overall_quality_score',0)) for x in job['qc_results'] if isinstance(x,dict) and x.get('available')]
        job.update(status='complete',url=f'/api/finished-video/{output.name}',stage='Video ready',qc_status='complete' if scores else ('unavailable' if quality_mode else 'not_requested'),qc_score=round(sum(scores)/len(scores),1) if scores else None,best_available=bool(scores and min(scores)<85))
    except Exception as exc:
        for path in clip_paths:
            if path:path.unlink(missing_ok=True)
        job.update(status='failed',error=str(exc),stage='Video generation failed')

def start(content,total,quality,quality_mode=False,production=None):
    job_id='long-'+uuid.uuid4().hex
    JOBS[job_id]={'status':'processing','stage':'Analyzing content','scenes_complete':0,'scenes_total':0,'quality_mode':quality_mode,'generation_mode':(production or {}).get('generation_mode','text_to_video'),'qc_status':'pending' if quality_mode else 'not_requested','qc_results':[],'retry_count':0,'reference_retry_count':0}
    asyncio.create_task(_run(job_id,content,total,quality,quality_mode,production));return job_id
def status(job_id):
    return JOBS.get(job_id)