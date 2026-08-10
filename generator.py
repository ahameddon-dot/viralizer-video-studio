
import json, math, pathlib, subprocess, argparse
from PIL import Image, ImageDraw, ImageFont

W, H = 540, 960
FPS = 20

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVu/DejaVuSans.ttf"
COND = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"

def ft(path, size):
    return ImageFont.truetype(path, size)

def wrap(draw, txt, font, maxw):
    words = str(txt).split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0,0), test, font=font)[2] <= maxw:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines

def build_scenes(data):
    topic = data.get("topic", "Untitled Hot Topic")
    rank = data.get("viral_rank", "-")
    opportunity = data.get("opportunity", "High")
    competition = data.get("competition", "-")
    reach = data.get("remaining_reach", "-")
    why = data.get("why_it_matters", "This topic is accelerating across online conversations.")
    hook = data.get("hook", f"Why everyone is talking about {topic}.")
    angle = data.get("creator_angle", "Explain what changed, why it matters, and what happens next.")
    idea = data.get("video_idea", f"The story behind {topic}.")
    cta = data.get("cta", "Follow Viralizer for the next big topic.")
    return [
        (0, 4, "BREAKING HOT TOPIC", topic.upper(), f"VIRAL RANK #{rank}"),
        (4, 8, "WHY IT MATTERS", why, f"OPPORTUNITY: {opportunity.upper()}"),
        (8, 12, "REACH WINDOW", f"Estimated remaining reach: {reach}. The conversation is still moving.", f"REMAINING REACH: {reach}"),
        (12, 17, "CREATOR ANGLE", angle, f"COMPETITION: {competition}"),
        (17, 22, "BEST VIDEO IDEA", idea, "HOOK → CONTEXT → IMPACT"),
        (22, 27, "OPEN WITH THIS", hook, "ACT WHILE IT'S HOT"),
        (27, 30, "VIRALIZER.AI", cta, "HOT TOPICS → CONTENT"),
    ]

def render(data, output):
    scenes = build_scenes(data)
    duration = 30
    work = pathlib.Path("/tmp/viralizer_render")
    frames = work / "frames"
    frames.mkdir(parents=True, exist_ok=True)

    def scene_for(t):
        for s in scenes:
            if s[0] <= t < s[1]:
                return s
        return scenes[-1]

    for i in range(FPS * duration):
        t = i / FPS
        s0, s1, title, body, metric = scene_for(t)
        local = (t - s0) / max(0.1, s1 - s0)

        im = Image.new("RGB", (W, H), (7, 5, 17))
        d = ImageDraw.Draw(im, "RGBA")

        # Purple moving glows
        for radius, alpha in ((370,32),(240,42),(130,56)):
            cx = int(W*.76 + 70*math.sin(t*.25))
            cy = int(H*.23 + 45*math.cos(t*.22))
            d.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),
                      fill=(104, 42, 230, alpha))

        # Subtle grid
        for gy in range(100, H, 80):
            yy = (gy + int(t*13)) % H
            d.line((0,yy,W,yy), fill=(150,85,255,18))
        for gx in range(0, W, 90):
            xx = (gx + int(t*8)) % W
            d.line((xx,0,xx,H), fill=(150,85,255,12))

        # Header
        d.rounded_rectangle((30,28,W-30,92), radius=18,
                            fill=(13,9,29,225), outline=(132,70,255,170), width=2)
        d.text((48,47), "VIRALIZER.AI", font=ft(BOLD,23), fill="white")
        d.text((W-174,51), "HOT TOPIC", font=ft(BOLD,15), fill=(255,208,55))

        # Metric pill
        d.rounded_rectangle((36,132,W-36,179), radius=18, fill=(108,44,240,225))
        d.text((55,145), str(metric), font=ft(COND,14), fill="white")

        # Title
        ease = min(1, local*5)
        xoff = int((1-ease)*42)
        y = 235
        tf = ft(COND, 38)
        for line in wrap(d, title, tf, W-82):
            d.text((41+xoff,y), line, font=tf, fill="white")
            y += 46

        d.rounded_rectangle((42,y+18,155,y+24), radius=3, fill=(255,207,52))

        # Body
        card_y = y + 66
        d.rounded_rectangle((35,card_y,W-35,card_y+260), radius=28,
                            fill=(16,10,35,225), outline=(126,65,245,140), width=2)
        bf = ft(REG, 24)
        by = card_y + 39
        for line in wrap(d, body, bf, W-112):
            d.text((60,by), line, font=bf, fill=(233,228,244))
            by += 36

        # Momentum chart
        chart_y = 742
        d.text((40,chart_y-43), "VIRAL MOMENTUM", font=ft(BOLD,14), fill=(183,154,230))
        pts=[]
        for k in range(8):
            xx=46+k*63
            progress=max(0,min(1,local*1.5))
            yy=chart_y+94-int((k/7)**1.45*125*progress)-int(7*math.sin(t*2+k))
            pts.append((xx,yy))
        d.line(pts, fill=(184,110,255,230), width=5)
        for xx,yy in pts:
            d.ellipse((xx-5,yy-5,xx+5,yy+5), fill=(255,210,55))

        d.text((40,876), "CREATE BEFORE THE MOMENT PASSES", font=ft(BOLD,15), fill="white")
        d.rounded_rectangle((40,916,W-40,924), radius=4, fill=(255,255,255,35))
        d.rounded_rectangle((40,916,40+(W-80)*(t/duration),924),
                            radius=4, fill=(145,72,255))

        im.save(frames / f"frame_{i:04d}.jpg", quality=88)

    output = pathlib.Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg","-y",
        "-framerate",str(FPS),
        "-i",str(frames/"frame_%04d.jpg"),
        "-f","lavfi","-i","sine=frequency=110:duration=30:sample_rate=44100",
        "-filter:a","volume=0.025",
        "-c:v","libx264","-preset","veryfast","-crf","22",
        "-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","128k",
        "-shortest","-movflags","+faststart",
        str(output)
    ]
    subprocess.run(cmd, check=True)
    print(f"Created: {output}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_json")
    ap.add_argument("-o","--output", default="viralizer_hot_topic.mp4")
    args = ap.parse_args()
    with open(args.input_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    render(data, args.output)
