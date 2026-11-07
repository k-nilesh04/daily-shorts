"""Daily pipeline:  script -> voice -> footage -> render -> (upload) -> history."""
import argparse
import json
import logging
import shutil
import sys

from . import config, footage, history, omni, render, script_gen, tts, youtube
from .util import log


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true", help="upload to YouTube (or set UPLOAD=true)")
    args = ap.parse_args()

    cfg = config.load()
    do_upload = args.upload or cfg.upload

    shutil.rmtree(cfg.work_dir, ignore_errors=True)
    cfg.work_dir.mkdir(parents=True)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. script
    meta = script_gen.generate(cfg, history.recent_topics(cfg.history_file))

    # 2. voice + word timings
    voice = cfg.work_dir / "voice.mp3"
    duration, words = tts.synthesize(cfg, meta["script"], voice)

    # 3. footage (+ optional hook)
    hook = omni.get_hook(cfg, meta["hook_prompt"], cfg.work_dir)
    need = render.segments_needed(cfg, duration, hook is not None)
    clips = footage.fetch(cfg, meta["keywords"], need, cfg.work_dir / "clips")
    meta["footage_credits"] = list({
        clip.path: clip.credit() for clip in clips
    }.values())

    # 4. render
    video = cfg.output_dir / "video.mp4"
    render.build(cfg, [clip.path for clip in clips], hook, voice, duration, words,
                 video, cfg.work_dir / "render")
    (cfg.output_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. upload
    if not do_upload:
        log.info("Upload skipped (dry run). Video: %s", video)
        return 0
    if not cfg.can_upload:
        log.error("UPLOAD requested but YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN missing")
        return 1
    vid = youtube.upload(cfg, video, meta)

    # 6. remember the topic only after a successful upload
    history.append(cfg.history_file, meta["topic"], meta["title"], vid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
