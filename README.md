# daily-shorts

Automated 30–60 second Hindi/Hinglish YouTube storytelling videos, rendered on GitHub Actions.

```
Gemini (story + scene prompts) → edge-tts (Hinglish narration + word timings)
  → Gemini Omni Flash (matching 15-second AI video scenes, generated in parallel)
  → FFmpeg (centered square video, black vertical canvas, motion graphics + captions)
  → optional private YouTube upload → topic history
```

Default niche: *surprising science and history facts*. The final video is 1080×1920, with AI-generated
portrait footage cropped into the centered square design.

## Important: video-generation charges

Gemini Omni video generation is **paid** and has no free tier. Google's [current pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-omni-1.2-flash)
estimates about **$0.07 per second for 720p output**. A 45-second Short uses three 15-second scene
requests, generated in parallel, and costs about **$3.15** for video output. A 60-second Short is
about **$4.20**. Parallel generation reduces waiting time, not cost.

`AI_VIDEO_MAX_USD` defaults to `$3.25`. The workflow refuses a video whose estimated scene cost
exceeds that limit, so the default supports up to 45 seconds. This is an application-side estimate,
**not a provider-enforced billing cap**; actual charges can differ. Set a Google Cloud billing budget
alert (for example, $100/month) and review actual usage. At one 45-second generation per day,
expected video-generation cost is about **$94.50 per 30 days**. Manual test runs also incur
generation charges even when YouTube upload is disabled.

## Setup

### 1. Gemini API

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey). Enable a paid
Gemini API tier/billing for the Google Cloud project attached to that key. The same key can be used
for both script generation and Omni video generation.

### 2. Run on GitHub Actions

1. Add repository secret `GEMINI_API_KEY` under **Settings → Secrets and variables → Actions**.
   If you use a separate API key for video, add `OMNI_API_KEY`; otherwise the workflow uses
   `GEMINI_API_KEY` for both.
2. The default `AI_VIDEO_MAX_USD=3.25` is set in code. To override it, add a repository Actions
   variable named `AI_VIDEO_MAX_USD` only after reviewing the current pricing.
3. Open **Actions → Daily Video → Run workflow**, select `main`, and keep `upload = false` for a
   render-only test. This still calls the paid video-generation API.
4. Download the run's `video-N` artifact and inspect `video.mp4` and `meta.json`.

The story defaults to Hinglish in Latin script, the `hi-IN-MadhurNeural` voice, and 45 seconds.
Set repository variables `LANGUAGE`, `TTS_VOICE`, `TARGET_SECONDS` (30–60), `NICHE`, and
`GEMINI_MODEL` to customize them. Videos longer than 45 seconds are blocked by the default
$3.25 estimated-cost limit; increase that variable only if you approve the higher spend.

### 3. Optional YouTube upload

1. In Google Cloud Console, enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and create an OAuth client ID for a Desktop app.
3. Run `python scripts/get_youtube_token.py client_secret.json` locally with the channel account.
4. Add `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` as repository Actions secrets.
5. Test using **Run workflow** with `upload = true`. Uploads are private by default.

Scheduled runs upload automatically once the YouTube secrets are configured. Scheduled runs and
manual runs requesting an upload stop before paid generation when YouTube secrets are missing.
Review generated videos and verify facts before publishing them publicly.

## Local development

Requires Python 3.12 and FFmpeg.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add Gemini key and approve video-generation spend
set -a; source .env; set +a
python -m unittest discover -s tests
python -m src.main              # generates a paid video; does not upload
```

## Project layout

```
src/main.py        pipeline orchestration
src/script_gen.py  Hinglish story, metadata, and scene prompts
src/video_gen.py   paid Omni video generation and cost preflight
src/tts.py         narration and word timings
src/render.py      FFmpeg assembly and motion design
src/captions.py    animated word-group captions
src/youtube.py     private-first upload
tests/             offline and mocked API tests
```

The [Gemini video guide](https://ai.google.dev/gemini-api/docs/video) documents 3–15 second video
generation through the Interactions API. This project requests 15-second, 720p, vertical clips and
adds its own narration and captions.
