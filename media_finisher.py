import asyncio, io, os, re, shutil, subprocess, tempfile, uuid
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse
import httpx
from PIL import Image

class MediaFinisherError(RuntimeError): pass
VOICES={"alloy","ash","ballad","coral","echo","fable","onyx","nova","sage","shimmer","verse","marin","cedar"}

def _normalize_media_url(url: str) -> str:
    parsed = urlparse(str(url))
    if parsed.hostname == "media.pixverse.ai" and "%2f" in parsed.path.lower():
        parsed = parsed._replace(path=unquote(parsed.path))
    return urlunparse(parsed)


def _media_url_candidates(url: str) -> list[str]:
    """Keep PixVerse's returned URL intact, with a decoded-path fallback."""
    original = str(url)
    normalized = _normalize_media_url(original)
    return list(dict.fromkeys((original, normalized)))


def _media_request_headers(url: str) -> dict[str, str]:
    if urlparse(str(url)).hostname == "media.pixverse.ai":
        return {
            "User-Agent": "Mozilla/5.0 (compatible; Viralizer/1.0)",
            "Referer": "https://app.pixverse.ai/",
            "Origin": "https://app.pixverse.ai",
            "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.5",
        }
    return {}


async def _download(url, path):
    parsed=urlparse(str(url))
    if parsed.scheme != "https" or not parsed.hostname: raise MediaFinisherError("The generated video URL is invalid.")
    last_error = None
    delays = (0, 3, 7, 15)
    candidates = _media_url_candidates(str(url))
    async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
        for attempt, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            for candidate in candidates:
                try:
                    async with client.stream("GET",candidate,headers=_media_request_headers(candidate)) as response:
                        response.raise_for_status(); size=0
                        with path.open("wb") as output:
                            async for chunk in response.aiter_bytes():
                                size+=len(chunk)
                                if size>250*1024*1024: raise MediaFinisherError("The generated video is larger than 250 MB.")
                                output.write(chunk)
                    return
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    if exc.response.status_code != 404:
                        raise MediaFinisherError(f"Could not download the generated video: {exc}") from exc
                except httpx.HTTPError as exc:
                    last_error = exc
                    if attempt == len(delays) - 1:
                        raise MediaFinisherError(f"Could not download the generated video: {exc}") from exc
    raise MediaFinisherError(
        "PixVerse finished the video, but its media file is not available yet. "
        "Please retry this completed job in a moment; no new video credit is required."
    ) from last_error

def _speech_retryable(status_code: int | None) -> bool:
    return status_code is None or status_code == 429 or status_code >= 500


async def _speech(text, voice, path, instructions=None):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise MediaFinisherError("OPENAI_API_KEY is required to add speech.")
    if voice not in VOICES: raise MediaFinisherError("The selected narration voice is not supported.")
    payload={"model":os.getenv("OPENAI_TTS_MODEL","gpt-4o-mini-tts"),"voice":voice,"input":text[:4096],"instructions":instructions or "Speak clearly and energetically for a short social video. Keep a natural pace.","response_format":"mp3"}
    last_error = None
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt, delay in enumerate((0, 2, 5)):
            if delay:
                await asyncio.sleep(delay)
            try:
                response=await client.post("https://api.openai.com/v1/audio/speech",headers={"Authorization":f"Bearer {key}"},json=payload)
                response.raise_for_status()
                path.write_bytes(response.content)
                return
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _speech_retryable(exc.response.status_code) or attempt == 2:
                    try: detail=exc.response.json().get("error",{}).get("message","")
                    except ValueError: detail=""
                    raise MediaFinisherError(detail or "OpenAI could not generate the narration.") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 2:
                    raise MediaFinisherError(f"Could not connect to the speech service: {exc}") from exc
    raise MediaFinisherError("OpenAI could not generate the narration.") from last_error

def _escape_drawtext(value):
    return (value.replace("\\", "\\\\")
                 .replace(":", "\\:")
                 .replace("'", "\\'")
                 .replace("%", "\\%")
                 .replace(",", "\\,")
                 .replace("[", "\\[")
                 .replace("]", "\\]"))

def _ffmpeg(video, output, audio, logo, overlay_text="", overlay_position="bottom-center", overlay_color="white", secondary_logo=None):
    if not shutil.which("ffmpeg"): raise MediaFinisherError("FFmpeg is not installed on the server.")
    cmd=["ffmpeg","-y","-i",str(video)]
    if audio: cmd += ["-i",str(audio)]
    next_input=1
    audio_index=None
    logo_index=None
    secondary_logo_index=None
    if audio:
        audio_index=next_input
        next_input+=1
    if logo:
        logo_index=next_input
        next_input+=1
        cmd += ["-i",str(logo)]
    if secondary_logo:
        secondary_logo_index=next_input
        cmd += ["-i",str(secondary_logo)]
    font_candidates=[Path("C:/Windows/Fonts/arial.ttf"),Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")]
    font_path=next((item for item in font_candidates if item.is_file()),None)
    font_value=str(font_path).replace("\\", "/").replace(":", "\\:") if font_path else ""
    font_setting=f"fontfile='{font_value}'" if font_path else "font='sans'"
    filters=[]; video_input="[0:v]"
    if logo:
        filters += [f"[{logo_index}:v]scale='min(220,iw)':'-1'[logo]", f"{video_input}[logo]overlay=W-w-28:28:format=auto[vlogo]"]
        video_input="[vlogo]"
    if secondary_logo:
        filters += [f"[{secondary_logo_index}:v]scale='min(180,iw)':'-1'[brandlogo]", f"{video_input}[brandlogo]overlay=28:28:format=auto[vbrand]"]
        video_input="[vbrand]"
    if overlay_text:
        positions={
            "top-left":("28","28"), "top-center":("(w-text_w)/2","28"), "top-right":("w-text_w-28","28"),
            "center":("(w-text_w)/2","(h-text_h)/2"),
            "bottom-left":("28","h-text_h-28"), "bottom-center":("(w-text_w)/2","h-text_h-28"), "bottom-right":("w-text_w-28","h-text_h-28"),
        }
        x,y=positions.get(overlay_position,positions["bottom-center"])
        safe_text=_escape_drawtext(overlay_text)
        filters.append(f"{video_input}drawtext={font_setting}:text='{safe_text}':fontcolor={overlay_color}:fontsize=48:line_spacing=12:box=1:boxcolor=black@0.58:boxborderw=16:x={x}:y={y}[vtext]")
        video_input="[vtext]"
    if filters: cmd += ["-filter_complex",";".join(filters),"-map",video_input]
    else: cmd += ["-map","0:v:0"]
    cmd += (["-map",f"{audio_index}:a:0","-af","apad","-shortest"] if audio else ["-map","0:a?","-shortest"])
    cmd += ["-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(output)]
    completed=subprocess.run(cmd,capture_output=True,text=True)
    if completed.returncode: raise MediaFinisherError("Could not add the selected speech, logo, or text overlay to the video.")
async def finish_video(video_url, narration, voice, logo_bytes, overlay_text="", overlay_position="bottom-center", overlay_color="white", secondary_logo_bytes=None):
    folder=Path(os.getenv("APP_DATA_DIR",str(Path(__file__).parent/"data")))/"finished_videos"; folder.mkdir(parents=True,exist_ok=True)
    output=folder/f"viralizer-{uuid.uuid4().hex}.mp4"
    with tempfile.TemporaryDirectory(prefix="viralizer-finish-") as name:
        temp=Path(name); video=temp/"source.mp4"
        if str(video_url).startswith('/api/finished-video/'):
            filename=Path(str(video_url)).name
            if not re.fullmatch(r'viralizer-[a-f0-9]{32}\.mp4',filename): raise MediaFinisherError("The generated video URL is invalid.")
            local=folder/filename
            if not local.is_file(): raise MediaFinisherError("The generated video file was not found.")
            shutil.copy2(local,video)
        else: await _download(video_url,video)
        audio=logo=secondary_logo=None
        if narration.strip(): audio=temp/"narration.mp3"; await _speech(narration.strip(),voice,audio)
        if logo_bytes:
            logo=temp/"logo.png"
            try:
                with Image.open(io.BytesIO(logo_bytes)) as source: source.thumbnail((1000,1000),Image.Resampling.LANCZOS); source.convert("RGBA").save(logo,"PNG")
            except Exception as exc: raise MediaFinisherError("The logo could not be read as an image.") from exc
        if secondary_logo_bytes:
            secondary_logo=temp/"official-logo.png"
            try:
                with Image.open(io.BytesIO(secondary_logo_bytes)) as source: source.thumbnail((1000,1000),Image.Resampling.LANCZOS); source.convert("RGBA").save(secondary_logo,"PNG")
            except Exception as exc: raise MediaFinisherError("The official logo could not be read as an image.") from exc
        await asyncio.to_thread(_ffmpeg,video,output,audio,logo,overlay_text,overlay_position,overlay_color,secondary_logo)
    return output
