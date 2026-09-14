from __future__ import annotations

import base64, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any
import httpx

from generation_router import choose_generation_route

PURPOSES=("hero hook","context","technique or development","important detail","human impact","wider consequence","future implication","closing hero image")

def visual_bible(content:dict[str,Any])->dict[str,str]:
    text=' '.join(str(content.get(k) or '') for k in ('topic','category','video_idea','why_it_matters')).lower()
    topic=' '.join(str(content.get('topic') or content.get('suggested_title') or 'the subject').split()[:18])
    if any(x in text for x in ('iphone','photography','camera tips','mobile photography')):
        return {'topic':topic,'subject':'the same skilled photographer, charcoal jacket, natural appearance','object':'the same unbranded premium triple-lens smartphone with rear lenses visible and screen hidden','environment':'one coherent golden-hour city location with clean architecture and natural depth','lighting':'warm side light, soft lens reflections, realistic skin tones and restrained city bokeh','palette':'charcoal, warm amber, slate blue and natural skin tones','style':'premium realistic mobile-photography commercial'}
    if any(x in text for x in ('football','soccer','liverpool','match','sport')):
        return {'topic':topic,'subject':'the same focused football player in a plain dark training kit','object':'one regulation football with stable geometry','environment':'one coherent modern stadium tunnel and connected pitch','lighting':'cool tunnel light opening into clean white floodlights and subtle haze','palette':'deep navy, neutral concrete, green pitch and clean white light','style':'cinematic realistic sports documentary'}
    return {'topic':topic,'subject':'the same clearly recognizable main subject with unchanged wardrobe and proportions','object':'one story-relevant physical object with stable design and geometry','environment':'one specific coherent real-world location connected to the subject','lighting':'directional natural key light balanced by practical background sources','palette':'restrained premium editorial colors','style':'cinematic realistic editorial documentary'}

def _lengths(total:int)->list[int]:
    return {5:[5],8:[8],10:[5,5],15:[5,5,5],20:[5,5,5,5],30:[5,5,5,5,5,5],45:[8,8,8,8,8,5],60:[10,10,10,10,5,5,5,5]}[total]

def build_plan(content:dict[str,Any],total:int)->dict[str,Any]:
    bible=visual_bible(content); lengths=_lengths(total); route=choose_generation_route(content,reference_available=True,production_style='premium')
    actions=("performs one immediate physical action that creates a powerful visual hook","moves through the environment and interacts naturally with the key object","demonstrates the central idea through one precise observable action","reveals a meaningful material detail through careful hand movement and framing","reacts naturally while supporting environmental motion continues","moves into a wider composition that reveals the consequence","pauses as a motivated environmental change suggests what happens next","ends in a clean memorable composition with natural continuing motion")
    shots=[]
    for i,length in enumerate(lengths):
        camera=('slow controlled push-in' if i%3==0 else 'gentle lateral track' if i%3==1 else 'locked camera with purposeful subject movement')
        purpose=PURPOSES[min(i,len(PURPOSES)-1)]; action=actions[min(i,len(actions)-1)]
        reference=(f"Create a vertical 9:16 reference frame for shot {i+1}, {purpose}, about {bible['topic']}. Show {bible['subject']} with {bible['object']} in {bible['environment']}. Composition: one dominant focal subject, clear depth, {camera} viewpoint, and generous uncluttered negative space for later graphics without covering the face or key object. Lighting: {bible['lighting']}. Palette: {bible['palette']}. Materials and anatomy must be realistic. Preserve exact product geometry. No readable text, letters, numbers, interfaces, captions, logos or watermarks. Do not describe or imply complicated motion.")
        motion=(f"Animate the supplied reference for {length} seconds. The subject {action}. Camera: one {camera} only. Add subtle breathing, fabric, reflection and environmental movement. Maintain the exact subject identity, anatomy, object geometry, environment, composition, lighting and palette from the source image. End on a stable intentional frame. No morphing, redesign, generated text, captions, interfaces, logos or watermarks.")
        text_prompt=(f"Create one uninterrupted {length}-second vertical {bible['style']} shot about {bible['topic']}. Purpose: {purpose}. Show {bible['subject']} with {bible['object']} in {bible['environment']}. The subject {action}. Camera: one {camera}. Lighting: {bible['lighting']}. Palette: {bible['palette']}. Maintain stable identity, anatomy, object geometry and composition. Keep clean negative space for later graphics. No readable text, numbers, interfaces, logos, captions or watermarks.")
        shots.append({'index':i,'duration':length,'purpose':purpose,'route':route.mode,'reference_prompt':reference,'motion_prompt':motion,'prompt':text_prompt})
    return {'visual_bible':bible,'shots':shots,'route':route.public()}

def repair_prompt(prompt:str,reason:str)->str:
    fixes={'camera':'Use a locked camera or extremely slow push-in.','identity':'Reduce subject motion and preserve exact facial features, clothing and proportions.','anatomy':'Avoid close hand actions; use a waist-up composition with simple natural posture.','object':'Keep the product fixed in shape, lens count, materials and proportions.','text':'Remove all writing surfaces and keep screens hidden or black.','motion':'Add restrained breathing, fabric, reflection and background movement.'}
    addition=next((v for k,v in fixes.items() if k in reason.lower()),'Simplify the action, stabilize the camera, and preserve subject and object geometry.')
    return prompt+' Corrective direction: '+addition

async def _vision_score(images:list[bytes],kind:str)->dict[str,Any]:
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:return {'available':False,'status':'unavailable','reason':'OPENAI_API_KEY is not configured'}
    rubric='composition, relevance, subject accuracy, visual quality, brand accuracy, and overlay safety' if kind=='reference' else 'relevance, visual quality, motion, composition, subject stability, object stability, anatomy, camera stability, lighting, and artifacts'
    parts=[{'type':'input_text','text':f'Evaluate this {kind} for {rubric}. Return only JSON with integer 0-100 scores for relevance, visual_quality, composition, stability, artifacts, overall_quality_score, plus failure_reason. Be strict. A clean professional result requires 85.'}]
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

async def score_reference(image:bytes)->dict[str,Any]:return await _vision_score([image],'reference')

async def score_video(path:Path)->dict[str,Any]:
    with tempfile.TemporaryDirectory() as temp:
        pattern=str(Path(temp)/'frame-%02d.jpg')
        result=subprocess.run(['ffmpeg','-y','-i',str(path),'-vf','fps=1/2,scale=576:-2','-frames:v','4',pattern],capture_output=True)
        if result.returncode:return {'available':False,'status':'unavailable','reason':'Could not inspect generated frames'}
        frames=[p.read_bytes() for p in sorted(Path(temp).glob('frame-*.jpg'))]
    return await _vision_score(frames,'generated video') if frames else {'available':False,'status':'unavailable','reason':'No frames available'}