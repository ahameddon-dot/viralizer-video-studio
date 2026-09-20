import asyncio, json, os, re, shutil, subprocess, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx
from creative_story_qc import score_whole_video_creative_qc
from creative_revision_director import classify_creative_failure, route_revision
from human_identity_lock import (
    apply_human_identity_lock,
    derive_human_identity_lock,
    identity_negative_constraints,
    identity_qc_decision,
)
from human_reference_identity import (
    human_reference_identity_decision,
    score_human_reference_identity,
    strengthen_human_reference_prompt,
)
from pixverse_client import PixVerseClient, build_video_prompt
from quality_pipeline import build_plan, repair_prompt, score_continuity, score_human_identity, score_reference, score_video
from visual_generation_control import (
    PixVerseProvider,
    assembly_eligibility,
    configured_reference_provider,
    qc_decision,
)

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

def _trim_clip(path:Path,duration:int)->Path:
    trimmed=path.with_name(path.stem+'-trimmed.mp4')
    result=subprocess.run(['ffmpeg','-y','-i',str(path),'-t',str(duration),'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(trimmed)],capture_output=True,text=True)
    if result.returncode: raise RuntimeError('Could not trim the generated storyboard shot.')
    path.unlink(missing_ok=True)
    return trimmed

def _frame_bytes(path:Path,position:str)->bytes:
    if not shutil.which('ffmpeg'): raise RuntimeError('FFmpeg is required for continuity inspection.')
    frame=path.with_name(path.stem+f'-{position}.jpg')
    command=['ffmpeg','-y']
    if position=='end':command += ['-sseof','-0.08']
    command += ['-i',str(path),'-frames:v','1','-q:v','2',str(frame)]
    result=subprocess.run(command,capture_output=True)
    if result.returncode or not frame.exists():raise RuntimeError(f'Could not extract the {position} frame for continuity QC.')
    data=frame.read_bytes();frame.unlink(missing_ok=True);return data

async def _quality_shot(provider,shot,quality,folder,job_id,index,job,aspect_ratio="9:16",previous_end=None):
    client=provider.client
    reference_bytes=None; reference_score=None; reference_retries=0; route=shot['route']
    preflight=shot.get('preflight_consistency') or {"status":"FAIL","reason":"Missing shot consistency validation"}
    job.update(current_job_id=job_id,generation_mode=route,core_subject=shot.get('shot_specification',{}).get('core_subject'),visual_concept=shot.get('motion_debug',{}).get('selected_visual_concept'),shot_specification=shot.get('shot_specification'),reference_image_prompt=shot.get('reference_prompt'),reference_prompt_consistency=preflight,final_pixverse_prompt=shot.get('motion_prompt'))
    job.setdefault('generation_trace',[]).append({'job_id':job_id,'scene_index':index,'core_subject':job.get('core_subject'),'category':shot.get('shot_specification',{}).get('category'),'visual_concept':job.get('visual_concept'),'concrete_action':shot.get('motion_debug',{}).get('concrete_visual_action'),'generation_mode':route,'shot_specification':shot.get('shot_specification'),'reference_image_prompt':shot.get('reference_prompt'),'reference_prompt_consistency':preflight,'final_pixverse_prompt':shot.get('motion_prompt')})
    if preflight.get('status')!='PASS' or str(shot.get('motion_semantic_qc') or '').upper()!='PASS':
        raise RuntimeError(f"Shot {shot.get('shot_id')} failed motion semantic preflight and was blocked.")
    if route!='image_to_video':
        raise RuntimeError(f"Shot {shot.get('shot_id')} has no approved controlled-reference route.")
    job['stage']=f'Preparing reference frame {index+1} of {job["scenes_total"]}'
    reference_provider=configured_reference_provider()
    if not reference_provider.capabilities.supports_generation:
        raise RuntimeError('Reference image generation is not configured; assembly is blocked.')
    reference_prompt=shot['reference_prompt']
    human_reference_spec=shot.get('human_reference_identity_spec') or {}
    reference_identity_qc=None
    max_reference_attempts=3
    for reference_attempt in range(max_reference_attempts):
        reference_bytes=await reference_provider.generate(reference_prompt,previous_end if shot.get('reuse_previous_end_frame') else None)
        if human_reference_spec:
            reference_identity_qc=await score_human_reference_identity(reference_bytes,human_reference_spec)
            identity_reference_decision=human_reference_identity_decision(reference_identity_qc,reference_attempt,max_reference_attempts)
            job.setdefault('reference_identity_qc_results',[]).append(reference_identity_qc)
            job['reference_identity_qc_status']=identity_reference_decision['status']
            if identity_reference_decision['status']!='PASS':
                if identity_reference_decision['status']=='REFERENCE_IDENTITY_QC_UNAVAILABLE':
                    raise RuntimeError(f"Shot {shot.get('shot_id')} reference identity QC was unavailable; reference was blocked before semantic QC.")
                if identity_reference_decision['status']=='REFERENCE_PROVIDER_IDENTITY_LIMITATION':
                    raise RuntimeError(f"REFERENCE_PROVIDER_IDENTITY_LIMITATION: Shot {shot.get('shot_id')} failed reference identity QC after {max_reference_attempts} capped attempts.")
                reference_retries+=1
                reference_prompt=strengthen_human_reference_prompt(
                    shot['reference_prompt'],
                    identity_reference_decision['failed_gates'],
                    str(reference_identity_qc.get('corrective_instruction') or ''),
                )
                continue
        reference_score=await score_reference(reference_bytes,shot.get('reference_qc_spec'))
        reference_decision=qc_decision(reference_score)
        if reference_decision['status']=='PASS':break
        reference_retries+=1
        reference_prompt=repair_prompt(reference_prompt,reference_decision['correction'])
    else:
        reference_decision={'status':'REGENERATE','correction':'Reference retry cap reached'}
    if reference_decision['status']!='PASS':
        raise RuntimeError(f"Shot {shot.get('shot_id')} reference QC failed: {reference_decision['correction']}")
    reference_path=folder/f"reference-{job_id}-{index}.png";reference_path.write_bytes(reference_bytes)
    job['reference_image_path']=str(reference_path);job['reference_image_url']=f"/api/video/reference/{job_id}/{index}"
    job['reference_semantic_validation']={'status':'PASS','semantic_alignment_score':reference_score.get('semantic_alignment_score'),'detected_subjects':reference_score.get('detected_subjects',[]),'conflicting_objects':reference_score.get('conflicting_objects',[]),'reason':''}
    if reference_identity_qc:
        job['reference_identity_qc']=reference_identity_qc
    human_identity_lock=await derive_human_identity_lock(reference_bytes,shot)
    if human_identity_lock.get('identity_authority_conflict'):
        reasons='; '.join(human_identity_lock.get('identity_authority_conflict_reasons') or [])
        raise RuntimeError(f"APPROVED_REFERENCE_IDENTITY_CONFLICT: Shot {shot.get('shot_id')} reference conflicts with approved story identity evidence: {reasons}")
    identity_negative=identity_negative_constraints(human_identity_lock)
    job['human_identity_lock']=human_identity_lock
    job['identity_qc_criteria']=[
        'SAME_PERSON','GENDER_PRESENTATION_PRESERVED','FACE_PRESERVED','HAIR_PRESERVED',
        'CLOTHING_PRESERVED','BODY_BUILD_PRESERVED','SUBJECT_COUNT_PRESERVED',
    ] if human_identity_lock else []
    max_video_attempts=2
    best=None;best_score=-1;retries=0;failure='';accepted_qc=None;accepted_identity_qc=None;accepted_continuity=None;accepted_end=None
    for attempt in range(max_video_attempts):
        job['stage']=f'Generating scene {index+1} of {job["scenes_total"]}' if attempt==0 else f'Improving scene {index+1} of {job["scenes_total"]}'
        base_prompt=shot['motion_prompt']
        active_prompt=apply_human_identity_lock(base_prompt,human_identity_lock,retry=attempt>0)
        if attempt>0 and not human_identity_lock:
            active_prompt=repair_prompt(base_prompt,failure)
        active_negative=', '.join(item for item in (MODEL_NEGATIVE,identity_negative) if item)
        generated=await provider.generate_shot(motion_prompt=active_prompt,text_prompt=shot['prompt'],start_reference=reference_bytes,end_reference=None,duration=shot.get('provider_duration',shot['duration']),aspect_ratio=aspect_ratio,quality=quality,negative_prompt=active_negative)
        video_id=generated['video_id'];job['reference_image_id']=generated.get('image_id')
        request_payload={'mode':generated['mode'],'image_id':generated.get('image_id'),'prompt':active_prompt,'negative_prompt':active_negative,'duration':shot.get('provider_duration',shot['duration']),'quality':quality,'model':'v6','motion_mode':'normal','seed':0,'storyboard_duration':shot['duration'],'provider_controls':generated.get('controls',{}),'provider_capabilities':generated['capabilities'],'human_identity_lock':human_identity_lock}
        job['pixverse_request_payload']=request_payload;job['generation_trace'][-1].update(reference_image_id=generated.get('image_id'),reference_image_path=job.get('reference_image_path'),reference_semantic_validation=job.get('reference_semantic_validation'),pixverse_request_payload=request_payload);_persist_generation_trace(folder,job['generation_trace'][-1])
        url=await _poll(client,video_id); path=folder/f'{job_id}-scene-{index}-attempt-{attempt}.mp4';await _download(url,path)
        if shot.get('provider_duration',shot['duration'])>shot['duration']:
            path=_trim_clip(path,shot['duration'])
        job['stage']=f'Checking scene {index+1} of {job["scenes_total"]}'
        if human_identity_lock:
            identity_qc=await score_human_identity(reference_bytes,path,human_identity_lock)
            identity_decision=identity_qc_decision(identity_qc,attempt,max_video_attempts)
            job.setdefault('identity_qc_results',[]).append(identity_qc)
            job['identity_qc_status']=identity_decision['status']
            if identity_decision['status']!='PASS':
                path.unlink(missing_ok=True)
                if identity_decision['status']=='IDENTITY_QC_UNAVAILABLE':
                    raise RuntimeError(f"Shot {shot.get('shot_id')} identity QC was unavailable; later QC and assembly were blocked.")
                failure='IDENTITY_DRIFT: '+', '.join(identity_decision['failed_checks'])
                retries=1
                if identity_decision['status']=='PROVIDER_IDENTITY_LIMITATION':
                    raise RuntimeError(f"PROVIDER_IDENTITY_LIMITATION: Shot {shot.get('shot_id')} failed human identity preservation after {max_video_attempts} capped attempts.")
                continue
            accepted_identity_qc=identity_qc
        qc=await score_video(path,shot.get('visual_qc_spec'));score=float(qc.get('overall_quality_score',0))
        first_frame=_frame_bytes(path,'start');end_frame=_frame_bytes(path,'end')
        continuity={'available':True,'decision':'PASS','overall_quality_score':100}
        if previous_end is not None:
            continuity=await score_continuity(previous_end,first_frame,shot.get('continuity_qc_spec'))
        action_result_fields=('ACTION_CLEAR','ACTION_ARTICLE_SPECIFIC','RESULT_VISIBLE','RESULT_MATCHES_EVIDENCE','CAUSE_EFFECT_CLEAR','PAYOFF_NON_GENERIC')
        action_result_required=bool((shot.get('visual_qc_spec') or {}).get('action_result_qc_required'))
        action_result_pass=not action_result_required or all(str(qc.get(field) or '').upper()=='PASS' for field in action_result_fields)
        qc_pass=bool(qc.get('available') and score>=85 and qc.get('decision','PASS')=='PASS' and action_result_pass)
        continuity_pass=bool(continuity.get('available') and float(continuity.get('overall_quality_score',0))>=85 and continuity.get('decision','PASS')=='PASS')
        if qc_pass and continuity_pass:
            best=path;best_score=score;accepted_qc=qc;accepted_continuity=continuity;accepted_end=end_frame;break
        path.unlink(missing_ok=True)
        if not action_result_pass:
            failed_action_fields=[field for field in action_result_fields if str(qc.get(field) or '').upper()!='PASS']
            failure='Action/result QC failed: '+', '.join(failed_action_fields)+'. Make the supported post-action result clearly visible without symbolic substitutes.'
        else:
            failure=str((continuity if not continuity_pass else qc).get('corrective_instruction') or (continuity if not continuity_pass else qc).get('failure_reason') or 'stability and continuity')
        retries=1
    if accepted_qc is None or accepted_end is None:
        if best:best.unlink(missing_ok=True)
        raise RuntimeError(f"Shot {shot.get('shot_id')} failed visual or continuity QC after shot-specific regeneration: {failure}")
    job['retry_count']+=retries;job['shot_regeneration_count']=job.get('shot_regeneration_count',0)+retries;job['reference_retry_count']+=reference_retries
    job['qc_results'].extend([item for item in (reference_score,accepted_identity_qc,accepted_qc,accepted_continuity) if item is not None])
    return {'path':best,'end_frame':accepted_end,'gates':{'shot_id':shot.get('shot_id'), 'reference_qc':'PASS','identity_qc':'PASS' if human_identity_lock else 'NOT_APPLICABLE','motion_semantic_qc':'PASS','shot_visual_qc':'PASS','continuity_qc':'PASS' if previous_end is not None else 'PASS'}}

async def _run(job_id,content,total,quality,quality_mode=False,production=None):
    job=JOBS[job_id]
    folder=Path(os.getenv('APP_DATA_DIR',str(Path(__file__).parent/'data')))/'finished_videos';folder.mkdir(parents=True,exist_ok=True)
    clip_paths=[]
    try:
        client=PixVerseClient();provider=PixVerseProvider(client);aspect_ratio=(production or {}).get('aspect_ratio','9:16')
        if quality_mode:
            planned=build_plan(content,total,creative_prompt=(production or {}).get("prompt","")); plan=planned['shots'];job.update(scenes_total=len(plan),visual_bible=planned['visual_bible'],generation_route=planned['route'],stage='Creating visual direction')
            gate_records=[];previous_end=None
            for index,shot in enumerate(plan):
                result=await _quality_shot(provider,shot,quality,folder,job_id,index,job,aspect_ratio,previous_end);clip_paths.append(result['path']);previous_end=result['end_frame'];gate_records.append(result['gates']);job['scenes_complete']=index+1
            eligibility=assembly_eligibility(gate_records);job['assembly_eligibility']=eligibility
            if not eligibility['eligible']:raise RuntimeError('Final assembly blocked: '+', '.join(eligibility['failures']))
        else:
            plan=prompts(content,total,creative_prompt=(production or {}).get("prompt",""));job.update(scenes_total=len(plan),stage='Preparing scenes')
            for index,(length,prompt) in enumerate(plan):
                job['stage']=f'Generating scene {index+1} of {len(plan)}';video_id=await client.generate(prompt,duration=length,quality=quality,negative_prompt=MODEL_NEGATIVE,aspect_ratio=aspect_ratio);url=await _poll(client,video_id);path=folder/f'{job_id}-scene-{index}.mp4';await _download(url,path);clip_paths.append(path);job['scenes_complete']=index+1
        job['stage']='Rendering final video';output=folder/f'viralizer-{uuid.uuid4().hex}.mp4'
        if len(clip_paths)==1: shutil.copyfile(clip_paths[0],output)
        else: await asyncio.to_thread(_combine,clip_paths,output)
        creative_qc=None
        if quality_mode and content.get('story_understanding') and content.get('visual_story_plan'):
            job['stage']='Evaluating complete visual story'
            creative_qc=await score_whole_video_creative_qc(output,content['story_understanding'],content['visual_story_plan'])
            job['whole_video_creative_qc']=creative_qc
            if creative_qc.get('available') and creative_qc.get('final_story_pass')!='PASS':
                failure_classes=classify_creative_failure(creative_qc)
                job['whole_video_failure_classification']=failure_classes
                job['whole_video_revision_route']=route_revision(failure_classes)
        for path in clip_paths:path.unlink(missing_ok=True)
        scores=[float(x.get('overall_quality_score',0)) for x in job['qc_results'] if isinstance(x,dict) and x.get('available')]
        creative_failed=bool(creative_qc and creative_qc.get('available') and creative_qc.get('final_story_pass')!='PASS')
        job.update(status='complete',url=f'/api/finished-video/{output.name}',stage='Video ready - creative review required' if creative_failed else 'Video ready',qc_status='creative_failed' if creative_failed else ('complete' if scores else ('unavailable' if quality_mode else 'not_requested')),qc_score=round(sum(scores)/len(scores),1) if scores else None,best_available=creative_failed or bool(scores and min(scores)<85))
    except Exception as exc:
        for path in clip_paths:
            if path:path.unlink(missing_ok=True)
        job.update(status='failed',error=str(exc),stage='Video generation failed')

def start(content,total,quality,quality_mode=False,production=None):
    job_id='long-'+uuid.uuid4().hex
    JOBS[job_id]={'status':'processing','stage':'Analyzing content','scenes_complete':0,'scenes_total':0,'quality_mode':quality_mode,'generation_mode':(production or {}).get('generation_mode','text_to_video'),'qc_status':'pending' if quality_mode else 'not_requested','qc_results':[],'retry_count':0,'reference_retry_count':0,'creative_revision_count':int((content.get('article_intelligence') or {}).get('creative_revision_count') or 0),'shot_regeneration_count':0,'whole_video_revision_count':0,'credits_consumed':None}
    asyncio.create_task(_run(job_id,content,total,quality,quality_mode,production));return job_id
def status(job_id):
    return JOBS.get(job_id)
