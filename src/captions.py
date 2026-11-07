"""Build an ASS subtitle file (big, centred, word-group captions)."""
import re
from pathlib import Path

from .config import Config

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,90,90,{margin_v},1

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
        out.append({
            "text": " ".join(x["text"] for x in g),
            "start": g[0]["start"],
            "end": g[-1]["end"],
        })
    # keep captions on screen until the next one starts (no flicker)
    for a, b in zip(out, out[1:]):
        if 0 <= b["start"] - a["end"] < 0.4:
            a["end"] = b["start"]
    return out


def write_ass(cfg: Config, words: list[dict], path: Path) -> Path:
    lines = [HEADER.format(w=cfg.width, h=cfg.height, font=cfg.caption_font,
                           size=cfg.caption_size, margin_v=520)]
    for g in group_words(words):
        text = g["text"].replace("{", "").replace("}", "").replace("\\", "")
        if cfg.caption_upper:
            text = text.upper()
        lines.append(f"Dialogue: 0,{_ts(g['start'])},{_ts(g['end'] + 0.05)},Default,,0,0,0,,{text}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
