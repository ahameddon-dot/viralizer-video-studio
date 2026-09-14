from __future__ import annotations
import re
from typing import Any


def _clean(value:Any,limit:int=60)->str:
    text=re.sub(r'\s+',' ',str(value or '')).strip(' .:-')
    text=re.sub(r'\b(?:Categories?|Viral Topic Rank|Total Audience|Estimated Remaining Views)\s*:[^.!?]*','',text,flags=re.I)
    return ' '.join(text.split()[:limit]).strip(' ,;:-')

def build_heygen_script(content:dict[str,Any],duration:int=15)->str:
    duration=max(5,min(60,int(duration or 15))); raw=_clean(content.get('topic') or content.get('suggested_title'),16); subject=_clean(raw.split(':',1)[0],5); text=' '.join(str(content.get(k) or '') for k in ('topic','category','video_idea','why_it_matters')).lower()
    idea=_clean(content.get('creator_angle') or content.get('video_idea'),42);why=_clean(content.get('why_it_matters'),42)
    if any(x in text for x in ('iphone','photography','camera tips','mobile photography')):
        if duration<=5:parts=['Better iPhone photos begin with clean light and one steady frame.']
        elif duration<=10:parts=['Your iPhone camera is powerful.','Find clean light, steady the frame, and make one subject stand out.']
        elif duration<=15:parts=['Your best camera may already be in your hand.','Find clean natural light, lock focus, steady the phone, and simplify the background.']
        else:parts=['Your best camera may already be in your hand.','For a stronger iPhone photo, begin with clean natural light and tap your subject to lock focus.','Hold the phone steady, simplify the frame, and move your position until the background supports the subject.','Try a lower angle, use reflections carefully, and take the picture at the moment the light or expression feels natural.','Small changes in light, composition, and timing can turn an everyday shot into an image people stop to see.','Which technique will you try first?']
    elif any(x in text for x in ('football','soccer','match','liverpool','sport')):
        parts=[f'Here is what matters most in the latest {subject or "football"} story.',idea or 'Look beyond the final score and watch the movement, pressure, and decisions that changed the match.',why or 'Those details explain why this moment matters beyond one result.','What stood out to you?']
    elif any(x in text for x in ('game','gaming','playstation','xbox','console')):
        parts=[f'The gaming story around {subject or "this update"} is moving quickly.',idea or 'The important change is not only what was announced, but how it affects the way people play.',why or 'That is why players and the wider industry are paying attention.','Would this change the way you play?']
    else:
        parts=[_clean(content.get('hook'),25) or f'Here is the development you need to know about {raw}.',idea,why,_clean(content.get('cta'),20) or 'What do you think happens next?']
    target=max(11,round(duration*2.15));words=[]
    for part in parts:
        if not part:continue
        remaining=target-len(words)
        if remaining<=0:break
        chunk=part.split()
        if len(chunk)>remaining:
            if words:break
            chunk=chunk[:remaining]
        words.extend(chunk)
    result=' '.join(words).strip(' ,;:-')
    if result and result[-1] not in '.!?':result+='.'
    return result

def build_presenter_direction(content:dict[str,Any],duration:int=15)->str:
    text=' '.join(str(content.get(k) or '') for k in ('topic','category')).lower()
    tone='friendly expert tutorial' if any(x in text for x in ('tips','how to','photography','guide')) else 'confident newsroom explainer' if any(x in text for x in ('news','update','industry','launch')) else 'clear, energetic social-media presenter'
    return f'{tone.capitalize()}. Medium close-up presenter, direct eye contact, natural facial expression and restrained hand gestures. Speak at a comfortable pace with short pauses between ideas. Keep the background clean with negative space for Viralizer graphics. Do not generate captions, headlines, statistics or logos inside the HeyGen video. Target duration: {duration} seconds.'