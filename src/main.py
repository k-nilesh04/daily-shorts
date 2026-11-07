"""Daily pipeline:  script -> voice -> AI video -> render -> (upload) -> history."""
import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from . import config, history, render, script_gen, tts, video_gen, youtube
from .util import log


NARRATION_OVERRUN_TOLERANCE_SECONDS = 2
NARRATION_UNDERRUN_TOLERANCE_RATIO = 0.15
NARRATION_UNDERRUN_TOLERANCE_MIN_SECONDS = 3
MAX_SHORT_SECONDS = 60


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
    if duration < min_duration:
        raise RuntimeError(
            f"Narration is {duration:.1f}s; minimum allowed for TARGET_SECONDS="
            f"{target_seconds} is {min_duration:.1f}s. AI video generation was stopped "
            "to avoid paying for an under-length video; regenerate the script or "
            "lower TARGET_SECONDS."
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
    if do_upload and not cfg.can_upload:
        log.warning("YT environment variables (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN) not found; bypassing upload.")
        do_upload = False

    _prepare_work_dir(cfg.work_dir)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. script
    meta = script_gen.generate(cfg, history.recent_topics(cfg.history_file))

    # 2. voice + word timings
    voice = cfg.work_dir / "voice.mp3"
    duration, words = tts.synthesize(cfg, meta["script"], voice)
    _validate_narration_duration(duration, cfg.target_seconds)

    # 3. Generate the configured video asset(s).
    is_json2video = cfg.video_provider == "json2video"
    estimated_cost = (
        None if is_json2video
        else round(video_gen.estimate_cost_usd(len(meta["scene_prompts"])), 2)
    )
    meta["video_generation"] = {
        "provider": cfg.video_provider,
        "model": video_gen.JSON2VIDEO_MODEL if is_json2video else video_gen.MODEL,
        "resolution": video_gen.JSON2VIDEO_RESOLUTION if is_json2video else video_gen.RESOLUTION,
        "scene_count": 1 if is_json2video else len(meta["scene_prompts"]),
        "dry_run": cfg.dry_run,
        "estimated_video_cost_usd": estimated_cost,
    }
    meta_path = cfg.output_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    clips = video_gen.generate_scenes(
        cfg, meta["scene_prompts"], cfg.work_dir / "scenes",
        text=meta.get("title", "Hello from Python"),
    )

    # 4. render
    video = cfg.output_dir / "video.mp4"
    render.build(cfg, clips, voice, duration, words, video, cfg.work_dir / "render")

    # 5. upload
    if not do_upload:
        log.info("Upload skipped (dry run). Video: %s", video)
        return 0
    vid = youtube.upload(cfg, video, meta)

    # 6. remember the topic only after a successful upload
    history.append(cfg.history_file, meta["topic"], meta["title"], vid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
