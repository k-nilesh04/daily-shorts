"""Daily pipeline:  script -> voice -> AI video -> render -> (upload) -> history."""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from . import (
    captions,
    config,
    history,
    huggingface,
    notify,
    render,
    script_gen,
    thumbnail,
    tts,
    video_gen,
    youtube,
)
from .util import log

NARRATION_OVERRUN_TOLERANCE_SECONDS = 5
NARRATION_UNDERRUN_TOLERANCE_RATIO = 0.15
NARRATION_UNDERRUN_TOLERANCE_MIN_SECONDS = 3
MAX_SHORT_SECONDS = 50


def _validate_narration_duration(duration: float, target_seconds: int) -> None:
    if duration <= 0:
        raise RuntimeError("Narration is empty; nothing to render")
    max_duration = min(
        target_seconds + NARRATION_OVERRUN_TOLERANCE_SECONDS,
        MAX_SHORT_SECONDS,
    )
    if duration > max_duration:
        raise RuntimeError(
            f"Narration is {duration:.1f}s; maximum allowed for TARGET_SECONDS="
            f"{target_seconds} is {max_duration}s. AI video generation was stopped "
            "to avoid paying for an overlong video."
        )
    underrun = max(
        NARRATION_UNDERRUN_TOLERANCE_MIN_SECONDS,
        target_seconds * NARRATION_UNDERRUN_TOLERANCE_RATIO,
    )
    min_duration = max(0.0, target_seconds - underrun)
    if 0 < duration < min_duration:
        log.warning(
            "Narration is %.1fs, below the %.1fs target window; the final video "
            "will be shorter than requested.",
            duration,
            float(target_seconds),
        )


def _prepare_work_dir(work: Path) -> None:
    """Reset intermediate files but keep cached scenes for a resumable retry."""
    work.mkdir(parents=True, exist_ok=True)
    for child in work.iterdir():
        if child.name == "scenes":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true", help="upload to YouTube (or set UPLOAD=true)")
    args = ap.parse_args()

    cfg = config.load()
    do_upload = args.upload or cfg.upload

    try:
        _run_pipeline(cfg, do_upload, args)
        return 0
    except Exception as error:  # noqa: BLE001
        notify.notify_failure(cfg, str(error))
        raise


def _run_pipeline(cfg: config.Config, do_upload: bool, args: argparse.Namespace) -> None:
    if do_upload:
        missing = [
            name
            for name, value in (
                ("YT_CLIENT_ID", cfg.yt_client_id),
                ("YT_CLIENT_SECRET", cfg.yt_client_secret),
                ("YT_REFRESH_TOKEN", cfg.yt_refresh_token),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "YouTube upload was requested but these credentials are missing: "
                f"{', '.join(missing)}. Add them as repository Actions secrets "
                "(Settings -> Secrets and variables -> Actions) or run without upload."
            )
        # Validate the OAuth refresh token before spending money on video
        # generation. A revoked/expired token now fails here instead of after
        # the paid render.
        youtube.verify(cfg)

    _prepare_work_dir(cfg.work_dir)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    MAX_SCRIPT_ATTEMPTS = 3
    MIN_WORDS_PER_SECOND = 1.5
    MAX_WORDS_PER_SECOND = 3.0

    voice = cfg.work_dir / "voice.mp3"
    words_per_second = script_gen.WORDS_PER_SECOND
    avoid = history.recent_topics(cfg.history_file)

    # 1. script + 2. voice, with adaptive retry based on the measured TTS rate.
    # The fixed words/second estimate is only a starting point; real narration
    # length varies with the voice and content, so regenerate with feedback
    # until the duration lands inside the accepted window.
    last_duration = None
    for attempt in range(MAX_SCRIPT_ATTEMPTS):
        meta = script_gen.generate(cfg, avoid, words_per_second=words_per_second)
        try:
            duration, words = tts.synthesize(cfg, meta["script"], voice)
        except RuntimeError:
            if attempt == MAX_SCRIPT_ATTEMPTS - 1:
                raise
            log.warning(
                "TTS failed; regenerating script (attempt %d/%d)", attempt + 2, MAX_SCRIPT_ATTEMPTS
            )
            continue
        last_duration = duration
        try:
            _validate_narration_duration(duration, cfg.target_seconds)
            break
        except RuntimeError as error:
            word_count = len(meta["script"].split())
            measured = word_count / duration if duration > 0 else words_per_second
            measured = min(MAX_WORDS_PER_SECOND, max(MIN_WORDS_PER_SECOND, measured))
            if attempt == MAX_SCRIPT_ATTEMPTS - 1:
                # Last resort: hard-trim the script to the number of words that
                # fit at the measured rate with a 10% safety margin, then
                # re-synthesize once more before giving up.
                target_words = max(1, int(cfg.target_seconds * measured * 0.9))
                trimmed_script = " ".join(meta["script"].split()[:target_words])
                if trimmed_script and trimmed_script != meta["script"]:
                    log.warning(
                        "Hard-trimming script from %d to %d words to force a "
                        "%ds-or-shorter narration.",
                        word_count,
                        target_words,
                        cfg.target_seconds,
                    )
                    try:
                        duration, words = tts.synthesize(cfg, trimmed_script, voice)
                        meta["script"] = trimmed_script
                        last_duration = duration
                        _validate_narration_duration(duration, cfg.target_seconds)
                        break
                    except RuntimeError:
                        pass
                # Final resort: trim the audio and captions to TARGET_SECONDS so
                # the run completes instead of aborting on an overlong narration.
                log.warning(
                    "Trimming narration audio to %.1fs to keep the video at or below %d seconds.",
                    cfg.target_seconds,
                    cfg.target_seconds,
                )
                tts.trim_audio(voice, cfg.target_seconds)
                duration = tts.probe_duration(voice)
                words = tts.trim_words(words, cfg.target_seconds)
                meta["script"] = " ".join(w.get("text", "") for w in words)
                last_duration = duration
                try:
                    _validate_narration_duration(duration, cfg.target_seconds)
                    break
                except RuntimeError:
                    pass
                log.warning(
                    "Narration is %.1fs after trimming; continuing with a shorter video.",
                    last_duration,
                )
            # Aggressive correction: target ~85% of the measured words so the
            # next narration lands comfortably under the limit.
            if duration > cfg.target_seconds:
                words_per_second = max(MIN_WORDS_PER_SECOND, measured * 0.85)
            else:
                words_per_second = min(MAX_WORDS_PER_SECOND, measured * 1.15)
            log.warning(
                "Narration is %.1fs for %d words (%.2f words/s); regenerating "
                "with %.2f words/s (attempt %d/%d): %s",
                duration,
                word_count,
                measured,
                words_per_second,
                attempt + 2,
                MAX_SCRIPT_ATTEMPTS,
                error,
            )
    else:
        # Loop exhausted without break: validate the last measurement to raise.
        if last_duration is not None:
            _validate_narration_duration(last_duration, cfg.target_seconds)

    # 3. Generate the configured video asset(s).
    is_json2video = cfg.video_provider == "json2video"
    is_huggingface = cfg.video_provider == "huggingface"
    estimated_cost = (
        None
        if (is_json2video or is_huggingface)
        else round(video_gen.estimate_cost_usd(len(meta["scene_prompts"])), 2)
    )
    meta["video_generation"] = {
        "provider": cfg.video_provider,
        "model": (
            video_gen.JSON2VIDEO_MODEL
            if is_json2video
            else "huggingface-free"
            if is_huggingface
            else cfg.omni_model
        ),
        "resolution": (
            video_gen.JSON2VIDEO_RESOLUTION
            if is_json2video
            else "512x512"
            if is_huggingface
            else video_gen.RESOLUTION
        ),
        "scene_count": (1 if is_json2video else len(meta["scene_prompts"])),
        "dry_run": cfg.dry_run,
        "estimated_video_cost_usd": estimated_cost,
    }
    meta_path = cfg.output_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if is_huggingface:
        clips = huggingface.generate_scenes(cfg, meta["scene_prompts"], cfg.work_dir / "scenes")
    else:
        clips = video_gen.generate_scenes(
            cfg,
            meta["scene_prompts"],
            cfg.work_dir / "scenes",
            text=meta.get("title", "Hello from Python"),
        )

    # 4. normalize audio loudness (YouTube standard -14 LUFS)
    tts.normalize_audio(voice)

    # 5. render
    video = cfg.output_dir / "video.mp4"
    render.build(cfg, clips, voice, duration, words, video, cfg.work_dir / "render")

    # 4b. generate thumbnail (non-fatal)
    thumb_path = cfg.output_dir / "thumbnail.jpg"
    thumb = thumbnail.generate(
        cfg,
        meta.get("title", "Daily Short"),
        meta.get("script", ""),
        thumb_path,
    )

    # 4c. export SRT subtitles
    srt_path = cfg.output_dir / "captions.srt"
    captions.write_srt(words, srt_path)
    log.info("Exported subtitles: %s", srt_path)

    # 5. upload
    if not do_upload:
        log.info("Upload skipped (dry run). Video: %s", video)
        if thumb:
            log.info("Thumbnail saved: %s", thumb)
        notify.notify_dry_run(cfg, video)
        return 0
    vid = youtube.upload(cfg, video, meta)
    if thumb and vid:
        youtube.upload_thumbnail(cfg, vid, thumb)

    # 6. remember the topic only after a successful upload
    history.append(cfg.history_file, meta["topic"], meta["title"], vid)
    notify.notify_success(cfg, video, meta, vid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
