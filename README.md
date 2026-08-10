# Viralizer Hot Topic Video Generator

This prototype supports both the original local renderer and a PixVerse web workflow.

## MCP outline to PixVerse

The web app accepts the Hot Topic JSON produced by your MCP, converts its content into
a visual PixVerse prompt, starts a text-to-video job, polls its status, and displays the
finished video.

PixVerse output is intentionally generated as clean B-roll without visible writing.
AI video models often produce malformed letters or mixed-language pseudo-text, so accurate
captions, titles, and voiceover should be added as a deterministic post-production step.
The prompt is built as a duration-aware explanatory storyboard using the MCP hook, outline
points, context, creator angle, cause, process, impact, and conclusion. Fifteen seconds is
the recommended default when the video needs to communicate more than one idea.

The generator content panel includes an editable suggested title, editable hook suggestions,
tags and keywords, a deduplicated thumbnail selector with preview, and KPI cards for estimated
resonance, viral rank, and total audience. Estimated resonance is calculated as remaining
reach divided by total audience. Metadata edits update the JSON used by prompt generation.

## Video providers

The generator uses a shared provider interface and currently supports PixVerse, Runway, and
HeyGen Video Agent. Add provider keys to `.env` as needed:

```text
PIXVERSE_API_KEY=your_pixverse_key
RUNWAYML_API_SECRET=your_runway_key
HEYGEN_API_KEY=your_heygen_key
```

Runway uses a selected thumbnail as its image-to-video input, or text-to-video when no HTTPS
thumbnail is selected. Runway clips duration to its current 10-second API maximum. HeyGen uses
its one-shot Video Agent in portrait mode. Kling and NativeAds.ai are shown as unavailable until
official API access details are supplied; no unofficial endpoints are used.

1. Create an API key at the PixVerse API Platform.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your PixVerse API key, MCP server URL,
   MCP outline tool name, and optional bearer token.
4. Start the app: `.venv\\Scripts\\uvicorn app:app --reload` on Windows, or
   `uvicorn app:app --reload` in an activated environment.
5. Open `http://127.0.0.1:8000`.

Both API credentials stay on the server. The UI sends the entered topic to
`POST /api/topic/from-mcp`; the backend calls the configured MCP tool through Streamable
HTTP and fills its JSON into the page. Generation uses `POST /api/video/generate`, and
the browser then polls `GET /api/video/{video_id}`.

Add these MCP settings to `.env` (replace the URL and tool name with yours):

```text
MCP_SERVER_URL=http://127.0.0.1:9000/mcp
MCP_TOOL_NAME=analyze_topic
MCP_TOPIC_ARGUMENT=keyword
MCP_HOT_TOPIC_KEYS=google,twitter,US,business,entertainment
MCP_API_KEY=your_viralizer_mcp_api_key
MCP_AUTH_TOKEN=
```

Viralizer MCP uses `MCP_API_KEY`, which is sent as the required `X-API-Key` header.
`MCP_AUTH_TOKEN` is only for other MCP servers that require bearer authentication and
can be left empty for Viralizer. The MCP tool may return either a structured JSON object or
JSON text. Its output should contain `topic`, `video_idea`, `hook`, `creator_angle`, and
`why_it_matters` for the best generated prompt.

Example MCP output passed to the generation endpoint:

```json
{
  "content": {
    "topic": "Your topic",
    "video_idea": "The visual story to generate",
    "hook": "The opening hook",
    "creator_angle": "The editorial angle",
    "why_it_matters": "Supporting context"
  },
  "duration": 5,
  "quality": "720p"
}
```

## What it does
Give it one Hot Topic JSON file and it renders a 30-second vertical MP4 automatically.

## Requirements
- Python 3.10+
- Pillow
- FFmpeg
- DejaVu fonts (or change the font paths in generator.py)

## Install
pip install pillow

Install FFmpeg with your OS package manager.

## Generate
python generator.py sample_hot_topic.json -o output.mp4

## Viralizer integration
Your Hot Topic backend only needs to output these fields:

- topic
- viral_rank
- opportunity
- competition
- remaining_reach
- why_it_matters
- creator_angle
- video_idea
- hook
- cta

The next stage is to expose this generator as an internal API endpoint such as:

POST /api/video/generate

Viralizer sends the Hot Topic JSON, the backend queues the render, and the completed MP4 is returned to the Video Library.

## Daily opportunity report

The app discovers up to 50 fresh public-news candidates, deduplicates them, and saves a ranked
Top 20 discovery report. Candidates are marked as pending; this daily process does not call or
validate against Viralizer MCP. Reports are saved in `data/daily_trends/YYYY-MM-DD.json` and
displayed at the top of the web app so Viralizer validation can be added later.
Each topic row has a **Get report** button. That button validates only the selected topic through
Viralizer MCP and loads its returned outline into the editable video-generator content panel.
The adjacent **Get PDF** button requests the full structured Viralizer MCP report and downloads it
as a formatted PDF. The PDF preserves the values returned by Viralizer rather than estimating them.

## Betting Topics

The separate **BETTING TOPICS** tab scans the official public Polymarket and Kalshi market-data
APIs, removes low-value prop/noise markets, detects matching cross-market events, and enriches up
to 12 content-worthy opportunities through Viralizer MCP when the user starts a scan. It includes
search, source/category filters, sorting, Early Signals, market probability/change/volume fields,
Viralizer metrics, source links, and video/PDF actions. Market prices are always labelled as trader
pricing rather than confirmed news or guaranteed probabilities.

Optional `.env` settings:

```text
DAILY_TRENDS_ENABLED=true
DAILY_TRENDS_TIME=07:00
DAILY_CANDIDATE_LIMIT=540
DAILY_RESULT_LIMIT=20
```

The built-in scheduler runs while the server is open. If the server starts after the configured
time and today's report is missing, it starts that day's workflow automatically. The report can
also be refreshed with the **Run daily discovery** button.

Saudi and Arabic coverage is kept out of the normal daily feed and appears in the separate
**SAUDI & ARABIC TOPICS** tab. That module scans multiple worldwide English and Arabic Google News
editions covering Saudi Arabia, the Gulf, MENA, and Arabic-language business, technology, sports,
and entertainment. Original headlines remain visible, but per-topic Viralizer requests use a
concise maximum of 10 words first to improve matching for long news headlines.
The normal Hot Topics report keeps up to 30 fresh topics for Breaking News, AI, Technology,
Business, Stock Market, Investing/Money, Cryptocurrency, Startups, Creator Economy, Social Media,
Entertainment, Gaming, Sports, Beauty/Makeup, Fashion, Health, and Science. Category sub-buttons
switch the table without mixing categories. Saudi/Arabic coverage and Prediction Markets remain
independent modules in their own main tabs.

Worldwide discovery combines Google News RSS, Hacker News search, and GDELT. Topic
rows show their contributing source platforms, and matching stories across independent sources
receive additional discovery signals. Social-media intelligence is intentionally obtained from
Viralizer MCP when the user selects a topic, because Viralizer already connects those platforms.
