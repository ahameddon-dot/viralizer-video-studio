from __future__ import annotations
import os
from typing import Any
import httpx

BASE='https://api.heygen.com'
class HeyGenError(RuntimeError):pass

class HeyGenClient:
    def __init__(self,key:str|None=None):
        self.key=(key or os.getenv('HEYGEN_API_KEY','')).strip()
        if not self.key:raise HeyGenError('HeyGen is not configured. Add HEYGEN_API_KEY to the server.')
    @property
    def headers(self):return {'X-Api-Key':self.key,'Content-Type':'application/json'}
    async def _json(self,response:httpx.Response)->dict[str,Any]:
        try:data=response.json()
        except ValueError:raise HeyGenError('HeyGen returned an invalid response.')
        if response.is_error or data.get('error'):
            err=data.get('error') or {};message=err.get('message') if isinstance(err,dict) else str(err)
            raise HeyGenError(message or data.get('message') or f'HeyGen request failed ({response.status_code}).')
        return data.get('data') or data
    async def avatars(self):
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(BASE+'/v2/avatars',headers=self.headers)
        return await self._json(r)
    async def voices(self):
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(BASE+'/v2/voices',headers=self.headers)
        return await self._json(r)
    async def agent_styles(self):
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(BASE+'/v3/video-agents/styles',headers=self.headers)
        return await self._json(r)
    async def generate_agent(self,payload:dict[str,Any]):
        async with httpx.AsyncClient(timeout=60) as c:r=await c.post(BASE+'/v3/video-agents',headers=self.headers,json=payload)
        data=await self._json(r);session_id=data.get('session_id')
        if not session_id:raise HeyGenError('HeyGen Video Agent did not return a session ID.')
        return str(session_id)
    async def agent_status(self,session_id:str):
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(BASE+f'/v3/video-agents/{session_id}',headers=self.headers)
        data=await self._json(r);state=str(data.get('status','')).lower();video_id=str(data.get('video_id') or '')
        failed=state in {'failed','canceled','cancelled','stopped'}
        complete=state in {'completed','complete','success','succeeded'} or bool(video_id)
        result={'status':'failed' if failed else 'complete' if complete else 'processing','stage':state or 'processing','progress':data.get('progress'),'video_id':video_id or None,'result':data}
        if video_id:
            try:
                rendered=await self.status(video_id)
                result.update(status=rendered['status'],url=rendered.get('url'),thumbnail_url=rendered.get('thumbnail_url'),render_result=rendered.get('result'))
            except HeyGenError:
                pass
        return result
    async def generate(self,script:str,avatar_id:str,voice_id:str,*,background:str='#0B1020',width:int=1080,height:int=1920):
        if not script.strip():raise HeyGenError('A narration script is required for a HeyGen presenter video.')
        avatar_id=(avatar_id or os.getenv('HEYGEN_AVATAR_ID','')).strip();voice_id=(voice_id or os.getenv('HEYGEN_VOICE_ID','')).strip()
        if not avatar_id or not voice_id:raise HeyGenError('Choose a HeyGen avatar and voice first.')
        payload={'video_inputs':[{'character':{'type':'avatar','avatar_id':avatar_id,'avatar_style':'normal'},'voice':{'type':'text','input_text':script.strip(),'voice_id':voice_id},'background':{'type':'color','value':background}}],'dimension':{'width':width,'height':height},'aspect_ratio':'9:16','test':False,'caption':False}
        async with httpx.AsyncClient(timeout=45) as c:r=await c.post(BASE+'/v2/video/generate',headers=self.headers,json=payload)
        data=await self._json(r);video_id=data.get('video_id')
        if not video_id:raise HeyGenError('HeyGen did not return a video ID.')
        return str(video_id)
    async def status(self,video_id:str):
        async with httpx.AsyncClient(timeout=30) as c:r=await c.get(BASE+'/v1/video_status.get',headers=self.headers,params={'video_id':video_id})
        data=await self._json(r);state=str(data.get('status','')).lower()
        normalized='complete' if state=='completed' else 'failed' if state in {'failed','canceled'} else 'processing'
        return {'status':normalized,'url':data.get('video_url'),'thumbnail_url':data.get('thumbnail_url'),'result':data}