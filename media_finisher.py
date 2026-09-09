import asyncio, io, os, shutil, subprocess, tempfile, uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image

class MediaFinisherError(RuntimeError): pass
VOICES={"alloy","ash","ballad","coral","echo","fable","onyx","nova","sage","shimmer","verse","marin","cedar"}

async def _download(url, path):
    parsed=urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname: raise MediaFinisherError("The generated video URL is invalid.")
    try:
        async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
            async with client.stream("GET",url) as response:
                response.raise_for_status(); size=0
                with path.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>250*1024*1024: raise MediaFinisherError("The generated video is larger than 250 MB.")
                        output.write(chunk)
    except httpx.HTTPError as exc: raise MediaFinisherError(f"Could not download the generated video: {exc}") from exc

async def _speech(text, voice, path):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise MediaFinisherError("OPENAI_API_KEY is required to add speech.")
    if voice not in VOICES: raise MediaFinisherError("The selected narration voice is not supported.")
    payload={"model":os.getenv("OPENAI_TTS_MODEL","gpt-4o-mini-tts"),"voice":voice,"input":text[:4096],"instructions":"Speak clearly and energetically for a short social video. Keep a natural pace.","response_format":"mp3"}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response=await client.post("https://api.openai.com/v1/audio/speech",headers={"Authorization":f"Bearer {key}"},json=payload); response.raise_for_status(); path.write_bytes(response.content)
    except httpx.HTTPStatusError as exc:
        try: detail=exc.response.json().get("error",{}).get("message","")
        except ValueError: detail=""
        raise MediaFinisherError(detail or "OpenAI could not generate the narration.") from exc
    except httpx.HTTPError as exc: raise MediaFinisherError(f"Could not connect to the speech service: {exc}") from exc

def _ffmpeg(video, output, audio, logo):
    if not shutil.which("ffmpeg"): raise MediaFinisherError("FFmpeg is not installed on the server.")
    cmd=["ffmpeg","-y","-i",str(video)]
    if audio: cmd += ["-i",str(audio)]
    if logo: cmd += ["-i",str(logo)]
    if logo:
        index=2 if audio else 1
        cmd += ["-filter_complex",f"[{index}:v]scale='min(220,iw)':'-1'[logo];[0:v][logo]overlay=W-w-28:28:format=auto[vout]","-map","[vout]"]
    else: cmd += ["-map","0:v:0"]
    cmd += (["-map","1:a:0","-af","apad","-shortest"] if audio else ["-map","0:a?","-shortest"])
    cmd += ["-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(output)]
    if subprocess.run(cmd,capture_output=True,text=True).returncode: raise MediaFinisherError("Could not add speech and logo to the video.")

async def finish_video(video_url, narration, voice, logo_bytes):
    folder=Path(os.getenv("APP_DATA_DIR",str(Path(__file__).parent/"data")))/"finished_videos"; folder.mkdir(parents=True,exist_ok=True)
    output=folder/f"viralizer-{uuid.uuid4().hex}.mp4"
    with tempfile.TemporaryDirectory(prefix="viralizer-finish-") as name:
        temp=Path(name); video=temp/"source.mp4"; await _download(video_url,video); audio=logo=None
        if narration.strip(): audio=temp/"narration.mp3"; await _speech(narration.strip(),voice,audio)
        if logo_bytes:
            logo=temp/"logo.png"
            try:
                with Image.open(io.BytesIO(logo_bytes)) as source: source.thumbnail((1000,1000),Image.Resampling.LANCZOS); source.convert("RGBA").save(logo,"PNG")
            except Exception as exc: raise MediaFinisherError("The logo could not be read as an image.") from exc
        await asyncio.to_thread(_ffmpeg,video,output,audio,logo)
    return output