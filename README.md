# daily-shorts

Fully automated daily YouTube Shorts, rendered for free on GitHub Actions.

```
cron → Gemini (script+metadata) → edge-tts (voice + word timings)
     → Wikimedia Commons (reusable video clips) → [optional hook clip]
     → FFmpeg (square footage, black 9:16 canvas, animated captions/HUD)
     → YouTube upload → history.json
```

Default niche: *surprising science and history facts* (change with the `NICHE` variable).
The video places a square, gently zooming footage window at the center of a black vertical canvas,
with cyan technical frame accents, a moving scan line and progress bar, and timed word-highlight
captions.

## Setup, in order

### 1. Keys (free)
- **Gemini**: https://aistudio.google.com/apikey → `GEMINI_API_KEY`

### 2. Try it locally (needs Python 3.12 + FFmpeg)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your Gemini key
set -a; source .env; set +a
python -m unittest discover -s tests     # offline sanity check
python -m src.main                       # dry run → output/video.mp4
```
Watch `output/video.mp4`. Tune `NICHE`, `TTS_VOICE`, `TARGET_SECONDS` until you'd post it.
Voices: `edge-tts --list-voices` (Hindi example: `hi-IN-SwaraNeural`; for Hindi captions
also use a font with Devanagari, e.g. `CAPTION_FONT="Noto Sans Devanagari"`).

### 3. Push to GitHub and run in the cloud
1. Create a repo, push this folder.
2. **Settings → Secrets and variables → Actions → Secrets**: add `GEMINI_API_KEY`.
3. **Actions → Daily Video → Run workflow** with *upload = false*.
4. Download the `video-N` artifact and compare with your local result.

### 4. YouTube upload (do last)
1. Google Cloud Console → new project → enable **YouTube Data API v3**.
2. OAuth consent screen → External → add yourself as a test user → then **Publish app → In production**
   (otherwise the refresh token expires after 7 days).
3. Credentials → Create **OAuth client ID → Desktop app** → download JSON.
4. Locally: `python scripts/get_youtube_token.py client_secret.json` → log in with the channel's account.
5. Add `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` as repo secrets.
6. Run the workflow manually with *upload = true*. The video lands in YouTube Studio as **private**.

New/unaudited API projects are forced to private by YouTube. Publish from Studio each day (it doubles as a
quality check), and apply for the API compliance audit if you want automatic public uploads.

### 5. Go daily
The cron in `.github/workflows/daily-video.yml` is already set (09:00 IST). Scheduled runs upload automatically.
The workflow commits `data/history.json` after each run, which also keeps the schedule from being auto-disabled
after 60 days of inactivity.

## Repo variables (Settings → Secrets and variables → Actions → Variables) — all optional
`NICHE`, `LANGUAGE`, `TTS_VOICE`, `TARGET_SECONDS`, `PRIVACY_STATUS` (private/unlisted/public),
`GEMINI_MODEL`, `USE_OMNI`.

## Footage source
Video clips are searched and downloaded from Wikimedia Commons without an API key. The available
selection can be smaller and less like a stock-footage library than commercial stock libraries. To
avoid silently using clips with restrictive licenses, the pipeline accepts only public-domain, CC0,
and attribution-only CC BY clips; it skips licenses such as CC BY-SA, CC BY-NC, and CC BY-ND. It
records source and license credits in `output/meta.json` and adds them to the YouTube description.
Check each file's Commons page: Commons notes that reuse terms can have errors and other restrictions
may apply. See the [MediaWiki API search](https://www.mediawiki.org/wiki/API:Search), [image
information](https://www.mediawiki.org/wiki/API:Imageinfo), and [Commons reuse
guidance](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia).

## Optional hook clip
- **Free**: drop your own `.mp4` clips (made manually in Google Flow / YouTube Shorts) into `hooks/`.
  One is picked at random as the opening shot. These user-provided clips are not covered by the
  Wikimedia Commons attribution list.
- **Paid (Gemini Omni API, no free tier, ~$0.10/sec)**: add secret `OMNI_API_KEY`, set variable `USE_OMNI=true`.
  `src/omni.py` is written from public docs for a *preview* API and has **not been tested against the live API**;
  if the call fails the run silently falls back to stock footage. Set a Google Cloud budget alert first.

## Project layout
```
src/main.py        orchestration            src/render.py      FFmpeg assembly
src/script_gen.py  Gemini script JSON       src/captions.py    ASS captions
src/tts.py         edge-tts + timings       src/youtube.py     upload
src/footage.py     Commons video download   src/omni.py        optional hook
tests/             offline FFmpeg smoke test
```

## Quality & policy notes
- Review the first weeks of videos before making them public; fully automated, repetitive content can be
  treated as "inauthentic / mass-produced" by YouTube. Vary topics, hooks, voices.
- The prompt asks Gemini for true facts only, but LLMs can still be wrong. Spot-check scripts in `output/meta.json`.
- Check the source and license credits for every Commons clip before publishing.
