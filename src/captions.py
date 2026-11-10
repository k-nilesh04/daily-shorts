"""Build animated ASS captions and the minimal HUD for the square-frame or fullscreen layout."""

import re
from pathlib import Path

from .config import Config

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H0000FFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,3,2,72,72,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(sec: float) -> str:
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def group_words(words: list[dict], max_words: int = 3) -> list[dict]:
    """Group word timings into short caption chunks; break on punctuation."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        ends_sentence = bool(re.search(r"[.!?,;:]$", w["text"]))
        if len(cur) >= max_words or ends_sentence:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        out.append(
            {
                "text": " ".join(x["text"] for x in g),
                "start": g[0]["start"],
                "end": g[-1]["end"],
                "words": g,
            }
        )
    # keep captions on screen until the next one starts (no flicker)
    for a, b in zip(out, out[1:]):
        if 0 <= b["start"] - a["end"] < 0.4:
            a["end"] = b["start"]
    return out


def write_ass(cfg: Config, words: list[dict], path: Path) -> Path:
    lines = [
        HEADER.format(
            w=cfg.width, h=cfg.height, font=cfg.caption_font, size=cfg.caption_size, margin_v=0
        )
    ]
    frame_y, frame_size = cfg.frame_y, cfg.frame_size
    center_x = cfg.width // 2

    layout = getattr(cfg, "layout", "fullscreen")
    if layout == "frame":
        caption_y = frame_y + frame_size + max(80, (cfg.height - frame_y - frame_size) // 3)
    else:
        # Fullscreen 9:16 vertical layout (optimal position above shorts interface)
        caption_y = cfg.height - 480

    for g in group_words(words):
        syllables = []
        for word in g["words"]:
            text = re.sub(r"[{}\\]", "", word["text"])
            if cfg.caption_upper:
                text = text.upper()
            duration_cs = max(1, round(max(0.01, word["end"] - word["start"]) * 100))
            syllables.append(f"{{\\kf{duration_cs}}}{text}")
        text = " ".join(syllables)
        animation = (
            f"{{\\an5\\pos({center_x},{caption_y})\\fscx88\\fscy88"
            "\\t(0,130,\\fscx100\\fscy100)\\fad(35,65)}"
        )
        lines.append(
            f"Dialogue: 1,{_ts(g['start'])},{_ts(g['end'] + 0.12)},"
            f"Default,,0,0,0,,{animation}{text}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_srt(words: list[dict], path: Path) -> Path:
    """Export word timings as an SRT subtitle file."""
    groups = group_words(words)
    lines = []
    for i, g in enumerate(groups, 1):
        start = _srt_ts(g["start"])
        end = _srt_ts(g["end"] + 0.12)
        text = " ".join(w["text"] for w in g["words"])
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _srt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
