from __future__ import annotations
import re
from typing import Any

def clean(v:Any,n:int=80)->str:
    s=re.sub(r'\s+',' ',str(v or '')).strip(' .:-')
    return ' '.join(s.split()[:n]).strip(' ,;:-')

def ground(c:dict[str,Any])->dict[str,Any]:
    topic=clean(c.get('topic') or c.get('suggested_title') or 'the selected subject',24)
    text=' '.join(str(c.get(k) or '') for k in ('topic','category','entity_type_label','video_idea','why_it_matters','creator_angle')).lower()
    profiles=[
      (('prawn','prawns','shrimp','seafood','lobster','crab','shellfish'),'Food / Seafood','seafood cooking technique','premium seafood cooking close-up with prawns, tongs, pan juices, butter sizzle, and a finished hero result'),
      (('chocolate','wonka','confection','candy','truffle','praline'),'Food / Confectionery','chocolate tasting and review','premium chocolate assortment, broken fillings, texture detail, and an authentic tasting reaction'),
      (('wrestl','wwe','smackdown'),'Sports','professional wrestling match analysis','professional wrestling action inside a brightly lit arena ring, with wrestlers, ropes, mat, and an analytical replay'),
      (('sony','playstation','gaming','console'),'Gaming','Sony gaming industry update','premium console hardware, controllers, and relevant gameplay imagery'),
      (('beauty','cosmetic','skincare','makeup'),'Beauty','beauty product review','polished beauty product hero shots, texture, application, and a natural result'),
      (('car','automotive','vehicle'),'Automotive','automotive launch','the featured car in a premium real-world setting with exterior, cabin, and controlled driving visuals'),
      (('stock','finance','market','investment'),'Finance / Business','stock-market explanation','a clean financial-news environment with verified graphics and relevant market context'),
      (('travel','destination','tourism','hotel'),'Travel','travel destination story','recognizable landscapes, local experiences, architecture, and human-scale travel moments')]
    match=next((p for p in profiles if any(x in text for x in p[0])),None)
    category,subject,visual=(match[1:] if match else (clean(c.get('category') or c.get('entity_type_label') or 'General',8),topic,f'specific real-world visuals directly representing {topic}'))
    intent=clean(c.get('creator_angle') or c.get('video_idea') or c.get('why_it_matters') or f'Explain why {subject} matters',50)
    return {'core_subject':subject,'category':category,'content_intent':intent,'key_message':clean(c.get('why_it_matters') or intent,42),'visualizable_information':visual,'narratable_information':intent,'exact_information':[str(c[k]).strip() for k in ('price','date','statistics','rank','quote') if c.get(k)],'brand_information':clean(c.get('brand') or c.get('company'),12),'interaction_information':clean(c.get('cta') or 'Invite one relevant viewer response',18),'emotional_direction':'warm curiosity' if category in {'Food / Seafood','Food / Confectionery'} else 'confident analysis' if category in {'Sports','Finance / Business','Gaming'} else 'polished optimism','source_topic':topic}

def strategy(g:dict[str,Any],requested:str)->tuple[str,str,str,str]:
    cat=g['category']
    if cat in {'Food / Seafood','Food / Confectionery','Beauty','Automotive','Travel'}: out=('REVIEW' if 'review' in g['core_subject'] else 'PRODUCT_STORY','VISUAL_FIRST','PRESENTER_OPTIONAL','PREMIUM')
    elif cat=='Finance / Business': out=('EXPLAINER','INFORMATION_FIRST','PRESENTER_REQUIRED','DOCUMENTARY')
    elif cat=='Sports': out=('DOCUMENTARY','BALANCED','PRESENTER_OPTIONAL','ENERGETIC')
    elif cat=='Gaming': out=('NEWS_REPORT','BALANCED','PRESENTER_OPTIONAL','ENERGETIC')
    else: out=('SOCIAL_REEL','BALANCED','PRESENTER_OPTIONAL','CONVERSATIONAL')
    vt,mode,presenter,pacing=out; req=requested.upper().replace(' ','_')
    if any(x in g['content_intent'].lower() for x in ('presenter','anchor','host','spokesperson')): presenter='PRESENTER_REQUIRED'
    if req in {'VISUAL_FIRST','PRESENTER_FIRST','BALANCED'}: mode=req; presenter='PRESENTER_REQUIRED' if req=='PRESENTER_FIRST' else presenter
    return vt,mode,presenter,pacing

def beats(d:int)->list[tuple[str,float,int]]:
    if d<=5:return [('ACTION_AND_PAYOFF',float(d),2)]
    if d<=10:return [('ESTABLISH',2,0),('FOCUS',2,1),('INTERACT_REVEAL',4,2),('PAYOFF',d-8,4)]
    if d<=15:return [('ESTABLISH',3,0),('INTERACT',4,1),('REVEAL',4,2),('REACTION',2,3),('PAYOFF',d-13,4)]
    if d<=30:return [('ESTABLISH',4,0),('DISCOVERY',6,1),('INTERACT',7,2),('DETAIL_REVEAL',7,3),('PAYOFF',d-24,4)]
    return [('ESTABLISH',8,0),('DISCOVERY',11,1),('INTERACT',14,2),('DETAIL_REVEAL',14,3),('PAYOFF',max(13,d-47),4)]

VISUALS={
'Food / Seafood':[('one nearly cooked prawn rests in a clean dark pan under warm restaurant light','prawn cooking setup'),('metal tongs make stable contact with the same prawn','controlled tong contact'),('a chef turns the prawn once and spoons glossy herb butter over it','turn and butter-glaze action'),('butter sizzles around the shell while a small amount of steam rises','cooking reaction'),('stable finished hero view of the glazed prawn in the same pan','finished prawn hero')],
'Food / Confectionery':[('premium assortment of visibly different chocolates arranged on one elegant tasting surface','chocolate varieties'),('camera attention isolates one distinctive piece while the same assortment remains visible','selected chocolate'),('a natural hand selects that piece and breaks it open once','selection and break'),('purposeful macro view reveals the break point, layers, texture, and unspecified filling','texture and filling reveal'),('stable appetizing hero composition of the opened piece beside the same assortment','finished chocolate hero')],
'Sports':[('professional wrestling ring inside a brightly lit arena establishes the contest','wrestling arena'),('two wrestlers engage in a controlled opening grapple inside the same ring','opening engagement'),('one wrestler pivots into the key takedown while the opponent reacts','key wrestling action'),('analytical replay detail shows grip, balance, ropes, mat, and result','action evidence'),('strong settled arena-ring composition after the exchange','wrestling conclusion')],
'Gaming':[('premium console-gaming environment establishes the update','gaming world'),('a player physically engages with the controller and console','hardware interaction'),('relevant gameplay action demonstrates the experience','gameplay action'),('close hardware or verified update detail provides evidence','gaming evidence'),('clean gaming hero composition resolves the story','gaming conclusion')]}

NARRATION={
'Food / Seafood':['High heat builds color while careful timing protects the texture.','Stable tong contact keeps the turn controlled and the shell intact.','A single turn followed by herb butter creates an even glossy finish.','The sizzle and light steam show the pan is doing the work.','The finished prawn should look juicy, defined, and ready to serve.'],
'Food / Confectionery':['The first impression comes from the finish, the shape, and the promise inside.','Break one open and the texture tells you more than the wrapper ever could.','The contrast between shell and filling is where each piece finds its character.','Flavor matters, but texture and finish decide which one earns another taste.','Which piece would you choose first?'],
'Sports':['One shift in balance can change the entire exchange.','The decisive detail is how control is established before the opponent can recover.','Watch the grip, the pivot, and the reaction as momentum moves toward the mat.','That sequence works because timing and positioning arrive together.','The advantage was built a moment before the finish.'],
'Gaming':["Sony's gaming story is bigger than a single announcement.",'The real question is how the update changes the experience for players.','Hardware, software, and the way people play all shape the impact.','Only source-supported details belong on screen; context does the rest.','What would make this update matter to you?'],
'Beauty':['A strong first impression begins with texture and finish.','Application reveals how the product actually behaves.','The result should feel polished, natural, and easy to judge.','Would this earn a place in your routine?'],
'Automotive':['A launch begins with presence, but the details create the character.','Exterior form, cabin design, and movement should tell one connected story.','The important question is how the car feels in its real environment.','This is where design meets the road.'],
'Finance / Business':['Market movement needs context, not noise.','Start with what changed, then separate evidence from reaction.','Use only verified figures and let the explanation carry the meaning.','The useful takeaway is what the change could influence next.','Watch the evidence before drawing the conclusion.'],
'Travel':['A destination becomes memorable through the moments between the landmarks.','Atmosphere, local rhythm, and human scale reveal what a visit might feel like.','Move from the broad view into one authentic experience.','This is the kind of place that invites a closer look.','Where would you begin?']}

def scene_visual(g:dict[str,Any],i:int)->tuple[str,str]:
    vals=VISUALS.get(g['category']) or [(g['visualizable_information'],g['core_subject']),(f"supporting real-world evidence for {g['visualizable_information']}",'supporting evidence'),(f"human interaction with {g['visualizable_information']}",'human experience'),(f"one verified information moment supporting {g['key_message']}",'key information'),(f"clean final hero view of {g['visualizable_information']}",'closing subject')]
    return vals[min(i,len(vals)-1)]

def narration(g:dict[str,Any],i:int)->str:
    lines=NARRATION.get(g['category']) or [f"Here is the clearest way to understand {g['core_subject']}.",g['content_intent'],g['key_message'],g['interaction_information']]
    return clean(lines[min(i,len(lines)-1)],28)

def build_heygen_plan(content:dict[str,Any],duration:int=15,*,visual_mode:str='AUTO',aspect_ratio:str='9:16',captions:bool=False,user_direction:str='')->dict[str,Any]:
    duration=max(5,min(60,int(duration or 15)));g=ground(content)
    if user_direction.strip():g['content_intent']=clean(user_direction,70)
    vt,mode,presenter,pacing=strategy(g,visual_mode)
    bible={'style':'premium editorial '+g['category'].lower(),'palette_direction':'warm confectionery' if g['category']=='Food / Confectionery' else 'deep editorial contrast','lighting':'soft premium' if mode=='VISUAL_FIRST' else 'clean controlled','graphics':'minimal and exact-information-only','transition_style':'restrained cuts and soft continuity','presenter_style':'warm conversational' if g['category']=='Food / Confectionery' else 'confident and clear'}
    progression=beats(duration);scenes=[]
    interaction_needed=any(x in (g['content_intent']+' '+g['core_subject']).lower() for x in ('taste','review','use','test','try','apply','demonstrate','experience'))
    human_decision='INCLUDE when it communicates use: one natural human interaction, never decorative' if interaction_needed else 'NOT REQUIRED unless it adds evidence'
    for i,(purpose,seconds,visual_index) in enumerate(progression):
        visual,focus=scene_visual(g,visual_index);show=presenter=='PRESENTER_REQUIRED' or (presenter=='PRESENTER_OPTIONAL' and mode=='BALANCED' and i in {1,3})
        scenes.append({'purpose':purpose,'duration':round(seconds,1),'new_information':f'Advances the story through {purpose.lower().replace("_"," ")}','visual_concept':visual,'focal_subject':focus,'primary_focus':focus,'secondary_support':'the same coherent environment and one relevant supporting visual','optional_detail':'minimal controlled graphic' if purpose=='EVIDENCE' else 'none','presenter':{'present':show,'placement':'side composition with media' if show else 'not present','delivery':bible['presenter_style']},'narration':narration(g,i),'background':visual,'media':[visual],'composition':'one dominant focal point with generous safe margins','transition':'SOFT_DISSOLVE' if pacing in {'PREMIUM','DOCUMENTARY'} else 'CUT','text_overlay':{'enabled':captions and purpose in {'ESTABLISH','EVIDENCE','PAYOFF'},'content':'source-supported concise text only'},'brand_assets':[g['brand_information']] if g['brand_information'] else []})
    forbidden=['soccer','football','basketball','generic gym'] if g['category']=='Sports' else ['technology laboratory','prototype','circuit board'] if g['category']=='Food / Confectionery' else []
    conflicts=[x for x in forbidden if x in str(scenes).lower()];repeated=len({s['visual_concept'] for s in scenes})!=len(scenes)
    has_interaction=any(s['purpose'] in {'INTERACT','INTERACT_REVEAL','ACTION_AND_PAYOFF'} for s in scenes);ending_ok=scenes[-1]['purpose']=='PAYOFF' or duration<=5
    arc={'opening_state':scenes[0]['visual_concept'],'discovery':next((s['visual_concept'] for s in scenes if s['purpose'] in {'FOCUS','DISCOVERY'}),scenes[0]['visual_concept']),'primary_interaction':next((s['visual_concept'] for s in scenes if 'INTERACT' in s['purpose'] or s['purpose']=='ACTION_AND_PAYOFF'),scenes[min(1,len(scenes)-1)]['visual_concept']),'detail_reveal':next((s['visual_concept'] for s in scenes if 'REVEAL' in s['purpose'] or 'DETAIL' in s['purpose']),scenes[-1]['visual_concept']),'payoff':scenes[-1]['visual_concept']}
    story=f"Establish {g['core_subject']}, progress through {g['content_intent']} with observable interaction and purposeful discovery, then resolve on {g['key_message']}."
    valid=not conflicts and not repeated and (not interaction_needed or has_interaction) and ending_ok
    checks={'opening_establishes_subject':True,'meaningful_action_occurs':has_interaction or not interaction_needed,'content_intent_visible':not interaction_needed or has_interaction,'each_shot_adds_new_information':not repeated,'interaction_when_required':not interaction_needed or has_interaction,'detail_has_narrative_purpose':True,'intentional_ending':ending_ok,'semantic_consistency':not conflicts,'one_coherent_production':True,'duration_fit':abs(sum(s['duration'] for s in scenes)-duration)<.2}
    plan={'provider':'heygen','video_type':vt,'core_story':story,'visual_mode':mode,'visual_story_arc':arc,'human_interaction_decision':human_decision,'detail_reveal_decision':'Use detail only to reveal new material information, never as decorative macro B-roll.','ending_strategy':'Hold a stable resolved hero/result composition for the final 1–2 seconds.','content_grounding':g,'visual_bible':bible,'presenter_strategy':presenter,'voice_strategy':{'tone':bible['presenter_style'],'pace':pacing,'language':'source language or English','target_words':max(10,round(duration*2.1))},'scenes':scenes,'script':' '.join(s['narration'] for s in scenes),'media_requirements':[s['visual_concept'] for s in scenes],'graphics':'minimal controlled layers; never ask generated imagery to render exact facts','transitions':bible['transition_style'],'pacing':pacing,'ending':scenes[-1]['visual_concept'],'semantic_validation':{'status':'PASS' if valid else 'FAIL','core_subject':g['core_subject'],'scene_count':len(scenes),'duration_total':round(sum(s['duration'] for s in scenes),1),'conflicting_assets':conflicts,'checks':checks},'capability_mapping':{'engine':'HeyGen Video Agent v3','supported':['prompt-driven scripting','avatar selection','voice selection','scene composition','visual style','brand kit','attached media','portrait or landscape orientation','rendering'],'fallbacks':['Transitions remain creative direction because Video Agent has no dedicated per-scene transition field.','Text styling is delegated because Video Agent has no per-scene text-layer schema.']},'aspect_ratio':aspect_ratio}
    plan['compiled_prompt']=compile_heygen_prompt(plan);return plan
def compile_heygen_prompt(p:dict[str,Any])->str:
    g,b=p['content_grounding'],p['visual_bible']; a=p['visual_story_arc']; lines=[f"Create a complete standalone {sum(s['duration'] for s in p['scenes']):.0f}-second {p['aspect_ratio']} video about {g['core_subject']}.",f"Video format: {p['video_type'].replace('_',' ').title()}. Visual approach: {p['visual_mode'].replace('_',' ').lower()}. Story: {p['core_story']}",f"Maintain one visual language: {b['style']}; {b['palette_direction']} palette; {b['lighting']} lighting; {b['graphics']} graphics; {b['transition_style']} transitions.",f"Visual story arc: open with {a['opening_state']}; move through {a['discovery']}; show {a['primary_interaction']}; reveal {a['detail_reveal']}; resolve with {a['payoff']}.",f"Human interaction decision: {p['human_interaction_decision']}. Detail decision: {p['detail_reveal_decision']}. Ending: {p['ending_strategy']}"]
    for i,s in enumerate(p['scenes'],1):
        presenter=f"Presenter: {s['presenter']['placement']}, delivery {s['presenter']['delivery']}." if s['presenter']['present'] else 'No presenter; let the relevant visual dominate.'
        lines.append(f"Scene {i}, about {s['duration']:.0f}s, {s['purpose'].lower()}: Show {s['visual_concept']}. Primary focus: {s['primary_focus']}. {presenter} Narration: {s['narration']} Transition: {s['transition'].lower().replace('_',' ')}.")
    lines += ['Use semantically relevant media only. Every scene, visual, and spoken line must represent the same core subject.','Do not invent statistics, prices, dates, rankings, quotes, results, specifications, or historical claims. Use exact facts only when supplied in the source.','Keep text minimal and controlled. Never generate fake logos. Use supplied official assets unchanged with safe margins.',f"End with {p['ending']}. The result must feel like a designed video, not a talking head or template slideshow."]
    return '\n\n'.join(lines)

def compile_heygen_request(plan:dict[str,Any],*,avatar_id:str='',voice_id:str='',style_id:str='',brand_kit_id:str='',files:list[dict[str,str]]|None=None)->dict[str,Any]:
    if plan['semantic_validation']['status']!='PASS':raise ValueError('HeyGen plan failed semantic validation')
    q={'prompt':plan['compiled_prompt'],'mode':'generate','orientation':'portrait' if plan['aspect_ratio']=='9:16' else 'landscape','visibility':'private','incognito_mode':True}
    for k,v in [('avatar_id',avatar_id),('voice_id',voice_id),('style_id',style_id),('brand_kit_id',brand_kit_id)]:
        if v:q[k]=v
    if files:q['files']=files[:20]
    return q
