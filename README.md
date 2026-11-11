# 🎬 Daily Shorts

> Automated 30–60 second 3D AI animated comedy YouTube Shorts — generated, rendered, and optionally uploaded, fully unattended.

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-102%20passing-brightgreen.svg)](#testing)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Cost & Billing](#cost--billing)
- [Quick Start](#quick-start)
- [GitHub Actions Setup](#github-actions-setup)
- [Configuration Reference](#configuration-reference)
- [YouTube Upload Setup](#youtube-upload-setup)
- [Local Development](#local-development)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Reference Links](#reference-links)

---

## Overview

**Daily Shorts** is a fully automated pipeline that produces vertical (1080×1920) YouTube Shorts from a single niche prompt. It handles everything end-to-end:

- **Story generation** — Gemini writes a Hinglish comedy script + scene prompts
- **Voice-over** — Edge-TTS synthesizes narration with word-level timings
- **Video generation** — Gemini Omni (or JSON2Video) renders 15-second 3D cartoon scenes
- **Rendering** — FFmpeg assembles scenes, audio, and animated karaoke captions into a final MP4
- **Upload** — Optional private-first YouTube upload with topic history tracking

The pipeline runs on **GitHub Actions** (daily cron) or **locally**, and adapts automatically to TTS timing variations so the final video never exceeds 50 seconds.

### Default Niche
> *Funny 3D animated short stories with cute characters (cute babies, funny cats, mischievous pets) in entertaining comedy situations.*

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────┐     ┌──────────┐
│  Gemini     │────▶│  Edge-TTS    │────▶│  Gemini Omni    │────▶│  FFmpeg  │────▶│  YouTube │
│  Flash-Lite │     │  (voice +    │     │  (15s scenes)   │     │  (render │     │  (upload)│
│  (script)   │     │   timings)   │     │  or JSON2Video  │     │  + subs) │     │          │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────────┘     └──────────┘
```

### Pipeline Steps

| Step | Module | Description |
|------|--------|-------------|
| 1 | `script_gen.py` | Generates story, metadata, and scene prompts (adapts word count to TTS rate) |
| 2 | `tts.py` | Synthesizes narration + word timings via Edge-TTS, normalizes audio to -14 LUFS |
| 3 | `video_gen.py` | Generates 15s AI video scenes (Gemini Omni) or renders still-image (JSON2Video) |
| 4 | `render.py` | Normalizes clips, overlays audio + animated karaoke captions, outputs MP4 |
| 4b | `thumbnail.py` | Generates a custom thumbnail from the script using Gemini image generation (nano banana) |
| 4c | `captions.py` | Exports SRT subtitles alongside the video |
| 5 | `youtube.py` | Uploads video + thumbnail to YouTube (private by default) with retry + verification |
| 6 | `history.py` | Records topic to avoid repetition |
| 7 | `notify.py` | Sends email notification (Gmail SMTP) on success or failure |

### Adaptive Timing
The pipeline measures real TTS duration and regenerates the script if it falls outside the accepted window (1–50 seconds). If narration is still too long after retries, audio and captions are trimmed to the target length. Minor timing variations are handled by looping clips.

---

## Cost & Billing

### Gemini Omni (default provider)
| Duration | Scenes | Estimated Cost |
|----------|--------|----------------|
| 30s | 2 | ~$2.10 |
| 45s | 3 | ~$3.15 |
| 60s | 4 | ~$4.20 |

- **Rate**: ~$0.07/second at 720p
- **No free tier** — requires paid Google Cloud billing
- `AI_VIDEO_MAX_USD` defaults to `$3.25` (blocks >45s by default)
- This is an **application-side estimate**, not a provider-enforced cap

### JSON2Video (alternative)
- Renders a still image + narration + captions (no AI video generation)
- Avoids Gemini video rate limits entirely
- Subject to JSON2Video plan quotas/credits

### Dry Run Mode
Set `DRY_RUN=true` to skip paid video generation and render test-pattern clips instead. Script generation still uses `GEMINI_API_KEY`.

---

## Quick Start

### Prerequisites
- Python 3.12+
- FFmpeg (with ffprobe)

### Local run

```bash
git clone https://github.com/<your-username>/daily-shorts.git
cd daily-shorts
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: add GEMINI_API_KEY (and JSON2VIDEO_* if using JSON2Video)
set -a; source .env; set +a   # Windows: load .env manually
python -m unittest discover -s tests   # verify setup
python -m src.main                    # generates video (no upload)
```

### Render-only (no paid video calls)
```bash
DRY_RUN=true python -m src.main
```

---

## GitHub Actions Setup

### 1. Add Secrets
Go to **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Required | Description |
|--------|----------|-------------|
| `GEMINI_API_KEY` | ✅ Always | Gemini API key ([get one](https://aistudio.google.com/apikey)) |
| `JSON2VIDEO_API_KEY` | JSON2Video only | From [json2video.com](https://json2video.com/) |
| `HUGGINGFACE_API_KEY` | HuggingFace only | Optional — increases free inference rate limits |
| `HUGGINGFACE_API_KEY` | HuggingFace only | Optional — increases free inference rate limits |
| `OMNI_API_KEY` | Optional | Separate key for video (falls back to `GEMINI_API_KEY`) |
| `YT_CLIENT_ID` | Upload only | OAuth Desktop app client ID |
| `YT_CLIENT_SECRET` | Upload only | OAuth Desktop app client secret |
| `YT_REFRESH_TOKEN` | Upload only | From `python scripts/get_youtube_token.py` |

### 2. Add Variables (optional, all have defaults)
Go to **Settings → Secrets and variables → Actions → Variables**:

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_PROVIDER` | `gemini` | `gemini`, `json2video`, or `huggingface` |
| `JSON2VIDEO_IMAGE_URL` | — | Public image URL (required for JSON2Video) |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Script generation model |
| `OMNI_MODEL` | `gemini-omni-1.2-flash` | Video generation model |
| `THUMBNAIL_MODEL` | `gemini-2.0-flash-exp` | Thumbnail generation model (nano banana) |
| `TARGET_SECONDS` | `45` | Video length (30–60) |
| `NICHE` | funny 3D comedy stories | Content niche |
| `LANGUAGE` | `Hinglish` | Narration language |
| `TTS_VOICE` | `hi-IN-MadhurNeural` | Edge-TTS voice |
| `TTS_RATE` | `+0%` | Speech rate |
| `LAYOUT` | `fullscreen` | `fullscreen` or `frame` |
| `PRIVACY_STATUS` | `private` | `private`, `unlisted`, or `public` |
| `AI_VIDEO_MAX_USD` | `3.25` | Cost limit |

### 3. Run the workflow
1. Go to **Actions → Daily Video → Run workflow**
2. Keep `upload = false` for a render-only dry run first
3. Download the `video-N` artifact and inspect `video.mp4` + `meta.json`
4. Set `upload = true` when ready to publish

### Scheduled runs
The workflow runs daily at 03:30 UTC. Scheduled runs:
- Use **paid video generation** + **upload** if YouTube secrets are configured
- Fall back to **dry-run** (test-pattern clips) if secrets are missing

---

## Configuration Reference

All settings are driven by environment variables. See [`.env.example`](.env.example) for the full list.

### Key settings

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `TARGET_SECONDS` | `45` | 30–60 | Target video duration |
| `AI_VIDEO_MAX_USD` | `3.25` | ≥0 | Cost limit (estimate) |
| `DRY_RUN` | `false` | bool | Skip paid video generation |
| `UPLOAD` | `false` | bool | Upload to YouTube |
| `PRIVACY_STATUS` | `private` | enum | Upload privacy |

---

## YouTube Upload Setup

1. **Google Cloud Console** → Enable **YouTube Data API v3**
2. **OAuth consent screen** → Configure for Desktop app
   - Add scope: `https://www.googleapis.com/auth/youtube.upload`
   - Add your channel account as a **Test user** (if in Testing mode)
3. **Credentials** → Create **OAuth client ID** (Desktop app) → Download JSON
4. Run locally:
   ```bash
   python scripts/get_youtube_token.py client_secret.json
   ```
5. Copy the printed values to GitHub Secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`)
6. Test with **Run workflow** → `upload = true`

> ⚠️ **Testing mode tokens expire after 7 days.** Publish the OAuth app or regenerate tokens periodically.

The workflow verifies the refresh token **before** paid video generation, so expired tokens fail fast with instructions.

---

## Local Development

### Requirements
- Python 3.12+
- FFmpeg (with ffprobe)

### Commands
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add Gemini key
python -m unittest discover -s tests   # run tests (102 tests, 2 skipped without FFmpeg)
python -m src.main              # generate video (no upload)
```

### Testing
```bash
# Full suite
python -m unittest discover -s tests

# With FFmpeg installed (runs end-to-end render test)
# Install: https://ffmpeg.org/download.html
```

Tests that need FFmpeg are skipped when it's not on `PATH`. The offline suite never calls paid providers or needs real credentials.

---

## Project Structure

```
daily-shorts/
├── src/
│   ├── main.py          # Pipeline orchestration
│   ├── config.py        # Environment-driven configuration
│   ├── script_gen.py    # Story, metadata, scene prompts
│   ├── video_gen.py     # Gemini Omni / JSON2Video generation
│   ├── tts.py           # Narration + word timings (Edge-TTS) + audio normalization
│   ├── render.py        # FFmpeg assembly + motion design
│   ├── thumbnail.py     # Custom thumbnail generation (Gemini nano banana)
│   ├── captions.py      # Animated karaoke captions (ASS) + SRT export
│   ├── notify.py        # Webhook notifications (Discord/Slack/Telegram)
│   ├── youtube.py       # Private-first upload + verification + thumbnails
│   ├── history.py       # Topic history tracking
│   └── util.py          # Logging + retry helpers
├── tests/               # Offline + mocked API tests (102 tests)
├── scripts/
│   └── get_youtube_token.py  # OAuth refresh token helper
├── .github/
│   ├── workflows/
│   │   ├── daily-video.yml  # Daily cron + manual workflow
│   │   └── tests.yml        # PR test workflow
│   ├── ISSUE_TEMPLATE/      # Bug report + feature request
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
├── Dockerfile               # Container support
├── .dockerignore
├── .env.example             # Environment template
├── .editorconfig
├── .pre-commit-config.yaml
├── Makefile                 # Common dev commands
├── pyproject.toml           # Project metadata
├── requirements.txt         # Python dependencies
├── LICENSE                  # MIT
└── README.md
`

---

## Troubleshooting

### 429 Too Many Requests (video generation)
- **Cause**: Gemini Omni has no free tier; quota is too low
- **Fix**: Enable billing in Google Cloud Console, or switch to `VIDEO_PROVIDER=json2video`

### NoAudioReceived (TTS)
- **Cause**: Microsoft TTS endpoint returned no audio
- **Fix**: Check `TTS_VOICE` is valid (`edge-tts --list-voices`), retry (3× backoff built in), or try a different voice

### YouTube 403 insufficientPermissions
- **Cause**: Refresh token lacks `youtube.upload` scope
- **Fix**: Add the scope to OAuth consent screen, regenerate token with `get_youtube_token.py`

### YouTube token expired
- **Cause**: OAuth app in Testing mode expires tokens after 7 days
- **Fix**: Re-run `get_youtube_token.py` and update `YT_REFRESH_TOKEN` secret

### Script too long / too short
- **Cause**: TTS rate differs from estimate
- **Fix**: Automatic — pipeline regenerates with adjusted word budget, trims if needed

---

## Reference Links

- [Google AI Studio (API keys)](https://aistudio.google.com/apikey)
- [Gemini API documentation](https://ai.google.dev/gemini-api/docs)
- [Gemini video generation](https://ai.google.dev/gemini-api/docs/video)
- [Gemini rate limits](https://aistudio.google.com/rate-limit)
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [JSON2Video](https://json2video.com/)
- [JSON2Video API quickstart](https://json2video.com/docs/v2/getting-started/quickstart)
- [Google Cloud Console](https://console.cloud.google.com/)
- [YouTube Data API v3](https://developers.google.com/youtube/v3)
- [GitHub Actions secrets](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions)
- [FFmpeg](https://ffmpeg.org/download.html)

---

## License

MIT — see [LICENSE](LICENSE) for details.