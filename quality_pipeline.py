from __future__ import annotations

import base64, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any
import httpx

from generation_router import choose_generation_route
from motion_director import build_motion_plan, build_shot_specification, compile_reference_image_prompt, validate_shot_consistency

PURPOSES=("hero hook","context","technique or development","important detail","human impact","wider consequence","future implication","closing hero image")

def _lengths(total:int)->list[int]:
    return {5:[5],8:[8],10:[5,5],15:[5,5,5],20:[5,5,5,5],30:[5,5,5,5,5,5],45:[8,8,8,8,8,5],60:[10,10,10,10,5,5,5,5]}[total]

def build_plan(content:dict[str,Any],total:int,creative_prompt:str="")->dict[str,Any]:
    lengths=_lengths(total)
    route=choose_generation_route(content,reference_available=True,production_style='premium')
    shots=[]
    for i,length in enumerate(lengths):
        purpose=PURPOSES[min(i,len(PURPOSES)-1)]
        shot_content=dict(content)
        if creative_prompt:
            shot_content["creator_angle"]=f"User-reviewed direction: {creative_prompt}"
        shot_content["shot_purpose"]=purpose
        image_plan=build_motion_plan(shot_content,length,generation_type="image_to_video",quality_mode=True)
        text_plan=build_motion_plan(shot_content,length,generation_type="text_to_video",quality_mode=True)
        shot_spec=build_shot_specification(image_plan)
        reference_prompt=compile_reference_image_prompt(shot_spec)
        consistency=validate_shot_consistency(shot_spec,reference_prompt,image_plan.final_prompt)
        shots.append({"index":i,"duration":length,"purpose":purpose,"route":route.mode,"reference_prompt":reference_prompt,"motion_prompt":image_plan.final_prompt,"prompt":text_plan.final_prompt,"shot_specification":shot_spec,"preflight_consistency":consistency,"motion_debug":image_plan.debug()})
    return {"visual_bible":shots[0]["shot_specification"] if shots else {},"shots":shots,"route":route.public(),"shot_specifications":[shot["shot_specification"] for shot in shots]}
def repair_prompt(prompt:str,reason:str)->str:
    fixes={'camera':'Use a locked camera or extremely slow push-in.','identity':'Reduce subject motion and preserve exact facial features, clothing and proportions.','anatomy':'Avoid close hand actions; use a waist-up composition with simple natural posture.','object':'Keep the product fixed in shape, lens count, materials and proportions.','text':'Remove all writing surfaces and keep screens hidden or black.','motion':'Add restrained breathing, fabric, reflection and background movement.'}
    addition=next((v for k,v in fixes.items() if k in reason.lower()),'Simplify the action, stabilize the camera, and preserve subject and object geometry.')
    return prompt+' Corrective direction: '+addition

async def _vision_score(images:list[bytes],kind:str,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:return {'available':False,'status':'unavailable','reason':'OPENAI_API_KEY is not configured'}
    rubric='composition, relevance, subject accuracy, visual quality, brand accuracy, and overlay safety' if kind=='reference' else 'relevance, visual quality, motion, composition, subject stability, object stability, anatomy, camera stability, lighting, and artifacts'
    semantic_instruction=''
    if semantic_spec:
        semantic_instruction=(' Canonical shot specification: '+json.dumps(semantic_spec,ensure_ascii=True)+'. Also return semantic_alignment_score (0-100), detected_subjects (array), conflicting_objects (array), and semantic_validation_status. Set semantic_validation_status to PASS only when the visible subject, environment, important objects, and start state agree with the specification and no forbidden object/domain is visibly present; otherwise FAIL.')
    parts=[{'type':'input_text','text':f'Evaluate this {kind} for {rubric}.{semantic_instruction} Return only JSON with integer 0-100 scores for relevance, visual_quality, composition, stability, artifacts, overall_quality_score, plus failure_reason. Be strict. A clean professional result requires 85.'}]
    parts += [{'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(img).decode()} for img in images]
    payload={'model':os.getenv('OPENAI_QC_MODEL','gpt-4.1-mini'),'input':[{'role':'user','content':parts}],'text':{'format':{'type':'json_object'}}}
    try:
        async with httpx.AsyncClient(timeout=120) as client:r=await client.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+key},json=payload)
        if r.is_error:return {'available':False,'status':'unavailable','reason':'QC service rejected the request'}
        data=r.json(); raw=data.get('output_text','')
        if not raw:
            raw=''.join(x.get('text','') for item in data.get('output',[]) for x in item.get('content',[]) if x.get('type')=='output_text')
        score=json.loads(raw); score.update(available=True,status='complete'); return score
    except Exception as exc:return {'available':False,'status':'unavailable','reason':str(exc)[:240]}

async def score_reference(image:bytes,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:return await _vision_score([image],'reference',semantic_spec)

async def score_video(path:Path)->dict[str,Any]:
    with tempfile.TemporaryDirectory() as temp:
        pattern=str(Path(temp)/'frame-%02d.jpg')
        result=subprocess.run(['ffmpeg','-y','-i',str(path),'-vf','fps=1/2,scale=576:-2','-frames:v','4',pattern],capture_output=True)
        if result.returncode:return {'available':False,'status':'unavailable','reason':'Could not inspect generated frames'}
        frames=[p.read_bytes() for p in sorted(Path(temp).glob('frame-*.jpg'))]
    return await _vision_score(frames,'generated video') if frames else {'available':False,'status':'unavailable','reason':'No frames available'}