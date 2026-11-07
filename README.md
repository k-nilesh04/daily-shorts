# daily-shorts

Automated 30–60 second 3D AI animated comedy & storytelling YouTube Shorts, rendered locally or on GitHub Actions.

```
Gemini (comedy story + polished 3D-cartoon scene prompts) → edge-tts (Hinglish narration + word timings)
  → Gemini Omni Flash (matching 15-second 3D cartoon video scenes, generated sequentially)
  → FFmpeg (fullscreen 9:16 vertical video + animated karaoke subtitles)
  → optional YouTube upload (Comedy category) → topic history
```

Default niche: *Funny 3D animated short stories with cute characters (cute babies, funny cats, mischievous pets) in entertaining comedy situations*. The final video is full 1080×1920 vertical format with viral popping captions.

## Important: video-generation charges

Gemini Omni video generation is **paid** and has no free tier. Google's [current pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-omni-1.2-flash)
estimates about **$0.07 per second for 720p output**. A 45-second Short uses three 15-second scene
requests and costs about **$3.15** for video output. A 60-second Short is
about **$4.20**.

`AI_VIDEO_MAX_USD` defaults to `$3.25`. The workflow refuses a video whose estimated scene cost
exceeds that limit, so the default supports up to 45 seconds. This is an application-side estimate,
**not a provider-enforced billing cap**; actual charges can differ. Set a Google Cloud billing budget
alert (for example, $100/month) and review actual usage. At one 45-second generation per day,
expected video-generation cost is about **$94.50 per 30 days**. Local runs use paid video generation by default unless `DRY_RUN=true`; Actions render-only runs
automatically use dry-run mode. Generation is sequential with bounded
backoff retries for HTTP 429; repeated 429 errors can still mean the project's model quota, usage
tier, or billing limit needs attention. Check the project's active limits in
[AI Studio](https://aistudio.google.com/rate-limit).
Provider retry delays and exponential backoff are capped at 120 seconds per retry. A quota or
billing block must be resolved in the Google project; waiting and retrying cannot increase the
available quota.
Video-generation requests use bounded retries and polling, with a 25-minute maximum total wait
across all scenes. The Actions job is limited to 40 minutes.

To render through JSON2Video instead, set `VIDEO_PROVIDER=json2video` explicitly and provide
`JSON2VIDEO_API_KEY` and `JSON2VIDEO_IMAGE_URL`. This uses JSON2Video's image-and-text movie API:
it renders the configured still image with the generated title, then this project adds narration
and captions. It does **not** turn the scene prompts into AI-generated animation. Adding only
`JSON2VIDEO_API_KEY` does not change providers; Gemini remains the default. There is no fallback
image, so a missing `JSON2VIDEO_IMAGE_URL` stops the run instead of publishing an off-brand video.
JSON2Video plan quotas and credits apply; the Gemini cost estimate does not cover JSON2Video.

Set `DRY_RUN=true` to skip paid video-provider rendering and render locally generated test-pattern
clips instead. Script creation still uses `GEMINI_API_KEY`; dry-run only avoids the paid video
generation calls. The Actions workflow enables dry-run for manual runs with `upload = false` and
for scheduled runs until all YouTube upload secrets are configured. Once scheduled upload
credentials are present, scheduled runs use paid video generation and upload as before.

## Setup

### 1. Gemini API

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey). Enable a paid
Gemini API tier/billing for the Google Cloud project attached to that key. The same key can be used
for both script generation and Omni video generation.

For JSON2Video rendering, set `VIDEO_PROVIDER=json2video` and `JSON2VIDEO_API_KEY` in `.env`
instead. Optionally set `JSON2VIDEO_IMAGE_URL` to a public image URL. `GEMINI_API_KEY` is still
needed for generating the story and metadata.

### 2. Run on GitHub Actions

1. Add repository secret `GEMINI_API_KEY` under **Settings → Secrets and variables → Actions**.
   If you use a separate API key for video, add `OMNI_API_KEY`; otherwise the workflow uses
   `GEMINI_API_KEY` for both.
   For JSON2Video, add `JSON2VIDEO_API_KEY` and set the Actions variable `VIDEO_PROVIDER` to
   `json2video`. Optionally set `JSON2VIDEO_IMAGE_URL` as a variable.
2. The default `AI_VIDEO_MAX_USD=3.25` is set in code. To override it, add a repository Actions
   variable named `AI_VIDEO_MAX_USD` only after reviewing the current pricing.
3. Open **Actions → Daily Video → Run workflow**, select `main`, and keep `upload = false` for a
   render-only dry run. It produces a test-pattern video without paid Omni video calls. Set
   `DRY_RUN=false` locally only when you intend to use paid video generation.
4. Download the run's `video-N` artifact and inspect `video.mp4` and `meta.json`.

The story defaults to Hinglish in Latin script, the `hi-IN-MadhurNeural` voice, and 45 seconds.
Script word limits start from a conservative speaking rate of about 2.0 words per second, so a
45-second target asks Gemini for roughly 90 words. The pipeline then measures the real TTS
duration and regenerates with an adjusted budget if it lands outside the accepted window. The pipeline stops
before paid video generation when the synthesized narration is too long (more than two seconds over
the target, never above 60 seconds total) **or** more than 15% shorter than the target. Minor TTS
timing variation is allowed; the renderer loops clips to cover a small overrun. In particular, a
45-second target allows TTS output from 38.2 through 47 seconds.
Longer narration stops with a clear error before paid video generation.
Set repository variables `LANGUAGE`, `TTS_VOICE`, `TARGET_SECONDS` (30–60), `NICHE`, and
`GEMINI_MODEL` to customize them. Videos longer than 45 seconds are blocked by the default
$3.25 estimated-cost limit; increase that variable only if you approve the higher spend.

### 3. Optional YouTube upload

1. In Google Cloud Console, enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and create an OAuth client ID for a Desktop app.
3. Run `python scripts/get_youtube_token.py client_secret.json` locally with the channel account.
4. Add `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` as repository Actions secrets.
5. Test using **Run workflow** with `upload = true`. Uploads are private by default.

Scheduled runs upload automatically once all three YouTube secrets are configured. Until then,
scheduled runs produce a dry-run artifact rather than failing on missing upload credentials or
making paid video-generation calls. Manual runs requesting upload stop before paid generation
when YouTube secrets are missing.
Review generated videos and verify facts before publishing them publicly.

## Local development

Requires Python 3.12 and FFmpeg.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add Gemini key and approve video-generation spend
set -a; source .env; set +a     # Windows: load .env with your shell of choice
python -m unittest discover -s tests
python -m src.main              # generates a paid video; does not upload
```

Tests that need FFmpeg are skipped when `ffmpeg` is not on `PATH`. The offline suite must never
call a paid provider or need real credentials.

## Project layout

```
src/main.py        pipeline orchestration
src/config.py      environment-driven configuration and validation
src/script_gen.py  Hinglish story, metadata, and scene prompts
src/video_gen.py   paid Omni video generation and cost preflight
src/tts.py         narration and word timings
src/render.py      FFmpeg assembly and motion design
src/captions.py    animated word-group captions
src/history.py     topic history
src/youtube.py     private-first upload
src/util.py        logging and retry helpers
tests/             offline and mocked API tests
```

The renderer always normalizes clips to 1080×1920 at 30 fps, then adds narration and captions.
The [Gemini video guide](https://ai.google.dev/gemini-api/docs/video) documents 3–15 second video
generation through the Interactions API. This project requests 15-second, 720p, vertical clips and
adds its own narration and captions.

JSON2Video uses its [movie API](https://json2video.com/docs/v2/getting-started/quickstart) to
render a vertical still-image/title clip when selected with `VIDEO_PROVIDER=json2video`.

## Reference links

- Google AI Studio API keys: https://aistudio.google.com/apikey
- Gemini API documentation: https://ai.google.dev/gemini-api/docs
- Gemini video generation guide: https://ai.google.dev/gemini-api/docs/video
- Gemini rate limits: https://aistudio.google.com/rate-limit
- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- JSON2Video website: https://json2video.com/
- JSON2Video API quickstart: https://json2video.com/docs/v2/getting-started/quickstart
- Google Cloud Console: https://console.cloud.google.com/
- YouTube Data API v3 documentation: https://developers.google.com/youtube/v3
- YouTube upload API guide: https://developers.google.com/youtube/v3/guides/uploading_a_video
- GitHub Actions secrets documentation: https://docs.github.com/actions/security-guides/using-secrets-in-github-actions
- FFmpeg download and documentation: https://ffmpeg.org/download.html
