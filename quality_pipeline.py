from __future__ import annotations

import base64, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any
import httpx
from qc_score_normalization import normalize_qc_scores

from generation_router import choose_generation_route
from human_reference_identity import build_human_reference_identity_spec
from motion_director import build_motion_plan, build_shot_specification, compile_reference_image_prompt as compile_legacy_reference_prompt, validate_shot_consistency
from visual_generation_control import (
    build_reference_qc_spec,
    compile_reference_prompt,
    continuity_qc_spec,
    enrich_storyboard_frames,
)

PURPOSES=("hero hook","context","technique or development","important detail","human impact","wider consequence","future implication","closing hero image")

def _partitions(total:int, allowed:tuple[int,...]=(10,8,5))->list[list[int]]:
    found=[]
    def visit(remaining:int, current:list[int])->None:
        if remaining==0:
            found.append(list(current));return
        for length in allowed:
            if length<=remaining:
                visit(remaining-length,current+[length])
    visit(total,[])
    return found

def _lengths(total:int,desired_beats:int=1)->list[int]:
    options=_partitions(total)
    if not options:
        return [max(5,min(10,total))]
    target=max(1,desired_beats)
    return min(options,key=lambda item:(abs(len(item)-target),len(item),-sum(item)))

def _story_beats(content:dict[str,Any])->list[dict[str,Any]]:
    plan=content.get("visual_story_plan") if isinstance(content.get("visual_story_plan"),dict) else {}
    beats=plan.get("story_beats") if isinstance(plan.get("story_beats"),list) else []
    return [beat for beat in beats if isinstance(beat,dict) and str(beat.get("visual") or "").strip()]

def _storyboard(content:dict[str,Any])->list[dict[str,Any]]:
    shots=content.get("storyboard") if isinstance(content.get("storyboard"),list) else []
    return enrich_storyboard_frames([shot for shot in shots if isinstance(shot,dict) and str(shot.get("visual_description") or "").strip()])

def _assign_beats(beats:list[dict[str,Any]],count:int)->list[list[dict[str,Any]]]:
    if not beats:return [[] for _ in range(count)]
    groups=[]
    for index in range(count):
        start=round(index*len(beats)/count);end=round((index+1)*len(beats)/count)
        groups.append(beats[start:max(start+1,end)])
    return groups

def build_plan(content:dict[str,Any],total:int,creative_prompt:str="")->dict[str,Any]:
    storyboard=_storyboard(content)
    if storyboard and sum(int(shot.get("duration_seconds") or 0) for shot in storyboard)==total:
        route=choose_generation_route(content,reference_available=True,production_style='premium')
        references={str(item.get("shot_id")):item for item in (content.get("reference_frame_plans") or []) if isinstance(item,dict)}
        qc_specs={str(item.get("shot_id")):item for item in (content.get("visual_qc_specs") or []) if isinstance(item,dict)}
        shots=[]
        for i,approved in enumerate(storyboard):
            length=int(approved["duration_seconds"])
            provider_duration=next((value for value in (5,8,10) if value>=length),10)
            shot_id=str(approved.get("shot_id") or f"S{i+1}")
            reference=references.get(shot_id) or {}
            shot_content=dict(content)
            shot_content.update(current_story_beat=approved.get("visual_description"),current_story_beat_index=i,shot_purpose=approved.get("purpose"),approved_storyboard_shot=approved,reference_frame_plan=reference)
            if creative_prompt: shot_content["approved_prompt"]=creative_prompt
            image_plan=build_motion_plan(shot_content,length,generation_type="image_to_video",quality_mode=True)
            text_plan=build_motion_plan(shot_content,length,generation_type="text_to_video",quality_mode=True)
            shot_spec=build_shot_specification(image_plan)
            factual=(content.get("story_understanding") or {}).get("factual_boundaries") or []
            identity_evidence={"story_understanding":content.get("story_understanding"),"visual_story_plan":content.get("visual_story_plan"),"article_intelligence":content.get("article_intelligence"),"topic":content.get("topic")}
            human_identity_spec=build_human_reference_identity_spec(approved,identity_evidence)
            reference_prompt=compile_reference_prompt(approved,reference,factual,(content.get("visual_story_plan") or {}).get("core_visual_subject") or "",human_identity_spec)
            consistency=validate_shot_consistency(shot_spec,reference_prompt,image_plan.final_prompt)
            motion_status=(image_plan.semantic_validation.get("handoff") or {}).get("status","FAIL")
            shots.append({"index":i,"shot_id":shot_id,"duration":length,"provider_duration":provider_duration,"purpose":approved.get("purpose"),"route":"image_to_video","approved_storyboard_shot":approved,"reference_frame_plan":reference,"human_identity_story_evidence":identity_evidence,"human_reference_identity_spec":human_identity_spec,"start_frame":approved.get("start_frame"),"end_frame":approved.get("end_frame"),"reuse_previous_end_frame":approved.get("reuse_previous_end_frame",False),"reference_prompt":reference_prompt,"reference_qc_spec":build_reference_qc_spec(approved,reference,factual,human_identity_spec),"motion_prompt":image_plan.final_prompt,"prompt":text_plan.final_prompt,"shot_specification":shot_spec,"visual_qc_spec":qc_specs.get(shot_id) or {},"preflight_consistency":consistency,"motion_semantic_qc":motion_status,"motion_debug":image_plan.debug()})
        for i in range(1,len(shots)):
            shots[i]["continuity_qc_spec"]=continuity_qc_spec(storyboard[i-1],storyboard[i])
        return {"visual_bible":shots[0]["reference_frame_plan"] if shots else {},"shots":shots,"route":route.public(),"shot_specifications":[shot["shot_specification"] for shot in shots],"storyboard":storyboard,"duration_strategy":{"total_seconds":total,"shot_lengths":[shot["duration"] for shot in shots],"source":"storyboard_director"}}
    beats=_story_beats(content)
    lengths=_lengths(total,len(beats) or 1)
    beat_groups=_assign_beats(beats,len(lengths))
    route=choose_generation_route(content,reference_available=True,production_style='premium')
    shots=[]
    for i,length in enumerate(lengths):
        group=beat_groups[i]
        purpose=" / ".join(str(beat.get("purpose") or "development") for beat in group) if group else PURPOSES[min(i,len(PURPOSES)-1)]
        shot_content=dict(content)
        if group:
            shot_content["current_story_beat"]=" Then ".join(str(beat.get("visual") or "").strip() for beat in group)
            shot_content["current_story_beat_index"]=i
        elif creative_prompt:
            shot_content["creator_angle"]=f"User-reviewed direction: {creative_prompt}"
        if creative_prompt:
            shot_content["approved_prompt"]=creative_prompt
        shot_content["shot_purpose"]=purpose
        image_plan=build_motion_plan(shot_content,length,generation_type="image_to_video",quality_mode=True)
        text_plan=build_motion_plan(shot_content,length,generation_type="text_to_video",quality_mode=True)
        shot_spec=build_shot_specification(image_plan)
        reference_prompt=compile_legacy_reference_prompt(shot_spec)
        consistency=validate_shot_consistency(shot_spec,reference_prompt,image_plan.final_prompt)
        shots.append({"index":i,"duration":length,"purpose":purpose,"route":route.mode,"human_identity_story_evidence":{"story_understanding":content.get("story_understanding"),"visual_story_plan":content.get("visual_story_plan"),"article_intelligence":content.get("article_intelligence"),"topic":content.get("topic")},"reference_prompt":reference_prompt,"motion_prompt":image_plan.final_prompt,"prompt":text_plan.final_prompt,"shot_specification":shot_spec,"preflight_consistency":consistency,"motion_debug":image_plan.debug()})
    return {"visual_bible":shots[0]["shot_specification"] if shots else {},"shots":shots,"route":route.public(),"shot_specifications":[shot["shot_specification"] for shot in shots],"story_beats":beats,"duration_strategy":{"total_seconds":total,"shot_lengths":lengths,"source":"visual_story_plan" if beats else "legacy_fallback"}}
def repair_prompt(prompt:str,reason:str)->str:
    fixes={'camera':'Use a locked camera or extremely slow push-in.','identity':'Reduce subject motion and preserve exact facial features, clothing and proportions.','anatomy':'Avoid close hand actions; use a waist-up composition with simple natural posture.','object':'Keep the product fixed in shape, lens count, materials and proportions.','text':'Remove all writing surfaces and keep screens hidden or black.','motion':'Add restrained breathing, fabric, reflection and background movement.'}
    addition=next((v for k,v in fixes.items() if k in reason.lower()),'Simplify the action, stabilize the camera, and preserve subject and object geometry.')
    return prompt+' Corrective direction: '+addition

async def _vision_score(images:list[bytes],kind:str,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:return {'available':False,'status':'unavailable','reason':'OPENAI_API_KEY is not configured'}
    if kind=='reference':
        rubric='core subject presence, composition match, material or wardrobe match, environment match, important objects present, forbidden objects absent, factual boundaries, no readable text, no unauthorized logos, no museum information panels, no plaques, documents, labels, or pseudo-text surfaces, no subject duplication, and no geometry or anatomy failure'
    elif kind=='human identity':
        rubric='identity match against the first authoritative reference image: same person, gender presentation, face, hair, clothing, body build and proportions, visible skin appearance, hands, and subject count'
    elif kind=='continuity':
        rubric='subject consistency, object geometry, environment, camera direction, lighting, scale, spatial relationships, and motion direction between the previous ending and next beginning'
    else:
        rubric='relevance, visual quality, motion, composition, subject stability, object stability, anatomy, camera stability, lighting, artifacts, and absence of generated information panels, plaques, documents, labels, logos, and pseudo-text surfaces'
    semantic_instruction=''
    if semantic_spec:
        semantic_instruction=(' Approved shot-level QC specification: '+json.dumps(semantic_spec,ensure_ascii=True)+'. Evaluate story beat representation, core visual subject, composition, required and forbidden objects, identity, environment, motion, anatomy/geometry, transition compatibility, story meaning, and visual impact. Also return semantic_alignment_score (0-100), detected_subjects (array), conflicting_objects (array), semantic_validation_status, decision (PASS or REGENERATE), and corrective_instruction. PASS only when the shot faithfully executes this specification; otherwise REGENERATE with one concise correction for this shot only.')
        if semantic_spec.get('action_result_qc_required'):
            semantic_instruction += (' This is a PERSON_ACTION result shot. Also return ACTION_CLEAR, ACTION_ARTICLE_SPECIFIC, RESULT_VISIBLE, RESULT_MATCHES_EVIDENCE, CAUSE_EFFECT_CLEAR, and PAYOFF_NON_GENERIC, each exactly PASS or FAIL. RESULT_VISIBLE must be FAIL when the action appears but the required post-action object state is not visibly proven.')
        if semantic_spec.get('human_identity_lock'):
            semantic_instruction += (' The first image is the approved identity source of truth and every later image is a sampled generated-video frame. Also return SAME_PERSON, GENDER_PRESENTATION_PRESERVED, FACE_PRESERVED, HAIR_PRESERVED, CLOTHING_PRESERVED, BODY_BUILD_PRESERVED, and SUBJECT_COUNT_PRESERVED, each exactly PASS or FAIL. Any replacement person, gender-presentation drift, face replacement, wardrobe or hairstyle change, body-build change, or extra person requires decision REGENERATE.')
    parts=[{'type':'input_text','text':f'Evaluate this {kind} for {rubric}.{semantic_instruction} Return only JSON with integer 0-100 scores for relevance, visual_quality, composition, stability, artifacts, overall_quality_score, plus failure_reason. Be strict. A clean professional result requires 85.'}]
    parts += [{'type':'input_image','image_url':'data:image/jpeg;base64,'+base64.b64encode(img).decode()} for img in images]
    payload={'model':os.getenv('OPENAI_QC_MODEL','gpt-4.1-mini'),'input':[{'role':'user','content':parts}],'text':{'format':{'type':'json_object'}}}
    try:
        async with httpx.AsyncClient(timeout=120) as client:r=await client.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+key},json=payload)
        if r.is_error:return {'available':False,'status':'unavailable','reason':'QC service rejected the request'}
        data=r.json(); raw=data.get('output_text','')
        if not raw:
            raw=''.join(x.get('text','') for item in data.get('output',[]) for x in item.get('content',[]) if x.get('type')=='output_text')
        score=normalize_qc_scores(json.loads(raw)); score.update(available=True,status='complete'); return score
    except Exception as exc:return {'available':False,'status':'unavailable','reason':str(exc)[:240]}

async def score_reference(image:bytes,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:return await _vision_score([image],'reference',semantic_spec)

async def score_continuity(previous_end:bytes,next_start:bytes,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:
    return await _vision_score([previous_end,next_start],'continuity',semantic_spec)

async def score_video(path:Path,semantic_spec:dict[str,Any]|None=None)->dict[str,Any]:
    with tempfile.TemporaryDirectory() as temp:
        pattern=str(Path(temp)/'frame-%02d.jpg')
        result=subprocess.run(['ffmpeg','-y','-i',str(path),'-vf','fps=1/2,scale=576:-2','-frames:v','4',pattern],capture_output=True)
        if result.returncode:return {'available':False,'status':'unavailable','reason':'Could not inspect generated frames'}
        frames=[p.read_bytes() for p in sorted(Path(temp).glob('frame-*.jpg'))]
    return await _vision_score(frames,'generated video',semantic_spec) if frames else {'available':False,'status':'unavailable','reason':'No frames available'}

async def score_human_identity(reference_image:bytes,path:Path,human_identity_lock:dict[str,Any])->dict[str,Any]:
    with tempfile.TemporaryDirectory() as temp:
        pattern=str(Path(temp)/'identity-frame-%02d.jpg')
        result=subprocess.run(['ffmpeg','-y','-i',str(path),'-vf','fps=1/2,scale=576:-2','-frames:v','4',pattern],capture_output=True)
        if result.returncode:
            return {'available':False,'status':'unavailable','reason':'Could not inspect generated frames for identity'}
        frames=[p.read_bytes() for p in sorted(Path(temp).glob('identity-frame-*.jpg'))]
    if not frames:
        return {'available':False,'status':'unavailable','reason':'No frames available for identity QC'}
    return await _vision_score([reference_image,*frames],'human identity',{'human_identity_lock':human_identity_lock})
