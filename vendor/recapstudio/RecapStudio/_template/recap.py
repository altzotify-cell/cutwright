"""Recap Studio engine v2 - one script for every step of the workflow.

You normally never run this by hand: the .bat files in the project folder do it.
Manual use:  python recap.py <step> [--video FILE] [--json FILE] [--pick] [--force] ...

Steps:
  init      Ask module / topic / target length / voice mode  -> project.json
  subs      Extract embedded subtitle tracks         -> subs/
  index     Contact sheets for EVERY file in footage/ -> sheets/
  sheets    Contact sheets for need_visual segments  -> sheets/
  collect   Guided footage collection (yt-dlp / drag files) -> footage/, images/
  tts       Generate narration audio                 -> audio/
  review    Export narration to review_sheet.csv (or --import edits back)
  premiere  Cut clips + build multi-track Premiere XML -> premiere_sequence.xml
  videopad  Same timeline as a VideoPad project     -> videopad_project.vpj (--simple: V1+A1 only)
  video     Cut clips + join into ONE finished mp4   -> recap_final.mp4
  srt       Subtitles (+ on-screen text .srt)        -> recap_subtitles.srt
  tiktok    Build vertical 9:16 TikTok parts         -> tiktok_out/
  check     Status report (also writes STATE.md)
  demo      Fill this project with synthetic test media (to test the pipeline / Premiere import)
"""

import argparse
import asyncio
import csv
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.parse
import uuid
import webbrowser
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".mts",
              ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff")
MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text",
                   "subviewer", "microdvd"}
IMAGE_SUB_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub",
                    "dvb_teletext"}

AUDIO_DIR = "audio"
CLIPS_DIR = "clips"
SHEETS_DIR = "sheets"
SUBS_DIR = "subs"
FOOTAGE_DIR = "footage"
IMAGES_DIR = "images"
MUSIC_DIR = "music"
GFX_DIR = "gfx"
PREVIEW_DIR = "audio_preview"
TIKTOK_OUT = "tiktok_out"
TIKTOK_TEMP = "tiktok_temp"
XML_OUT = "premiere_sequence.xml"
FINAL_OUT = "recap_final.mp4"
SRT_OUT = "recap_subtitles.srt"
ONSCREEN_SRT = "recap_onscreen.srt"
CHAPTERS_OUT = "chapters.txt"
SHOT_CSV = "shot_manifest.csv"
SHOTS_STATE = "shots.json"
CREDITS_OUT = "credits.txt"
REVIEW_CSV = "review_sheet.csv"
STATE_MD = "STATE.md"
CONFIG_FILE = "config.json"
PROJECT_FILE = "project.json"

MODULES = [
    ("movie_recap", "Movie recap      (one film file + its subtitles)"),
    ("show_recap", "Show recap       (many episode files)"),
    ("nba_minidoc", "NBA mini-doc     (collected clips + stills, chapters)"),
    ("nba_story", "NBA story        (shorter, hook + arc)"),
    ("real_story", "Real story       (mostly stills, news clips)"),
    ("ranking", "Ranking / top-N  (countdown with number graphics)"),
]
RECAP_MODULES = ("movie_recap", "show_recap")
DEFAULT_TARGETS = {"movie_recap": "10:00", "show_recap": "10:00", "nba_minidoc": "8:00",
                   "nba_story": "3:00", "real_story": "6:00", "ranking": "6:00"}

DEFAULT_CONFIG = {
    "fps": 24,
    "width": 1920,
    "height": 1080,
    "sample_rate": 48000,
    "fill": "pad",              # pad = black bars | blur = blurred copy of the clip fills the frame
    "keep_audio_volume": 0.30,  # used when a segment has "keep_audio": true
    "music_volume": 0.12,
    "tts": {
        "engine": "",
        "edge_voice": "en-US-ChristopherNeural",
        "edge_rate": "+0%",
        "elevenlabs_voice_id": "",
        "elevenlabs_model": "eleven_v3",
        "elevenlabs_stability": 0.5,
        "minimax_voice": "male-qn-qingse",
    },
    "tiktok": {"width": 1080, "height": 1920, "fps": 30},
    "subtitles": {"max_chars_per_line": 42, "max_lines": 2},
}

DEFAULT_PROJECT = {
    "module": "movie_recap",
    "topic": "",
    "style": "retell",          # recap modules: retell | commentary | mixed
    "target_length": "",        # "8:00" or minutes, or {"youtube": "8:00", "tiktok_part": "1:00"}
    "platform": "youtube",
    "tts_mode": "plain",        # plain | light | heavy
    "voice_card": "",
    "fact_check": "off",
    "music": False,
    "captions": True,
}


# ====================================================================
# Shared helpers
# ====================================================================
def die(msg):
    print(f"\n[ERROR] {msg}")
    sys.exit(1)


def need(*tools):
    for t in tools:
        if shutil.which(t) is None:
            die(f"'{t}' was not found. Run SETUP.bat (main Recap Studio folder), "
                "then close and reopen this window.")


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"[!] Could not read {CONFIG_FILE} ({e}); using defaults.")
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_env():
    """Reads keys.env from this folder, the Projects folder, and the main folder."""
    here = ROOT
    for d in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        p = os.path.join(d, "keys.env")
        if not os.path.isfile(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\"'")
                if v and k not in os.environ:
                    os.environ[k] = v


CFG = load_config()
load_env()
FPS = int(CFG["fps"])
WIDTH = int(CFG["width"])
HEIGHT = int(CFG["height"])
SAMPLE_RATE = int(CFG["sample_rate"])


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def tail(text, n=8):
    return "\n".join(text.strip().splitlines()[-n:])


def parse_time(value):
    """Accepts 12.5, '12.5', 'MM:SS', 'HH:MM:SS(.ms)' -> float seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    secs = 0.0
    for p in str(value).strip().split(":"):
        secs = secs * 60 + float(p)
    return secs


def fmt_dash(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}-{(s % 3600) // 60:02d}-{s % 60:02d}"


def get_duration(path):
    res = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(res.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe could not read '{path}':\n{tail(res.stderr)}")


def get_audio_info(path):
    res = run(["ffprobe", "-v", "error", "-select_streams", "a:0",
               "-show_entries", "stream=sample_rate,channels", "-of", "json", path])
    try:
        s = json.loads(res.stdout)["streams"][0]
        return int(s["sample_rate"]), int(s["channels"])
    except Exception:
        return 44100, 1


def find_video(override=None):
    if override:
        if not os.path.isfile(override):
            die(f"Video not found: {override}")
        return override
    vids = [f for f in os.listdir(".")
            if f.lower().endswith(VIDEO_EXTS) and os.path.isfile(f)
            and not f.lower().startswith("tiktok_")]
    if not vids:
        die("No episode video in this folder. Drop the video file next to the .bat files.")
    vids.sort(key=os.path.getsize, reverse=True)
    if len(vids) > 1:
        print(f"[i] Several videos found, using the largest: {vids[0]}")
    return vids[0]


def find_json(override=None):
    if override:
        if not os.path.isfile(override):
            die(f"JSON not found: {override}")
        return override
    if os.path.isfile("segments.json"):
        return "segments.json"
    hits = glob.glob("*segments*.json")
    if not hits:
        hits = [h for h in glob.glob("*.json") if h.lower() != CONFIG_FILE]
    if not hits:
        die("No segments.json in this folder. Paste the JSON from Claude into segments.json.")
    return hits[0]


def load_data(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")


def yt_segments(data):
    if isinstance(data, list):
        return data
    return data.get("youtube", []) if isinstance(data, dict) else []


def tiktok_parts(data):
    t = data.get("tiktok", {}) if isinstance(data, dict) else {}
    if isinstance(t, list):
        return {"tiktok": t}
    return t or {}


def all_segments(data):
    """YouTube segments + every TikTok clip, de-duplicated by id."""
    seen, out = set(), []
    pool = list(yt_segments(data))
    for clips in tiktok_parts(data).values():
        pool.extend(clips)
    for seg in pool:
        sid = seg.get("id")
        if sid and sid not in seen:
            seen.add(sid)
            out.append(seg)
    return out


def reveal(path):
    try:
        if os.name == "nt" and os.path.exists(path):
            os.startfile(os.path.abspath(path))  # noqa
    except Exception:
        pass


def progress(done, total, label=""):
    """Machine-readable progress line; the Recap Studio UI turns it into a progress bar."""
    print(f"@@PROGRESS {int(done)} {int(total)} {label}", flush=True)


class Cache:
    """Remembers how each clip was rendered so unchanged clips are skipped."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.d = json.load(f)
        except Exception:
            self.d = {}

    def fresh(self, key, value, file):
        return self.d.get(key) == value and os.path.exists(file)

    def set(self, key, value):
        self.d[key] = value
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.d, f)




# ====================================================================
# v2 helpers: project.json, media lookup, probing, fonts, tags
# ====================================================================
def load_project():
    p = json.loads(json.dumps(DEFAULT_PROJECT))
    if os.path.exists(PROJECT_FILE):
        try:
            with open(PROJECT_FILE, "r", encoding="utf-8") as f:
                p.update(json.load(f))
        except Exception as e:
            print(f"[!] Could not read {PROJECT_FILE} ({e}); using defaults.")
    return p


def save_project(p):
    with open(PROJECT_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


PROJECT = load_project()
MODULE = PROJECT.get("module") or "movie_recap"


def parse_target(value, key="youtube"):
    """'8:00' -> 480 s; a bare number means minutes; dict -> pick key. None if not set."""
    if isinstance(value, dict):
        value = value.get(key)
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)) or re.fullmatch(r"\d+(\.\d+)?", str(value).strip()):
            return float(value) * 60.0
        return parse_time(value)
    except Exception:
        return None


def fmt_mmss(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def find_in(name, *folders):
    """Looks for a file by name in the given folders (and as an absolute path)."""
    if not name:
        return None
    name = str(name).strip().strip('"')
    if os.path.isabs(name) and os.path.isfile(name):
        return name
    for d in folders:
        p = os.path.join(d, name) if d else name
        if os.path.isfile(p):
            return p
    return None


def glob_by_id(folder, sid, exts):
    for ext in exts:
        for pat in (f"{sid}{ext}", f"{sid}{ext.upper()}"):
            p = os.path.join(folder, pat)
            if os.path.isfile(p):
                return p
    return None


def default_video():
    """Soft version of find_video: largest video in the project root, else None."""
    vids = [f for f in os.listdir(".")
            if f.lower().endswith(VIDEO_EXTS) and os.path.isfile(f)
            and not f.lower().startswith("tiktok_") and f.lower() != FINAL_OUT]
    if not vids:
        return None
    vids.sort(key=os.path.getsize, reverse=True)
    return vids[0]


_PROBE = {}


def probe_media(path):
    """-> dict(w, h, dur, has_audio). Cached per run."""
    if path in _PROBE:
        return _PROBE[path]
    info = {"w": 0, "h": 0, "dur": 0.0, "has_audio": False}
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height:format=duration", "-of", "json", path])
    try:
        d = json.loads(r.stdout or "{}")
        for s in d.get("streams", []):
            if s.get("codec_type") == "video" and not info["w"]:
                info["w"], info["h"] = int(s.get("width") or 0), int(s.get("height") or 0)
            if s.get("codec_type") == "audio":
                info["has_audio"] = True
        info["dur"] = float((d.get("format") or {}).get("duration") or 0)
    except Exception:
        pass
    _PROBE[path] = info
    return info


def seg_media(seg, default_vid):
    """Decides where a segment's picture comes from.
    -> {"kind": video|image|slate, "file", "start", "avail", "why"}"""
    sid = seg.get("id", "?")
    # 1. a still image
    if seg.get("image"):
        f = find_in(seg["image"], IMAGES_DIR, FOOTAGE_DIR, ".")
        if f:
            return {"kind": "image", "file": f, "start": 0.0, "avail": 0.0}
        return {"kind": "slate", "why": f"image '{seg['image']}' not found in images/"}
    # 2. explicit source file
    f = None
    if seg.get("src"):
        f = find_in(seg["src"], FOOTAGE_DIR, ".")
        if not f:
            return {"kind": "slate", "why": f"src '{seg['src']}' not found in footage/"}
    # 3. collected shot named after the segment id
    if not f:
        f = glob_by_id(FOOTAGE_DIR, sid, VIDEO_EXTS)
    # 4. a still named after the segment id
    if not f:
        im = glob_by_id(IMAGES_DIR, sid, IMAGE_EXTS)
        if im:
            return {"kind": "image", "file": im, "start": 0.0, "avail": 0.0}
    # 5. the one big source video (movie / episode recaps)
    if not f and default_vid and seg.get("src_start"):
        f = default_vid
    if not f:
        return {"kind": "slate", "why": "no footage yet"}
    try:
        start = parse_time(seg["src_start"]) if seg.get("src_start") else 0.0
        dur = probe_media(f)["dur"]
        end = parse_time(seg["src_end"]) if seg.get("src_end") else dur
    except Exception as e:
        return {"kind": "slate", "why": f"bad time range ({e})"}
    if end <= start:
        return {"kind": "slate", "why": f"src_end must be after src_start ({start}->{end})"}
    return {"kind": "video", "file": f, "start": start, "avail": end - start}


def iter_segments(data):
    """Every segment dict (youtube + tiktok parts), in file order, by reference."""
    out = list(yt_segments(data))
    for clips in tiktok_parts(data).values():
        out.extend(clips)
    return [s for s in out if isinstance(s, dict)]


# ---- fonts (for slates, number cards, timestamps) ----
def find_font(bold=True):
    cands = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def ff_path(p):
    """Escape a path for use inside an ffmpeg filter option."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def font_opt():
    f = find_font()
    return f"fontfile='{ff_path(f)}':" if f else ""


def write_textfile(name, text):
    os.makedirs(GFX_DIR, exist_ok=True)
    p = f"{GFX_DIR}/_{name}.txt"
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


# ---- tags ----
TAG_RE = re.compile(r"\[[^\]\n]{1,40}\]")


def strip_tags(text):
    t = TAG_RE.sub(" ", str(text))
    return " ".join(t.replace("*", "").split())


def count_tags(text):
    return len(TAG_RE.findall(str(text)))


def est_speech_seconds(text):
    """~2.5 words per second, plus 0.6 s for each [pause]."""
    words = len(strip_tags(text).split())
    pauses = len(re.findall(r"\[(?:long )?pause\]", str(text), re.I))
    return words / 2.5 + 0.6 * pauses


# ---- scale / pad / blur-fill ----
def fit_graph(sw, sh, W, H, fill, src="[0:v]", dst="[f]"):
    """Filter graph that makes any picture W x H.
    Same aspect -> plain scale. Different -> black bars (pad) or blurred background (blur)."""
    if sw <= 0 or sh <= 0:
        return (f"{src}scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2{dst}")
    if abs((sw / sh) / (W / H) - 1.0) < 0.02:
        return f"{src}scale={W}:{H}{dst}"
    if fill == "blur":
        return (f"{src}split[bgs][fgs];"
                f"[bgs]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:5[bgb];"
                f"[fgs]scale={W}:{H}:force_original_aspect_ratio=decrease[fgb];"
                f"[bgb][fgb]overlay=(W-w)/2:(H-h)/2{dst}")
    return (f"{src}scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2{dst}")


def file_sig(path):
    try:
        st = os.stat(path)
        return f"{os.path.abspath(path)}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return f"{path}:missing"


# ====================================================================
# STEP 1: subtitles
# ====================================================================
def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def find_all_videos():
    """Every source video: the project root plus footage/ (episodes), natural-sorted by file name.
    Skips the finished outputs and collected per-segment shots (yt_001.mp4 etc. are tiny anyway)."""
    found = []
    for d in (".", FOOTAGE_DIR):
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            full = os.path.join(d, f)
            low = f.lower()
            if (os.path.isfile(full) and low.endswith(VIDEO_EXTS)
                    and not low.startswith("tiktok_") and low != FINAL_OUT):
                found.append(full)
    found.sort(key=lambda p: natural_key(os.path.basename(p)))
    return found


def extract_subs_from(video):
    """Extract every text subtitle track of one video into subs/. -> list of (srt_path, language)."""
    probe = run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                 "stream=index,codec_name:stream_tags=language,title", "-of", "json", video])
    streams = json.loads(probe.stdout or "{}").get("streams", [])
    if not streams:
        print("  no embedded subtitle tracks.")
        return []
    print(f"  {len(streams)} subtitle track(s):")
    os.makedirs(SUBS_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(video))[0]
    safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s)
    saved = []
    for n, s in enumerate(streams):
        codec = s.get("codec_name", "")
        t = s.get("tags", {})
        lang = t.get("language", "und")
        print(f"    #{n}: {lang}  {codec}  {t.get('title', '')}")
        label = safe(f"{base}.{n}.{lang}" + (f".{t['title']}" if t.get("title") else ""))
        if codec in IMAGE_SUB_CODECS:
            print(f"    skipping #{n} ({codec}): picture-based subs need OCR.")
            continue
        out = f"{SUBS_DIR}/{label}.srt"
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", video,
                 "-map", f"0:s:{n}", "-c:s", "srt", out])
        if r.returncode == 0:
            print(f"    saved {out}")
            saved.append((out, lang))
        else:
            print(f"    could not convert #{n} ({codec}): {r.stderr.strip()[:200]}")
        if codec in ("ass", "ssa"):
            out2 = f"{SUBS_DIR}/{label}.ass"
            r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", video,
                     "-map", f"0:s:{n}", "-c:s", "copy", out2])
            if r.returncode == 0:
                print(f"    saved {out2} (may include speaker names)")
    return saved


def pick_english(saved):
    """Best English track from [(path, lang)]: eng/en first, then undefined, else the first track."""
    for path, lang in saved:
        if lang.lower().startswith("en"):
            return path
    for path, lang in saved:
        if lang.lower() in ("und", ""):
            return path
    return saved[0][0] if saved else None


def step_subs(args):
    """Subtitles for ONE video (--video) or for EVERY episode found in the project root + footage/."""
    need("ffmpeg", "ffprobe")
    videos = [find_video(args.video)] if args.video else find_all_videos()
    if not videos:
        die("No video found. Put the film / episodes in footage/ (or the project folder), then run this again.")
    print(f"Found {len(videos)} video(s):")
    for v in videos:
        print(f"  {v}")
    chosen, missing = [], []
    for i, video in enumerate(videos, 1):
        progress(i - 1, len(videos), f"Subtitles: {os.path.basename(video)}")
        print(f"\n[{i}/{len(videos)}] {os.path.basename(video)}")
        saved = extract_subs_from(video)
        best = pick_english(saved)
        if not best:
            # a hand-downloaded subtitle named after the video (Episode03.srt for Episode03.mkv)
            base = os.path.splitext(os.path.basename(video))[0]
            hand = sorted(h for h in glob.glob(f"{SUBS_DIR}/{glob.escape(base)}*.srt")
                          if not os.path.basename(h).startswith("ALL_EPISODES"))
            if hand:
                best = hand[0]
                print(f"  using your own subtitle file {best}")
        if best:
            chosen.append((os.path.basename(video), best))
        else:
            missing.append(os.path.basename(video))

    # one combined file for Claude: every episode's English subtitles, labelled with the exact file name
    if len(videos) > 1 and chosen:
        combined = f"{SUBS_DIR}/ALL_EPISODES_for_claude.txt"
        with open(combined, "w", encoding="utf-8") as out:
            out.write("Subtitles for every episode. Each block starts with the EPISODE FILE name; "
                      "use that exact name as \"src\" for segments from it.\n"
                      "Timestamps below are the real ones for that episode.\n\n")
            for vname, srt in chosen:
                out.write(f"########## EPISODE FILE: {vname} ##########\n\n")
                with open(srt, "r", encoding="utf-8", errors="replace") as f:
                    out.write(f.read().strip() + "\n\n")
        print(f"\nWrote {combined}  <- attach THIS one file to Claude.")
    os.makedirs(SUBS_DIR, exist_ok=True)
    with open(f"{SUBS_DIR}/_episodes.txt", "w", encoding="utf-8") as ep:
        for vname, srt in chosen:
            ep.write(f"{vname}\t{os.path.basename(srt)}\n")
        for vname in missing:
            ep.write(f"{vname}\t(NO SUBTITLES)\n")

    progress(len(videos), len(videos), "Subtitles done")
    print(f"\nDone. {len(chosen)} of {len(videos)} video(s) have English-ish subtitles in subs/.")
    if missing:
        print("[!] No usable text subtitles in: " + ", ".join(missing))
        print("    Download an English .srt for each and put it in subs/ named like the video "
              "(e.g. Episode03.srt for Episode03.mkv).")
    reveal(SUBS_DIR)




# ====================================================================
# STEP: init (new project questions) + module name for MENU.bat
# ====================================================================
def ask_text(prompt, default=""):
    if os.environ.get("RECAP_NONINTERACTIVE"):
        return default
    raw = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    return raw or default


def step_module(args):
    print(MODULE)


def step_init(args):
    p = load_project()
    print("\n=== New project setup (Enter = keep the suggestion) ===")
    keys = [k for k, _ in MODULES]
    default = keys.index(p["module"]) + 1 if p.get("module") in keys else 1
    p["module"] = ask_choice("What kind of video?", MODULES, default)
    p["topic"] = ask_text("Topic / title (e.g. 'Kobe 81-point game')", p.get("topic", ""))
    if p["module"] in RECAP_MODULES:
        p["style"] = ask_choice("Narration style:", [
            ("retell", "Retell      (what happens, scene by scene)"),
            ("commentary", "Commentary  (analysis: themes, mistakes, meaning)"),
            ("mixed", "Mixed       (retell + short analysis beats)")], 1)
    p["target_length"] = ask_text("Target length of the final video (e.g. 8:00, or minutes; blank = module default)",
                                  str(p.get("target_length") or ""))
    p["platform"] = ask_choice("Main platform:", [("youtube", "YouTube"), ("tiktok", "TikTok"),
                                                  ("both", "Both")], 1)
    p["tts_mode"] = ask_choice("Voice text style (ElevenLabs v3 tags):", [
        ("plain", "plain  - no tags (Edge-TTS / safest)"),
        ("light", "light  - a few emotion tags on key beats"),
        ("heavy", "heavy  - tags on most segments")], 1)
    if p["tts_mode"] != "plain":
        p["voice_card"] = ask_text("Voice card (tone/pacing/allowed tags)",
                                   p.get("voice_card") or "calm documentary narrator; allowed tags: [excited] [whispers] [sad] [softly] [dramatic] [warmly] [pause]")
    p["music"] = ask_choice("Background music bed (put tracks in music/)?",
                            [(True, "yes"), (False, "no")], 2)
    p["captions"] = True
    save_project(p)
    for d in (FOOTAGE_DIR, IMAGES_DIR, MUSIC_DIR):
        os.makedirs(d, exist_ok=True)

    # keep only the prompt file for the chosen module
    chosen = f"PASTE_THIS_TO_CLAUDE_{p['module']}.txt"
    if os.path.exists(chosen):
        shutil.copyfile(chosen, "PASTE_THIS_TO_CLAUDE.txt")
    for f in glob.glob("PASTE_THIS_TO_CLAUDE_*.txt"):
        try:
            os.remove(f)
        except OSError:
            pass
    tgt = p["target_length"] or DEFAULT_TARGETS.get(p["module"], "")
    print(f"\n[OK] project.json written. Module: {p['module']} | target length: {tgt}")
    print("Next: open PASTE_THIS_TO_CLAUDE.txt - it is the prompt for this project type.")


# ====================================================================
# Contact sheets
# ====================================================================
def make_sheet(file, start, dur, cols, rows, width, out, stamp=True):
    n = cols * rows
    vf = f"fps={n}/{dur:.3f},scale={width}:-1"
    if stamp and find_font():
        vf += (f",drawtext={font_opt()}text='%{{pts\\:hms\\:{start:.2f}}}':x=6:y=h-th-6:"
               f"fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=3")
    vf += f",tile={cols}x{rows}"
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
             "-i", file, "-vf", vf, "-frames:v", "1", "-q:v", "3", out])
    if (r.returncode != 0 or not os.path.exists(out)) and stamp:
        return make_sheet(file, start, dur, cols, rows, width, out, stamp=False)
    return r.returncode == 0 and os.path.exists(out), tail(r.stderr, 4)


def step_sheets(args):
    need("ffmpeg", "ffprobe")
    jpath = find_json(args.json)
    data = load_data(jpath)
    dv = args.video if args.video else default_video()
    print(f"JSON : {jpath}\n")
    os.makedirs(SHEETS_DIR, exist_ok=True)

    flagged = made = 0
    nv = [x for x in yt_segments(data) if x.get("need_visual")]
    for k_nv, s in enumerate(nv):
        progress(k_nv, len(nv), f"Contact sheet {s.get('id', '?')}")
        if not s.get("need_visual"):
            continue
        flagged += 1
        m = seg_media(s, dv)
        if m["kind"] != "video":
            print(f"[-] {s['id']}: {m.get('why') or m['kind']} - no sheet")
            continue
        start, dur = m["start"], max(m["avail"], 1)
        cols, rows, width = (4, 4, 400) if dur > 40 else (3, 2, 480)
        out = f"{SHEETS_DIR}/{s['id']}_{fmt_dash(start)}.jpg"
        if os.path.exists(out) and not args.force:
            print(f"[-] {out} already exists (skipping)")
            continue
        print(f"[+] {s['id']}  {fmt_mmss(start)} -> {fmt_mmss(start + dur)}  ({os.path.basename(m['file'])})")
        ok, err = make_sheet(m["file"], start, dur, cols, rows, width, out)
        if not ok:
            print(f"    [!] failed: {err}")
            continue
        made += 1

    if flagged == 0:
        print("No segments with \"need_visual\": true found in the JSON.")
    else:
        print(f"\nDone. {made} new sheet(s) in sheets/ - upload them to Claude.")
        reveal(SHEETS_DIR)


def index_file(path, force=False, label=None):
    """Contact sheet(s) for a whole footage file; timestamps are burned into every tile."""
    info = probe_media(path)
    dur = info["dur"]
    if dur <= 0:
        print(f"[!] could not read {path}")
        return []
    stem = label or re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(os.path.basename(path))[0])
    n_sheets = min(8, max(1, math.ceil(dur / 300)))
    chunk = dur / n_sheets
    made = []
    os.makedirs(SHEETS_DIR, exist_ok=True)
    for i in range(n_sheets):
        start = i * chunk
        out = f"{SHEETS_DIR}/footage_{stem}_{fmt_dash(start)}.jpg"
        if os.path.exists(out) and not force:
            made.append(out)
            continue
        ok, err = make_sheet(path, start, chunk, 4, 4, 400, out)
        if ok:
            made.append(out)
        else:
            print(f"    [!] sheet failed: {err}")
    return made


def step_index(args):
    need("ffmpeg", "ffprobe")
    todo = []
    if os.path.isdir(FOOTAGE_DIR):
        todo = [os.path.join(FOOTAGE_DIR, f) for f in sorted(os.listdir(FOOTAGE_DIR))
                if f.lower().endswith(VIDEO_EXTS)]
    dv = default_video()
    if dv:
        todo.insert(0, dv)
    if not todo:
        die("No video files in footage/ (or in the project folder). Drop footage there first.")
    total = 0
    for k_ix, path in enumerate(todo):
        progress(k_ix, len(todo), f"Indexing {os.path.basename(path)}")
        info = probe_media(path)
        print(f"[+] {path}  {fmt_mmss(info['dur'])}  {info['w']}x{info['h']}")
        total += len(index_file(path, args.force))
    print(f"\nDone. {total} contact sheet(s) in sheets/ (timestamp is burned into each tile) - "
          "upload them to Claude so it can give exact in/out times.")
    reveal(SHEETS_DIR)


# ====================================================================
# STEP: collect - guided footage collection (yt-dlp or drag & drop)
# ====================================================================
def ytdlp_cmd():
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        return None


def search_urls(shot, seg):
    q = [str(x).strip() for x in (shot.get("queries") or []) if str(x).strip()]
    if not q and shot.get("description"):
        q = [shot["description"]]
    kinds = ["https://www.youtube.com/results?search_query=",
             "https://x.com/search?f=video&q=",
             "https://www.google.com/search?tbm=isch&q="]
    urls = []
    for i, text in enumerate(q[:3]):
        urls.append(kinds[i] + urllib.parse.quote_plus(text))
    return urls


def parse_range(rest):
    """'1:42-1:51' / '1:42 1:51' / '1:42 to 1:51' -> ('1:42','1:51') or (None, None)."""
    rest = rest.strip()
    if not rest:
        return None, None
    parts = [p for p in re.split(r"\s*(?:-|to|\s)\s*", rest) if p]
    if len(parts) >= 2:
        try:
            a, b = parse_time(parts[0]), parse_time(parts[1])
            if b > a:
                return parts[0], parts[1]
        except Exception:
            pass
    return None, None


def load_shots():
    try:
        with open(SHOTS_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_shots(d):
    with open(SHOTS_STATE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    write_credits(d)


def write_credits(shots):
    rows = [(k, v) for k, v in shots.items() if v.get("url")]
    if not rows:
        return
    with open(CREDITS_OUT, "w", encoding="utf-8") as f:
        f.write("SOURCE LOG (clip -> where it came from)\n\n")
        for k, v in rows:
            rng = f"  [{v['in']} - {v['out']}]" if v.get("in") else ""
            f.write(f"{k}: {v['url']}{rng}\n")


def download_clip(url, sid, a, b):
    """Downloads ONLY the wanted section with yt-dlp -> footage/<sid>.mp4"""
    cmd = ytdlp_cmd()
    if not cmd:
        print("[!] yt-dlp is not installed. Run SETUP.bat (main folder), then try again.")
        return None
    os.makedirs(FOOTAGE_DIR, exist_ok=True)
    for old in glob.glob(f"{FOOTAGE_DIR}/{sid}.*"):
        try:
            os.remove(old)
        except OSError:
            pass
    base = cmd + ["--no-playlist", "--no-mtime", "-f",
                  "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
                  "--merge-output-format", "mp4", "-o", f"{FOOTAGE_DIR}/{sid}.%(ext)s"]
    section = ["--download-sections", f"*{a}-{b}", "--force-keyframes-at-cuts"] if (a and b) else []
    # YouTube often answers 403 to ffmpeg range downloads for some player clients,
    # so try several clients, then (optionally) fall back to the full video + local trim.
    attempts = [
        ("default client", []),
        ("tv client", ["--extractor-args", "youtube:player_client=tv,web_safari"]),
        ("ios/mweb client", ["--extractor-args", "youtube:player_client=ios,mweb"]),
        ("web client + native downloader", ["--extractor-args", "youtube:player_client=web,default",
                                             "--downloader", "native"]),
    ]
    print("    downloading..." + ("" if a else " (whole video - no time range given)"))
    hits = []
    for label, extra in attempts:
        for old in glob.glob(f"{FOOTAGE_DIR}/{sid}.*"):
            try:
                os.remove(old)
            except OSError:
                pass
        if label != "default client":
            print(f"    retrying with {label}...")
        r = subprocess.run(base + extra + section + [url])
        hits = [h for h in glob.glob(f"{FOOTAGE_DIR}/{sid}.*") if h.lower().endswith(VIDEO_EXTS)]
        if r.returncode == 0 and hits:
            return hits[0]
        if not section and label == "tv client":
            break
    if section:
        ans = "n"
        if not os.environ.get("RECAP_NONINTERACTIVE"):
            ans = input("    Section download keeps failing. Download the WHOLE video and cut it locally "
                        "(can be large/slow)? y/N > ").strip().lower()
        if ans == "y":
            tmp = f"{FOOTAGE_DIR}/_full_{sid}.%(ext)s"
            cmd_full = cmd + ["--no-playlist", "--no-mtime", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                              "--merge-output-format", "mp4", "-o", tmp, url]
            subprocess.run(cmd_full)
            fulls = glob.glob(f"{FOOTAGE_DIR}/_full_{sid}.*")
            if fulls:
                out = f"{FOOTAGE_DIR}/{sid}.mp4"
                subprocess.run(["ffmpeg", "-y", "-ss", str(parse_time(a)), "-to", str(parse_time(b)),
                                "-i", fulls[0], "-c:v", "libx264", "-c:a", "aac", out])
                for f_ in fulls:
                    try:
                        os.remove(f_)
                    except OSError:
                        pass
                if os.path.exists(out):
                    return out
    print("    [!] download failed (YouTube is blocking it).")
    print("        Fixes: 1) run  yt-dlp -U   2) install Deno (winget install DenoLand.Deno) - yt-dlp needs a JS runtime")
    print("               3) or download the clip by hand and drag the file here.")
    return None
    return hits[0]


def step_collect(args):
    need("ffmpeg", "ffprobe")
    data = load_data(find_json(args.json))
    segs = [s for s in iter_segments(data)]
    seen, uniq = set(), []
    for s in segs:
        if s.get("id") and s["id"] not in seen:
            seen.add(s["id"])
            uniq.append(s)
    dv = default_video()
    shots = load_shots()
    missing = []
    for s in uniq:
        m = seg_media(s, dv)
        if m["kind"] == "slate":
            st = shots.get(s["id"], {}).get("status")
            if st == "skipped" and not args.retry:
                continue
            missing.append(s)
    print(f"{len(uniq)} segments, {len(missing)} still need footage.")
    if not missing:
        print("Nothing to collect - every segment has footage or a still.")
        write_shot_manifest(uniq, dv)
        return
    if not shots.get("_notice"):
        print("\nNote: downloading clips may breach some sites' terms, and heavy use of copyrighted "
              "footage with thin commentary can get claims. Your call - this message shows once.")
        shots["_notice"] = {"status": "shown"}
        save_shots(shots)
    print("\nFor each shot: paste a URL (optionally with a time range like  https://... 1:42-1:51 ),")
    print("or drag a video/image file into this window.  Enter = skip,  b = reopen search tabs,  q = quit.\n")

    for n, s in enumerate(missing, 1):
        sid = s["id"]
        shot = s.get("shot") or {}
        print("-" * 64)
        print(f"[{n}/{len(missing)}] {sid}")
        print(f"  Narration : {strip_tags(s.get('narration', ''))[:160]}")
        if shot.get("description"):
            print(f"  Need      : {shot['description']}")
        for i, qtxt in enumerate(shot.get("queries") or [], 1):
            print(f"  Search {i}  : {qtxt}")
        if shot.get("fallback"):
            print(f"  Fallback  : {shot['fallback']}")
        urls = search_urls(shot, s)
        if urls:
            for u in urls:
                webbrowser.open_new_tab(u)
        while True:
            raw = input("  URL [range] / file / Enter=skip / b / q > ").strip().strip('"')
            low = raw.lower()
            if low == "q":
                save_shots(shots)
                print("Saved. Run collect again to resume.")
                write_shot_manifest(uniq, dv)
                return
            if low == "b":
                for u in urls:
                    webbrowser.open_new_tab(u)
                continue
            if not raw:
                shots[sid] = {"status": "skipped"}
                save_shots(shots)
                break
            if os.path.isfile(raw):
                ext = os.path.splitext(raw)[1].lower()
                is_img = ext in IMAGE_EXTS
                dest_dir = IMAGES_DIR if is_img else FOOTAGE_DIR
                os.makedirs(dest_dir, exist_ok=True)
                dest = os.path.join(dest_dir, sid + ext)
                shutil.copyfile(raw, dest)
                shots[sid] = {"status": "done", "file": dest, "url": "", "note": "dragged file"}
                save_shots(shots)
                print(f"    saved -> {dest}")
                break
            mt = re.match(r"(https?://\S+)\s*(.*)$", raw)
            if not mt:
                print("    That is not a URL or a file. Try again (Enter = skip).")
                continue
            url, rest = mt.group(1), mt.group(2)
            if os.path.splitext(url.split("?")[0])[1].lower() in IMAGE_EXTS:
                try:
                    import requests
                    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                    ext = os.path.splitext(url.split("?")[0])[1].lower()
                    os.makedirs(IMAGES_DIR, exist_ok=True)
                    dest = os.path.join(IMAGES_DIR, sid + ext)
                    with open(dest, "wb") as f:
                        f.write(r.content)
                    shots[sid] = {"status": "done", "file": dest, "url": url}
                    save_shots(shots)
                    print(f"    saved -> {dest}")
                    break
                except Exception as e:
                    print(f"    [!] image download failed: {e}")
                    continue
            a, b = parse_range(rest)
            if rest.strip() and not a:
                print("    Could not read the time range - use start-end like 1:42-1:51")
                continue
            path = download_clip(url, sid, a, b)
            if not path:
                continue
            info = probe_media(path)
            shots[sid] = {"status": "done", "file": path, "url": url, "in": a or "", "out": b or ""}
            save_shots(shots)
            print(f"    saved -> {path}  ({fmt_mmss(info['dur'])}, {info['w']}x{info['h']})")
            if not a and info["dur"] > 90:
                made = index_file(path, True, label=sid)
                print(f"    long video: contact sheet(s) made in sheets/ - send them to Claude "
                      f"for exact in/out times, then trim/cut with the timestamps.")
            break

    save_shots(shots)
    write_shot_manifest(uniq, dv)
    print("\nDone with this pass. Run collect again any time to resume skipped shots (--retry for those).")


def step_missing(args):
    """Print a JSON list of the segments that still need footage (for the web UI)."""
    data = load_data(find_json(args.json))
    seen, uniq = set(), []
    for s in iter_segments(data):
        if s.get("id") and s["id"] not in seen:
            seen.add(s["id"])
            uniq.append(s)
    dv = default_video()
    shots = load_shots()
    out = []
    for s in uniq:
        m = seg_media(s, dv)
        sh = s.get("shot") or {}
        st = shots.get(s["id"], {}).get("status")
        out.append({
            "id": s["id"],
            "missing": m["kind"] == "slate",
            "why": m.get("why", ""),
            "status": st or "",
            "narration": strip_tags(s.get("narration", ""))[:200],
            "description": sh.get("description", ""),
            "queries": sh.get("queries") or [],
            "fallback": sh.get("fallback", ""),
        })
    print(json.dumps(out, ensure_ascii=False))


def step_collect_one(args):
    """Non-interactive single-shot collection (for the web UI)."""
    need("ffmpeg", "ffprobe")
    data = load_data(find_json(args.json))
    seen, segs = set(), []
    for s in iter_segments(data):
        if s.get("id") and s["id"] not in seen:
            seen.add(s["id"])
            segs.append(s)
    seg = next((s for s in segs if s.get("id") == args.id), None)
    if seg is None:
        die(f"No segment with id '{args.id}'.")
    sid = seg["id"]
    shots = load_shots()
    dv = default_video()

    if args.skip:
        shots[sid] = {"status": "skipped"}
        save_shots(shots)
        write_shot_manifest(segs, dv)
        print(json.dumps({"id": sid, "status": "skipped"}))
        return

    if args.file:
        if not os.path.isfile(args.file):
            die(f"File not found: {args.file}")
        ext = os.path.splitext(args.file)[1].lower()
        dest_dir = IMAGES_DIR if ext in IMAGE_EXTS else FOOTAGE_DIR
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, sid + ext)
        shutil.copyfile(args.file, dest)
        shots[sid] = {"status": "done", "file": dest, "url": "", "note": "uploaded file"}
        save_shots(shots)
        write_shot_manifest(segs, dv)
        info = probe_media(dest)
        print(json.dumps({"id": sid, "status": "done", "file": dest,
                          "dur": round(info["dur"], 1), "w": info["w"], "h": info["h"]}))
        return

    if not args.url:
        die("Provide --url (with optional --range 'a-b'), --file, or --skip.")

    url = args.url.strip()
    a, b = None, None
    if args.range:
        a, b = parse_range(args.range)

    if os.path.splitext(url.split("?")[0])[1].lower() in IMAGE_EXTS:
        try:
            import requests
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            ext = os.path.splitext(url.split("?")[0])[1].lower()
            os.makedirs(IMAGES_DIR, exist_ok=True)
            dest = os.path.join(IMAGES_DIR, sid + ext)
            with open(dest, "wb") as f:
                f.write(r.content)
            shots[sid] = {"status": "done", "file": dest, "url": url}
            save_shots(shots)
            write_shot_manifest(segs, dv)
            print(json.dumps({"id": sid, "status": "done", "file": dest}))
            return
        except Exception as e:
            die(f"image download failed: {e}")

    path = download_clip(url, sid, a, b)
    if not path:
        die(f"download failed for {url}")
    info = probe_media(path)
    shots[sid] = {"status": "done", "file": path, "url": url, "in": a or "", "out": b or ""}
    save_shots(shots)
    if not a and info["dur"] > 90:
        index_file(path, True, label=sid)
    write_shot_manifest(segs, dv)
    print(json.dumps({"id": sid, "status": "done", "file": path,
                      "dur": round(info["dur"], 1), "w": info["w"], "h": info["h"]}))


def write_shot_manifest(segs, dv, items=None):
    """shot_manifest.csv: one row per segment - where its picture comes from."""
    shots = load_shots()
    rows = []
    for s in segs:
        m = seg_media(s, dv)
        sh = s.get("shot") or {}
        meta = shots.get(s["id"], {})
        rows.append([s["id"], "OK" if m["kind"] != "slate" else "MISSING", m["kind"],
                     m.get("file", ""), fmt_mmss(m["start"]) if m["kind"] == "video" else "",
                     meta.get("url", ""), sh.get("description", ""), "; ".join(sh.get("queries") or []),
                     sh.get("fallback", "")])
    with open(SHOT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "status", "type", "file", "in", "url", "description", "queries", "fallback"])
        w.writerows(rows)
    print(f"[+] {SHOT_CSV}: {sum(1 for r in rows if r[1] == 'OK')} ok, "
          f"{sum(1 for r in rows if r[1] == 'MISSING')} missing")


# ====================================================================
# STEP 3: TTS (Edge / ElevenLabs / MiniMax)
# ====================================================================
EDGE_VOICES = [
    ("en-US-ChristopherNeural", "Christopher (classic recap narrator)"),
    ("en-US-GuyNeural", "Guy (natural / documentary)"),
    ("en-US-EricNeural", "Eric (deep / serious)"),
    ("en-US-JennyNeural", "Jenny (clear female narrator)"),
]
MINIMAX_VOICES = [
    ("male-qn-qingse", "Male Qingse (calm & clear narrator)"),
    ("presenter_male", "Presenter Male (broadcast voice)"),
    ("Wise_Woman", "Wise Woman (mature narrative)"),
    ("audiobook_male_1", "Audiobook Male (deep storyteller)"),
]
ENGINES = [("edge", "Edge-TTS    (free, unlimited)"),
           ("elevenlabs", "ElevenLabs  (multi-key, premade voices)"),
           ("minimax", "MiniMax     (multi-key, speech-2.6-hd)")]


POOLS = []


class KeyPool:
    def __init__(self, raw):
        self.keys = [k.strip() for k in raw.replace(" ", ",").split(",") if k.strip()]
        self.idx = 0
        POOLS.append(self)

    @property
    def current(self):
        return self.keys[self.idx] if self.keys else None

    def rotate(self):
        if self.idx + 1 < len(self.keys):
            self.idx += 1
            print(f"\n[!] Key failed/quota hit. Switching to key #{self.idx + 1}...")
            return True
        print(f"\n[!] All {len(self.keys)} API key(s) exhausted.")
        return False


def ask_choice(title, options, default=1):
    if os.environ.get("RECAP_NONINTERACTIVE"):
        idx = default - 1 if 1 <= default <= len(options) else 0
        return options[idx][0]
    print(f"\n{title}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}. {label}")
    raw = input(f"Pick a number (Enter = {default}): ").strip()
    idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= len(options) else default - 1
    return options[idx][0]


def get_keys(env_name, label):
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        print(f"\n[!] No {label} key found. Put it in keys.env as {env_name}=your_key")
        if not os.environ.get("RECAP_NONINTERACTIVE"):
            raw = input(f"Or paste {label} key(s) now (comma-separated): ").strip()
    if not raw:
        die(f"{label} API key is required.")
    return KeyPool(raw)


def make_edge(cfg, pick):
    try:
        import edge_tts
    except ImportError:
        die("edge-tts is not installed. Run SETUP.bat (main folder).")
    t = cfg["tts"]
    if pick:
        t["edge_voice"] = ask_choice("Edge-TTS voices:", EDGE_VOICES)
        save_config(cfg)
    voice, rate = t["edge_voice"], t.get("edge_rate", "+0%")
    print(f"Engine: Edge-TTS | Voice: {voice} | Rate: {rate}")

    def runner(text, out):
        async def go():
            await edge_tts.Communicate(text, voice, rate=rate).save(out)
        asyncio.run(go())
        return True
    return runner


def make_elevenlabs(cfg, pick):
    import requests
    pool = get_keys("ELEVENLABS_API_KEY", "ElevenLabs")
    api = "https://api.elevenlabs.io/v1"
    t = cfg["tts"]
    if pick or not t.get("elevenlabs_voice_id"):
        voices = []
        try:
            r = requests.get(f"{api}/voices", headers={"xi-api-key": pool.current}, timeout=30)
            if r.status_code == 200:
                voices = [v for v in r.json().get("voices", []) if v.get("category") == "premade"]
        except Exception as e:
            print(f"[!] Could not fetch voices: {e}")
        if voices:
            opts = []
            for v in voices:
                lb = v.get("labels") or {}
                d = ", ".join(x for x in (lb.get("gender"), lb.get("accent"), lb.get("description")) if x)
                opts.append((v["voice_id"], v["name"] + (f"  ({d})" if d else "")))
            t["elevenlabs_voice_id"] = ask_choice("ElevenLabs voices (free plan):", opts)
        else:
            t["elevenlabs_voice_id"] = "21m00Tcm4TlvDq8ikWAM"  # Rachel fallback
        save_config(cfg)
    voice_id = t["elevenlabs_voice_id"]
    print(f"Engine: ElevenLabs | Voice ID: {voice_id} | Model: {t.get('elevenlabs_model', 'eleven_v3')} "
          f"| Stability: {t.get('elevenlabs_stability', 0.5)} | Keys: {len(pool.keys)}")
    verify_voice_on_keys(pool, voice_id)

    def runner(text, out):
        payload = {"text": text, "model_id": t.get("elevenlabs_model", "eleven_v3"),
                   "voice_settings": {"stability": float(t.get("elevenlabs_stability", 0.5)),
                                      "similarity_boost": 0.75}}
        waits = 0
        while True:
            r = requests.post(f"{api}/text-to-speech/{voice_id}", json=payload, timeout=120,
                              headers={"xi-api-key": pool.current,
                                       "Content-Type": "application/json",
                                       "Accept": "audio/mpeg"})
            if r.status_code == 200:
                with open(out, "wb") as f:
                    f.write(r.content)
                return True
            if r.status_code in (401, 402, 429):
                if r.status_code == 429 and len(pool.keys) == 1 and waits < 3:
                    waits += 1
                    time.sleep(5)
                    continue
                if not pool.rotate():
                    return False
                time.sleep(1)
                continue
            print(f"\n[!] Failed: {r.status_code} - {r.text[:200]}")
            return False
    return runner


def make_minimax(cfg, pick):
    import requests
    pool = get_keys("MINIMAX_API_KEY", "MiniMax")
    api = "https://api.minimax.io/v1/t2a_v2"
    t = cfg["tts"]
    if pick:
        opts = MINIMAX_VOICES + [("__custom__", "Custom voice_id (type it)")]
        v = ask_choice("MiniMax voices:", opts)
        if v == "__custom__":
            v = input("Enter voice_id: ").strip() or MINIMAX_VOICES[0][0]
        t["minimax_voice"] = v
        save_config(cfg)
    voice_id = t["minimax_voice"]
    print(f"Engine: MiniMax | Voice: {voice_id} | Keys: {len(pool.keys)}")

    def runner(text, out):
        payload = {"model": "speech-2.6-hd", "text": text,
                   "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0},
                   "audio_setting": {"format": "mp3", "sample_rate": 32000}}
        while True:
            r = requests.post(api, json=payload, timeout=120,
                              headers={"Authorization": f"Bearer {pool.current}",
                                       "Content-Type": "application/json"})
            if r.status_code == 200:
                d = r.json()
                audio = (d.get("data") or {}).get("audio")
                if audio:
                    with open(out, "wb") as f:
                        f.write(bytes.fromhex(audio))
                    return True
                msg = (d.get("base_resp") or {}).get("status_msg", "no audio returned")
                print(f"\n[!] MiniMax error: {msg}")
                if not pool.rotate():
                    return False
            elif r.status_code in (401, 402, 429):
                if not pool.rotate():
                    return False
            else:
                print(f"\n[!] Failed: {r.status_code} - {r.text[:200]}")
                return False
    return runner




# ====================================================================
# TTS v2: tag modes, manifest (selective re-voice), preview, review sheet, length report
# ====================================================================
def verify_voice_on_keys(pool, voice_id):
    """Warn if the chosen voice is not usable on every API key (failover would change the voice)."""
    import requests
    if len(pool.keys) < 2:
        return
    bad = []
    for i, k in enumerate(pool.keys, 1):
        try:
            r = requests.get(f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                             headers={"xi-api-key": k}, timeout=20)
            if r.status_code != 200:
                bad.append((i, r.status_code))
        except Exception:
            pass
    if bad:
        print("[!] WARNING: this voice was NOT found on key(s) " +
              ", ".join(f"#{i} (HTTP {c})" for i, c in bad) +
              " - if failover switches to those keys, the voice will change or fail.")
    else:
        print(f"    Voice checked on all {len(pool.keys)} keys: OK (failover keeps the same voice).")


def keeps_tags(engine, cfg):
    """Tags stay in the text only for ElevenLabs v3 and only when project.json tts_mode isn't plain.
    Every other engine/model would READ THEM ALOUD, so they are stripped."""
    return (engine == "elevenlabs" and "v3" in str(cfg["tts"].get("elevenlabs_model", "")).lower()
            and PROJECT.get("tts_mode", "plain") != "plain")


def voice_text(seg, engine, cfg):
    t = str(seg.get("narration", "")).strip()
    if keeps_tags(engine, cfg):
        return " ".join(t.replace("*", "").split())
    return strip_tags(t)


def tts_signature(engine, cfg):
    t = cfg["tts"]
    if engine == "elevenlabs":
        return f"el|{t.get('elevenlabs_voice_id')}|{t.get('elevenlabs_model')}|{t.get('elevenlabs_stability')}"
    if engine == "minimax":
        return f"mm|{t.get('minimax_voice')}"
    return f"edge|{t.get('edge_voice')}|{t.get('edge_rate')}"


def h8(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def load_manifest():
    try:
        with open(os.path.join(AUDIO_DIR, "_manifest.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_manifest(m):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    with open(os.path.join(AUDIO_DIR, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)


def gen_with_retry(generate, text, out):
    tmp = out + ".part"
    retried = False
    for attempt in range(3):
        try:
            if generate(text, tmp):
                os.replace(tmp, out)
                return True, retried
        except Exception as e:
            print(f" error: {e}", end="", flush=True)
            time.sleep(1)
        retried = True
    if os.path.exists(tmp):
        os.remove(tmp)
    return False, retried


def step_tts(args):
    jpath = find_json(args.json)
    data = load_data(jpath)
    segs = [s for s in all_segments(data) if str(s.get("narration", "")).strip()]
    if not segs:
        die("No segments with narration found in the JSON.")

    cfg = CFG
    prev = cfg["tts"].get("engine") or ""
    keys_ = [k for k, _ in ENGINES]
    default_ = keys_.index(prev) + 1 if prev in keys_ else 1
    if args.engine:
        cfg["tts"]["engine"] = args.engine
    else:
        cfg["tts"]["engine"] = ask_choice("Which TTS engine do you want to use?", ENGINES, default_)
    save_config(cfg)
    engine = cfg["tts"]["engine"]

    if args.force and os.path.isdir(AUDIO_DIR):
        if not args.yes and input("This deletes ALL audio/*.mp3 and regenerates it. Type YES to confirm: ").strip() != "YES":
            die("Cancelled.")
        for f in glob.glob(os.path.join(AUDIO_DIR, "*.mp3")):
            os.remove(f)
        save_manifest({})

    maker = {"edge": make_edge, "elevenlabs": make_elevenlabs, "minimax": make_minimax}.get(engine, make_edge)
    generate = maker(cfg, args.pick)
    sig = tts_signature(engine, cfg)
    tagged = keeps_tags(engine, cfg)
    print(f"Tags: {'KEPT (ElevenLabs v3, mode ' + PROJECT.get('tts_mode', 'plain') + ')' if tagged else 'stripped (plain text goes to the voice)'}")

    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    preview = bool(args.preview)
    if preview and not only:
        only = [s["id"] for s in segs[:3]]
        print(f"Preview of the first {len(only)} segments (use --only id1,id2 to pick others).")
    if only:
        known = {s["id"] for s in segs}
        for x in only:
            if x not in known:
                print(f"[!] unknown id '{x}'")
        segs = [s for s in segs if s["id"] in only]
        if not segs:
            die("None of those ids have narration.")

    out_dir = PREVIEW_DIR if preview else AUDIO_DIR
    os.makedirs(out_dir, exist_ok=True)
    man = {} if preview else load_manifest()

    # decide what needs (re)voicing
    plan = []
    resig = []
    for s in segs:
        sid = s["id"]
        text = voice_text(s, engine, cfg)
        out = os.path.join(out_dir, f"{sid}.mp3")
        th = h8(text)
        if preview or (only and not preview):
            plan.append((s, text, out, th, "preview" if preview else "re-voice (asked)"))
            continue
        if not os.path.exists(out):
            plan.append((s, text, out, th, "new"))
            continue
        rec = man.get(sid)
        if rec is None:
            man[sid] = {"text": th, "sig": sig}  # old audio of unknown origin: keep it
            continue
        if rec.get("text") != th:
            plan.append((s, text, out, th, "text changed"))
        elif rec.get("sig") != sig:
            resig.append((s, text, out, th, "voice/engine changed"))
    if resig:
        ans = "y" if args.yes else input(f"\n{len(resig)} existing clip(s) were made with a different voice/engine/settings. "
                    "Re-voice them too? (y = yes, Enter = keep them): ").strip().lower()
        if ans == "y":
            plan.extend(resig)
        else:
            for s, text, out, th, _ in resig:
                man[s["id"]] = {"text": th, "sig": man[s["id"]]["sig"]}
    if not preview:
        save_manifest(man)

    if not plan:
        print("\nAll audio is up to date - nothing to voice.")
        length_report(args)
        return

    print(f"\n{len(plan)} clip(s) to voice -> {out_dir}/\n")
    failed, retries = [], []
    for i, (s, text, out, th, why) in enumerate(plan, 1):
        sid = s["id"]
        progress(i - 1, len(plan), f"Voicing {sid}")
        print(f"[{i}/{len(plan)}] {sid} ({len(text)} chars, {why})...", end="", flush=True)
        before = POOLS[-1].idx if POOLS else 0
        ok, retried = gen_with_retry(generate, text, out)
        after = POOLS[-1].idx if POOLS else 0
        if ok:
            print(" done" + (f"  [key #{before + 1} -> #{after + 1}]" if after != before else ""))
            if not preview:
                man[sid] = {"text": th, "sig": sig}
                save_manifest(man)
            if retried or after != before:
                retries.append(f"{sid}: retry={retried} key {before + 1}->{after + 1}")
        else:
            print(" FAILED")
            failed.append(sid)
        time.sleep(0.2)
    progress(len(plan), len(plan), "Voice-over done")

    if retries:
        with open(os.path.join(out_dir, "_retries.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M") + "\n" + "\n".join(retries) + "\n")
        print(f"\n[i] {len(retries)} clip(s) needed a retry or key switch (logged in {out_dir}/_retries.log) - "
              "listen to those first.")
    if failed:
        die(f"Failed clips: {', '.join(failed)}  (just run this step again to retry them)")
    if preview:
        print(f"\nPreview done. Listen in {PREVIEW_DIR}/ - tweak the [tags] in segments.json "
              "(or review_sheet.csv), preview again, then run the full voice step.")
        reveal(PREVIEW_DIR)
        return
    print("\nAll audio generated.")
    length_report(args)


def audio_frames(sid, fps, acache):
    if not os.path.exists(os.path.join(AUDIO_DIR, f"{sid}.mp3")):
        return None
    try:
        return fit_audio(sid, fps, acache)[1]
    except Exception:
        return None


def length_report(args):
    """Actual narration length vs the target in project.json."""
    try:
        data = load_data(find_json(args.json))
    except SystemExit:
        return
    need("ffmpeg", "ffprobe")
    acache = Cache(os.path.join(TRIM_DIR, "_cache.json"))
    target = parse_target(PROJECT.get("target_length")) or parse_target(DEFAULT_TARGETS.get(MODULE), "youtube")
    yt = [s for s in yt_segments(data) if s.get("id")]
    if yt:
        rows, missing = [], 0
        for s in yt:
            fr = audio_frames(s["id"], FPS, acache)
            if fr is None:
                missing += 1
                continue
            rows.append((fr / FPS, s["id"]))
        total = sum(r[0] for r in rows)
        print(f"\n=== LENGTH (YouTube) ===")
        print(f"  actual narration: {fmt_mmss(total)}" + (f"   ({missing} segment(s) without audio yet)" if missing else ""))
        if target:
            diff = total - target
            word = "over" if diff > 0 else "under"
            print(f"  target {fmt_mmss(target)}, actual {fmt_mmss(total)}, {word} by {fmt_mmss(abs(diff))}")
            if diff > 0 and rows:
                print("  longest segments (trim these first):")
                for d, sid in sorted(rows, reverse=True)[:5]:
                    print(f"    {sid:<12} {d:5.1f}s")
        else:
            print("  (no target length set in project.json)")
    tt = tiktok_parts(data)
    tfps = int(CFG["tiktok"]["fps"])
    ttarget = parse_target(PROJECT.get("target_length"), "tiktok_part") if isinstance(PROJECT.get("target_length"), dict) else None
    for part, clips in tt.items():
        tot, n = 0.0, 0
        for c in clips:
            fr = audio_frames(c.get("id"), tfps, acache)
            if fr is not None:
                tot += fr / tfps
                n += 1
        if n:
            extra = f", target {fmt_mmss(ttarget)}" if ttarget else ""
            print(f"  TikTok {part}: {fmt_mmss(tot)} ({n}/{len(clips)} clips){extra}")


# ---- review sheet (edit narration/tags/captions in Excel, import back) ----
def step_review(args):
    jpath = find_json(args.json)
    data = load_data(jpath)
    segs = iter_segments(data)
    dv = default_video()

    if args.do_import:
        if not os.path.exists(REVIEW_CSV):
            die(f"{REVIEW_CSV} not found - export it first.")
        by_id = {s.get("id"): s for s in segs}
        shutil.copyfile(jpath, jpath + ".bak")
        changed = 0
        with open(REVIEW_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                s = by_id.get((row.get("id") or "").strip())
                if not s:
                    continue
                for col, key in (("narration", "narration"), ("subtitle", "subtitle"), ("caption", "caption")):
                    if col not in row:
                        continue
                    new = (row[col] or "").strip()
                    old = str(s.get(key, "")).strip()
                    if new != old:
                        if new:
                            s[key] = new
                        else:
                            s.pop(key, None)
                        changed += 1
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Imported: {changed} field(s) changed in {jpath} (backup: {jpath}.bak).")
        print("Run the voice step - only the edited segments are re-voiced.")
        return

    need("ffmpeg", "ffprobe")
    acache = Cache(os.path.join(TRIM_DIR, "_cache.json"))
    rows, n_long, n_short = [], 0, 0
    seen = set()
    for s in segs:
        sid = s.get("id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        text = str(s.get("narration", ""))
        est = est_speech_seconds(text)
        rng, flag = "", ""
        clip_len = ""
        if s.get("src_start") and s.get("src_end"):
            try:
                a, b = parse_time(s["src_start"]), parse_time(s["src_end"])
                rng = f"{s['src_start']} -> {s['src_end']}"
                clip_len = round(b - a, 1)
                if est > clip_len + 0.7:
                    flag = f"TOO LONG (last frame held ~{est - clip_len:.0f}s)"
                    n_long += 1
                elif clip_len > 4 and est < clip_len * 0.6:
                    flag = f"TOO SHORT (footage cut ~{clip_len - est:.0f}s)"
                    n_short += 1
            except Exception:
                pass
        fr = audio_frames(sid, FPS, acache)
        rows.append([sid, rng, clip_len, round(est, 1), round(fr / FPS, 1) if fr else "", flag,
                     count_tags(text), text, s.get("subtitle", ""), s.get("caption", "")])
    with open(REVIEW_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "source_range", "clip_sec", "est_voice_sec", "actual_voice_sec", "flag",
                    "tags", "narration", "subtitle", "caption"])
        w.writerows(rows)
    print(f"[+] {REVIEW_CSV}: {len(rows)} segments ({n_long} too long, {n_short} too short).")
    print("Edit narration / subtitle / caption in Excel (keep the id column), save as CSV, "
          "then run 'Import review edits'.")
    reveal(REVIEW_CSV)


# ====================================================================
# Shared by STEP 4 / 5 / 6: silence-free, frame-exact narration audio
# ====================================================================
TRIM_DIR = "audio_trim"
SILENCE_DB = "-50dB"


def fit_audio(sid, fps, cache):
    """audio/<id>.mp3  ->  audio_trim/<fps>fps/<id>.wav

    * silence at the start and end of the voice-over is removed
    * the result is padded (by less than 1 frame) to a WHOLE number of frames,
      so video and audio are exactly the same length.
    Returns (wav_path, frame_count).
    """
    src = os.path.join(AUDIO_DIR, f"{sid}.mp3")
    out_dir = os.path.join(TRIM_DIR, f"{fps}fps")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{sid}.wav")
    st = os.stat(src)
    ckey = f"{fps}fps/{sid}"
    key = f"{st.st_mtime_ns}|{st.st_size}|{fps}|{SAMPLE_RATE}|{SILENCE_DB}"
    if cache.fresh(ckey, key, out):
        return out, max(1, round(get_duration(out) * fps))

    trim = (f"silenceremove=start_periods=1:start_threshold={SILENCE_DB}:start_silence=0.02,"
            f"areverse,"
            f"silenceremove=start_periods=1:start_threshold={SILENCE_DB}:start_silence=0.03,"
            f"areverse")
    base = ["-c:a", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "2"]
    tmp = out + ".tmp.wav"

    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", trim] + base + [tmp])
    dur = get_duration(tmp) if r.returncode == 0 and os.path.exists(tmp) else 0.0
    if dur < 0.05:  # everything looked like silence -> keep the file untouched
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", src] + base + [tmp])
        if r.returncode != 0 or not os.path.exists(tmp):
            raise RuntimeError(f"ffmpeg failed on {src}:\n{tail(r.stderr)}")
        dur = get_duration(tmp)

    frames = max(1, math.ceil(dur * fps - 1e-3))
    total = frames / fps
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
             "-af", f"apad=whole_dur={total:.6f}", "-t", f"{total:.6f}"] + base + [out])
    try:
        os.remove(tmp)
    except OSError:
        pass
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"ffmpeg failed while fitting {src}:\n{tail(r.stderr)}")
    cache.set(ckey, key)
    return out, frames


def to_pathurl(abs_path):
    # Premiere-style URL: file://localhost/C%3a/Users/name/My%20Folder/file.mp3
    clean = os.path.abspath(abs_path).replace("\\", "/")
    enc = urllib.parse.quote(clean, safe="/").replace("%3A", "%3a")
    if not enc.startswith("/"):
        enc = "/" + enc
    return "file://localhost" + enc




# ====================================================================
# STEP 4 / 5 shared: build every picture clip to match its voice-over exactly
# ====================================================================
def ffrun(cmd, out):
    r = run(cmd)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"ffmpeg failed:\n{tail(r.stderr)}")
    return r


X264 = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]


def render_video_clip(m, frames, W, H, F, out, fill):
    """Video-only clip of EXACTLY `frames` frames. Longer footage is cut at the end,
    shorter footage gets its last frame held (no black, no gap)."""
    total = frames / F
    use = min(m["avail"], total)
    info = probe_media(m["file"])
    g = fit_graph(info["w"], info["h"], W, H, fill)
    g += f";[f]fps={F},setsar=1,tpad=stop_mode=clone:stop_duration={total + 1:.3f}[v]"
    ffrun(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{m['start']:.3f}", "-t", f"{use:.3f}",
           "-i", m["file"], "-filter_complex", g, "-map", "[v]", "-frames:v", str(frames)] + X264 + [out], out)


def render_image_clip(m, frames, W, H, F, out):
    """Still image -> slow zoom (Ken Burns) lasting exactly `frames` frames."""
    info = probe_media(m["file"])
    g = fit_graph(info["w"], info["h"], W * 2, H * 2, "blur", "[0:v]", "[f]")
    g += (f";[f]zoompan=z='1+0.10*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
          f"d={frames}:s={W}x{H}:fps={F},setsar=1,format=yuv420p[v]")
    ffrun(["ffmpeg", "-y", "-loglevel", "error", "-i", m["file"], "-filter_complex", g,
           "-map", "[v]", "-frames:v", str(frames)] + X264 + [out], out)


def wrap_block(text, width=58):
    out = []
    for para in str(text).split("\n"):
        out.extend(textwrap.wrap(para, width) or [""])
    return "\n".join(out)


def render_slate(seg, why, frames, W, H, F, out):
    """Placeholder card for a shot that is still missing, so the timeline length is right."""
    sid = seg.get("id", "?")
    shot = seg.get("shot") or {}
    lines = []
    if shot.get("description"):
        lines.append(shot["description"])
    for q in shot.get("queries") or []:
        lines.append(f"search: {q}")
    if shot.get("fallback"):
        lines.append(f"fallback: {shot['fallback']}")
    if not lines:
        lines.append(strip_tags(seg.get("narration", ""))[:200] or why)
    lines.append(f"({why})")
    t1 = write_textfile(f"slate_{sid}_t", f"MISSING SHOT  {sid}")
    t2 = write_textfile(f"slate_{sid}_b", wrap_block("\n".join(lines)))
    total = frames / F
    fo = font_opt()
    base = f"color=c=0x20232a:s={W}x{H}:r={F}"
    full = (f"{base},drawtext={fo}textfile='{t1}':fontcolor=0xffb020:fontsize={int(H / 13)}:x=(w-text_w)/2:y={int(H * 0.10)},"
            f"drawtext={fo}textfile='{t2}':fontcolor=white:fontsize={int(H / 27)}:x={int(W * 0.08)}:y={int(H * 0.28)}:line_spacing=12")
    for vf in (full, base):
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", vf, "-t", f"{total:.6f}",
                 "-frames:v", str(frames)] + X264 + [out])
        if r.returncode == 0 and os.path.exists(out):
            return
    raise RuntimeError(f"slate failed:\n{tail(r.stderr)}")


def render_gfx(rank, caption, frames, W, H, F, out):
    """Transparent overlay (.mov with alpha) for V2: big rank number and/or a caption line."""
    fo = font_opt()
    chain = f"color=c=black@0.0:s={W}x{H}:r={F},format=rgba"
    if rank not in (None, ""):
        tf = write_textfile("rank_" + os.path.splitext(os.path.basename(out))[0], f"#{rank}")
        chain += (f",drawtext={fo}textfile='{tf}':fontcolor=white:fontsize={int(H / 4.2)}:"
                  f"x={int(W * 0.04)}:y={int(H * 0.05)}:box=1:boxcolor=0x000000@0.55:boxborderw={int(H / 45)}:"
                  f"borderw=3:bordercolor=0xffb020")
    if caption:
        tf = write_textfile("cap_" + os.path.splitext(os.path.basename(out))[0], wrap_block(caption, 44))
        chain += (f",drawtext={fo}textfile='{tf}':fontcolor=white:fontsize={int(H / 20)}:"
                  f"x=(w-text_w)/2:y=h-text_h-{int(H * 0.08)}:box=1:boxcolor=0x000000@0.6:boxborderw={int(H / 60)}:"
                  f"line_spacing=8")
    os.makedirs(GFX_DIR, exist_ok=True)
    ffrun(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", chain, "-frames:v", str(frames),
           "-c:v", "qtrle", "-pix_fmt", "argb", out], out)


def render_orig_audio(m, frames, fps, vol, out):
    """The clip's own sound, ducked, padded/cut to the exact length. None if the clip has no audio."""
    if not probe_media(m["file"])["has_audio"]:
        return None
    total = frames / fps
    use = min(m["avail"], total)
    ffrun(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{m['start']:.3f}", "-t", f"{use:.3f}",
           "-i", m["file"], "-vn", "-af", f"volume={vol},apad=whole_dur={total:.6f}", "-t", f"{total:.6f}",
           "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le", out], out)
    return out


def silent_wav(frames, fps, out):
    total = frames / fps
    if not os.path.exists(out) or abs(get_duration(out) - total) > 0.02:
        ffrun(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"anullsrc=r={SAMPLE_RATE}:cl=stereo", "-t", f"{total:.6f}", "-c:a", "pcm_s16le", out], out)
    return out


def keep_audio_volume(seg):
    v = seg.get("keep_audio")
    if v in (None, False, 0, "0", "false", "False"):
        return 0.0
    if v is True or v in ("true", "True"):
        return float(CFG.get("keep_audio_volume", 0.30))
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return float(CFG.get("keep_audio_volume", 0.30))


def build_items(segments, fps, W, H, clips_dir, fill, render=True, gfx=True, label="clips"):
    """For every segment that has narration audio: picture clip (+ original audio, + overlay).
    Returns items in order. render=False only fits the audio (used for .srt)."""
    need("ffmpeg", "ffprobe")
    os.makedirs(clips_dir, exist_ok=True)
    cache = Cache(os.path.join(clips_dir, "_cache.json"))
    acache = Cache(os.path.join(TRIM_DIR, "_cache.json"))
    dv = default_video()
    print(f"Building {len(segments)} {label}"
          + (f" (source: {dv})" if dv else "") + f" at {W}x{H} {fps}fps, fill={fill}...\n")
    items = []
    for n_seg, seg in enumerate(segments):
        sid = seg.get("id")
        if not sid:
            continue
        progress(n_seg, len(segments), f"Rendering {sid}")
        if not os.path.exists(os.path.join(AUDIO_DIR, f"{sid}.mp3")):
            print(f"[-] Skipping {sid}: no audio/{sid}.mp3 (run the voice step first)")
            continue
        try:
            wav, frames = fit_audio(sid, fps, acache)
            total = frames / fps
            m = seg_media(seg, dv)
            clip = os.path.join(clips_dir, f"{sid}.mp4")
            tag, note = "", ""
            if render:
                if m["kind"] == "video":
                    use = min(m["avail"], total)
                    key = f"video|{file_sig(m['file'])}|{m['start']:.3f}|{use:.3f}|{frames}|{fps}|{W}x{H}|{fill}|v3"
                    drawfn = lambda: render_video_clip(m, frames, W, H, fps, clip, fill)
                    if m["avail"] > total + 0.05:
                        note = f"footage trimmed by {m['avail'] - total:.2f}s to fit voice"
                    elif total > m["avail"] + 0.05:
                        note = f"last frame held {total - m['avail']:.2f}s (voice is longer than the clip)"
                    else:
                        note = "perfect fit"
                elif m["kind"] == "image":
                    key = f"image|{file_sig(m['file'])}|{frames}|{fps}|{W}x{H}|v3"
                    drawfn = lambda: render_image_clip(m, frames, W, H, fps, clip)
                    note = "still image, slow zoom"
                else:
                    stext = json.dumps(seg.get("shot") or {}, sort_keys=True) + m.get("why", "")
                    key = f"slate|{h8(stext)}|{sid}|{frames}|{fps}|{W}x{H}|v3"
                    drawfn = lambda: render_slate(seg, m.get("why", ""), frames, W, H, fps, clip)
                    note = f"SLATE - {m.get('why', 'missing')}"
                if cache.fresh(sid, key, clip):
                    tag = "cached  "
                else:
                    drawfn()
                    cache.set(sid, key)
                    tag = "rendered"
                vdur = get_duration(clip)
                if abs(vdur - total) > 1.5 / fps:
                    print(f"    [!] warning: {sid} clip is {vdur:.3f}s but should be {total:.3f}s")
            item = {"id": sid, "kind": m["kind"], "media": m, "video_file": os.path.abspath(clip),
                    "audio_file": os.path.abspath(wav), "frames": frames, "text": sub_text(seg),
                    "caption": str(seg.get("caption") or "").strip(), "rank": seg.get("rank"),
                    "chapter": str(seg.get("chapter") or "").strip(), "orig_file": None,
                    "gfx_file": None, "seg": seg}

            if render and m["kind"] == "video":
                vol = keep_audio_volume(seg)
                if vol > 0:
                    of = os.path.join(TRIM_DIR, f"{fps}fps", f"{sid}_orig.wav")
                    okey = f"orig|{file_sig(m['file'])}|{m['start']:.3f}|{frames}|{fps}|{vol}|{SAMPLE_RATE}"
                    if cache.fresh(sid + "#orig", okey, of):
                        item["orig_file"] = os.path.abspath(of)
                    elif render_orig_audio(m, frames, fps, vol, of):
                        cache.set(sid + "#orig", okey)
                        item["orig_file"] = os.path.abspath(of)
                    else:
                        print(f"    [i] {sid}: keep_audio asked but the clip has no audio track")
            if render and gfx and (item["caption"] or seg.get("rank") not in (None, "")):
                gf = os.path.join(GFX_DIR, f"{sid}.mov")
                os.makedirs(GFX_DIR, exist_ok=True)
                gkey = f"gfx|{seg.get('rank')}|{item['caption']}|{frames}|{fps}|{W}x{H}|{find_font()}|v1"
                if not cache.fresh(sid + "#gfx", gkey, gf):
                    render_gfx(seg.get("rank"), item["caption"], frames, W, H, fps, gf)
                    cache.set(sid + "#gfx", gkey)
                item["gfx_file"] = os.path.abspath(gf)
        except Exception as e:
            print(f"[!] Skipping {sid}: {e}")
            continue
        if render:
            print(f"[+] {tag} {sid:<10} {total:6.2f}s  {note}")
        items.append(item)

    progress(len(segments), len(segments), "Clips rendered")
    if not items:
        die("Nothing to build - no segment had audio. Run the voice step first.")
    return items


def make_music_bed(total_frames, fps, name="music_bed"):
    """First track in music/ -> one quiet bed exactly as long as the video (fade in/out). None if off."""
    if not PROJECT.get("music"):
        return None
    tracks = sorted(f for f in glob.glob(os.path.join(MUSIC_DIR, "*")) if f.lower().endswith(MUSIC_EXTS))
    if not tracks:
        print("[i] music is ON in project.json but music/ is empty - skipping the music bed.")
        return None
    total = total_frames / fps
    out = os.path.join(TRIM_DIR, f"{name}_{fps}fps.wav")
    os.makedirs(TRIM_DIR, exist_ok=True)
    vol = float(CFG.get("music_volume", 0.12))
    af = f"volume={vol},afade=t=in:d=2"
    if total > 6:
        af += f",afade=t=out:st={total - 3:.3f}:d=3"
    ffrun(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", tracks[0], "-t", f"{total:.6f}",
           "-af", af, "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le", out], out)
    print(f"[+] music bed: {os.path.basename(tracks[0])} at volume {vol}")
    return os.path.abspath(out)


def sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        el.text = str(text)
    return el


def add_rate(parent):
    r = sub(parent, "rate")
    sub(r, "timebase", FPS)
    sub(r, "ntsc", "FALSE")




# ====================================================================
# STEP 4A: Premiere sequence (multi-track XML)
#   V1 footage/stills/slates | V2 number & caption graphics
#   A1 voice-over | A2 original audio (ducked) | A3 music bed
# ====================================================================
def xml_tcode(parent):
    tc_ = sub(parent, "timecode")
    add_rate(tc_)
    sub(tc_, "string", "00:00:00:00")
    sub(tc_, "frame", 0)
    sub(tc_, "displayformat", "NDF")


def xml_vchars(parent):
    vsc_ = sub(parent, "samplecharacteristics")
    add_rate(vsc_)
    for tag_, val in (("width", WIDTH), ("height", HEIGHT), ("anamorphic", "FALSE"),
                      ("pixelaspectratio", "square"), ("fielddominance", "none")):
        sub(vsc_, tag_, val)


def xml_links(parent, idx):
    for mtype, cid in (("video", f"clipitem-v-{idx}"), ("audio", f"clipitem-a-{idx}")):
        ln = sub(parent, "link")
        sub(ln, "linkclipref", cid)
        sub(ln, "mediatype", mtype)
        sub(ln, "trackindex", 1)
        sub(ln, "clipindex", idx + 1)


def xml_video_clip(track, cid, name, path, start, n, alpha=False):
    vc = sub(track, "clipitem", id=cid)
    sub(vc, "masterclipid", "master-" + cid)
    sub(vc, "name", name)
    sub(vc, "enabled", "TRUE")
    sub(vc, "duration", n)
    add_rate(vc)
    sub(vc, "start", start)
    sub(vc, "end", start + n)
    sub(vc, "in", 0)
    sub(vc, "out", n)
    sub(vc, "alphatype", "straight" if alpha else "none")
    sub(vc, "pixelaspectratio", "square")
    sub(vc, "anamorphic", "FALSE")
    vfile = sub(vc, "file", id="file-" + cid)
    sub(vfile, "name", os.path.basename(path))
    sub(vfile, "pathurl", to_pathurl(path))
    add_rate(vfile)
    sub(vfile, "duration", n)
    xml_tcode(vfile)
    vm = sub(vfile, "media")
    xml_vchars(sub(vm, "video"))
    return vc


def xml_audio_clip(track, cid, name, path, start, n):
    ac = sub(track, "clipitem", id=cid, premiereChannelType="stereo")
    sub(ac, "masterclipid", "master-" + cid)
    sub(ac, "name", name)
    sub(ac, "enabled", "TRUE")
    sub(ac, "duration", n)
    add_rate(ac)
    sub(ac, "start", start)
    sub(ac, "end", start + n)
    sub(ac, "in", 0)
    sub(ac, "out", n)
    afile = sub(ac, "file", id="file-" + cid)
    sub(afile, "name", os.path.basename(path))
    sub(afile, "pathurl", to_pathurl(path))
    add_rate(afile)
    sub(afile, "duration", n)
    xml_tcode(afile)
    afm = sub(sub(afile, "media"), "audio")
    afsc = sub(afm, "samplecharacteristics")
    sub(afsc, "depth", 16)
    sub(afsc, "samplerate", SAMPLE_RATE)
    sub(afm, "channelcount", 2)
    st = sub(ac, "sourcetrack")
    sub(st, "mediatype", "audio")
    sub(st, "trackindex", 1)
    return ac


def write_premiere_xml(items, music):
    total = sum(i["frames"] for i in items)
    seq_name = os.path.basename(ROOT) or "Recap Sequence"
    root = ET.Element("xmeml", version="4")
    proj = sub(root, "project")
    sub(proj, "name", seq_name)
    kids = sub(proj, "children")
    seq = sub(kids, "sequence", id="sequence-1")
    sub(seq, "uuid", str(uuid.uuid4()))
    sub(seq, "duration", total)
    add_rate(seq)
    sub(seq, "name", seq_name)
    media = sub(seq, "media")

    v_el = sub(media, "video")
    xml_vchars(sub(v_el, "format"))
    v1 = sub(v_el, "track")
    v2 = sub(v_el, "track") if any(i["gfx_file"] for i in items) else None

    a_el = sub(media, "audio")
    sub(a_el, "numOutputChannels", 2)
    asc = sub(sub(a_el, "format"), "samplecharacteristics")
    sub(asc, "depth", 16)
    sub(asc, "samplerate", SAMPLE_RATE)

    def atrack():
        return sub(a_el, "track", currentExplodedTrackIndex="0", totalExplodedTrackCount="1",
                   premiereTrackType="Stereo")
    a1 = atrack()
    a2 = atrack() if any(i["orig_file"] for i in items) else None
    a3 = atrack() if music else None

    cur, markers = 0, []
    for idx, it in enumerate(items):
        n = it["frames"]
        vc = xml_video_clip(v1, f"clipitem-v-{idx}", it["id"], it["video_file"], cur, n)
        xml_links(vc, idx)
        ac = xml_audio_clip(a1, f"clipitem-a-{idx}", it["id"], it["audio_file"], cur, n)
        xml_links(ac, idx)
        if it["gfx_file"] and v2 is not None:
            label = (f"#{it['rank']} " if it["rank"] not in (None, "") else "") + (it["caption"] or "")
            xml_video_clip(v2, f"clipitem-g-{idx}", "GFX " + label.strip(), it["gfx_file"], cur, n, alpha=True)
        if it["orig_file"] and a2 is not None:
            xml_audio_clip(a2, f"clipitem-o-{idx}", it["id"] + " original", it["orig_file"], cur, n)
        if it["chapter"]:
            markers.append((cur, it["chapter"], "chapter"))
        if it["kind"] == "slate":
            markers.append((cur, f"MISSING: {it['id']}", it["media"].get("why", "")))
        cur += n
    if music and a3 is not None:
        xml_audio_clip(a3, "clipitem-m-0", "music bed", music, 0, total)

    for tr in (v1, v2, a1, a2, a3):
        if tr is not None:
            sub(tr, "enabled", "TRUE")
            sub(tr, "locked", "FALSE")
    xml_tcode(seq)
    for frame, name, comment in markers:
        mk = sub(seq, "marker")
        sub(mk, "comment", comment)
        sub(mk, "name", name)
        sub(mk, "in", frame)
        sub(mk, "out", -1)

    ET.indent(root)
    with open(XML_OUT, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' +
                ET.tostring(root, encoding="unicode"))
    return total, markers


# ====================================================================
# STEP 4D: VideoPad project (.vpj)
#   Same timeline as the Premiere XML, written in NCH VideoPad's own project format.
#   Format notes + the proof it was built from: videopad-agent-pipeline / docs/vpj-format-findings.md
#   V1 footage | V2 number & caption graphics | A1 voice-over | A2 original audio | A3 music
#   --simple: V1 + A1 only, picture and voice muxed into one file per segment.
# ====================================================================
VPJ_OUT = "videopad_project.vpj"
VPJ_AV_DIR = "clips_av"          # --simple: picture + voice muxed per segment
VPJ_FIRST_HANDLE = 3382          # hindex of the known-good template; new objects are numbered from here

# Fixed lines copied verbatim from a project VideoPad itself wrote (NCH VideoPad 8.91). The Computer_FilePath
# inside the export blob is the only value this writer changes: it sets the default export folder.
VPJ_EXPORT_BLOB = (
    "Type=2SubtitlesExport=1&Computer_Preset=Default&Computer_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmov"
    "ie.mp4&Portable_Preset=AppleiPhone6S_6SP&Portable_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie.mp4&"
    "360_Preset=Default&360_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie.mp4&Disc_Name=DiscName&Disc_Ima"
    "gePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmydvd.iso&Disc_IDDrive=255&Disc_DVD_NTSC=0&Disc_DVD_Widescreen"
    "=1&Disc_DVD_AutoBitrate=1&Disc_DVD_AverageBitrate=4000&Disc_DVD_MaximumBitrate=9000&Disc_DVD_AudioBi"
    "trate=96&Disc_DVD_Data_Preset=Widescreen%20TV&Disc_Bluray_Data_Preset=Widescreen%20TV&ImageSequence_"
    "FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie&ImageSequence_Format=0&ImageSequence_JPG_Quality=85&Im"
    "ageSequence_Width=1024&ImageSequence_Height=576&Upload_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie"
    ".mp4&Upload_DeleteFile=1&YouTube_Preset=YouTube%20720p&YouTube_FrameRate=30.000000&YouTube_ForceFixe"
    "dFrameRate=0&Youtube_Title=&Youtube_Description=&Youtube_CategoryID=&Youtube_Keywords=&Youtube_Priva"
    "cy=0&Flickr_Title=&Flickr_Description=&Flickr_Tags=&Flickr_Safety=1&Flickr_Public=1&Flickr_Friend=1&"
    "Flickr_Family=1&Flickr_Hidden=0&Vimeo_Title=&Vimeo_Resolution=&Vimeo_Description=&Vimeo_FrameRate=30"
    ".000000&Vimeo_IsAutoDetectedFrameRate=1&Vimeo_Privacy=0&Dropbox_Preset=720p&Dropbox_FilePath=C%3A%5C"
    "Users%5Cuser%5CVideos%5Cmovie.mp4&GoogleDrive_Preset=720p&GoogleDrive_FilePath=C%3A%5CUsers%5Cuser%5"
    "CVideos%5Cmovie.mp4&OneDrive_Preset=720p&OneDrive_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie.mp4&"
    "Stereoscopic_Preset=Widescreen%20TV&Stereoscopic_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie.mp4&S"
    "tereoscopic_StereoFormat=7&Stereoscopic_ConvertTo3D=1"
)
VPJ_EDITOUT = (
    "EditOutput_Settings=-1&EditOutput_Resize=0&EditOutput_ChangeFramerate=0&EditOutput_ForceFixedFramera"
    "te=0&EditOutput_ResizeType=0&EditOutput_Width=768&EditOutput_Height=576&EditOutput_ResizeKeepRatio=0"
    "&EditOutput_Framerate=30.000000"
)   # the template line ends in a lone CR; it is re-added when writing

VPJ_EXPORT_DEFAULT_PATH = "Computer_FilePath=C%3A%5CUsers%5Cuser%5CVideos%5Cmovie.mp4"
VPJ_SEQ_CACHE = "Seq9_1792790493_18467"   # template value; VideoPad re-derives it


def vpj_q(s):
    """URL-encode the way .vpj files do: C:\\Users\\a b -> C%3A%5CUsers%5Ca%20b ('.', '_', '-' stay)."""
    return urllib.parse.quote(str(s), safe="")


def vpj_ms(frames, fps):
    """Frame count -> milliseconds. Always converted from the running total so seams never drift."""
    return int(round(frames * 1000.0 / fps))


def vpj_media_lines(h, path, dur_ms, kind, h_pair=None, ctime=None, name=None):
    """Bin records. 'pair' = file with picture AND sound (two linked records, exactly as VideoPad writes
    them); 'video' / 'audio' = single-stream file (the same record without the link fields)."""
    name, p = vpj_q(name or os.path.basename(path)), vpj_q(path)
    ctime = int(ctime or time.time())
    thumb = 4500 if dur_ms > 4500 else dur_ms // 2     # 4500 = the placeholder VideoPad writes
    out = []
    if kind in ("pair", "audio"):
        link = f"&hlinked={h_pair}" if kind == "pair" else ""
        had = "&hadlinkedvideo=1" if kind == "pair" else ""
        out.append(f"h={h}&type=5&name={name}&path={p}&note=&creationtime={ctime}&hfolder=7{link}"
                   f"&in=0&out={dur_ms}{had}&thumbpos={thumb}&soundstreamindex=-1&isbackgroundsound=0")
    if kind in ("pair", "video"):
        hv = h_pair if kind == "pair" else h
        link = f"&hlinked={h}" if kind == "pair" else ""
        had = "&hadlinkedaudio=1" if kind == "pair" else ""
        out.append(f"h={hv}&type=3&sphen=0&sphho=0&sphve=0&name={name}&path={p}&note=&creationtime={ctime}"
                   f"&stereoformat=0&stereostretch=0&hfolder=6{link}&in=0&out={dur_ms}&thumb={thumb}{had}"
                   f"&thumbpos={thumb}")
    return out


def vpj_clip_line(h, media_h, name, offset, tin, tout, track_h, linked_h=None):
    link = f"&hlinked={linked_h}" if linked_h else ""
    return (f"h={h}&type=7&sphen=0&sphho=0&sphve=0&horiginalclip={media_h}&name={vpj_q(name)}"
            f"&offset={offset}&in={tin}&out={tout}{link}&fadeinduration=0&thumbpos=4500"
            f"&tlstart=0&tlend=0&tlstartoff=0&tlendoff=0&htrack={track_h}")


def vpj_chain_line(h, mute=0):
    return (f"size=0&fadepoints=0&speedchangef=1.000000&audiopitchchange=0&voll=0&volr=0"
            f"&mute={mute}&hclip={h}")


def assemble_vpj(seq_name, total_ms, n_vtracks, n_atracks, media, clips, export_path=None):
    """Build the text of a .vpj.

    media : list of {"key", "path", "dur", "kind": pair|video|audio, "ctime"?, "name"?}
    clips : list of {"media": key, "v": video-track number (1-based) or None, "a": audio-track number or None,
            "offset": ms on the timeline, "in": ms, "out": ms, "name"?}
    A 'pair' clip with both "v" and "a" is written as the linked picture+sound pair VideoPad makes.
    The trailing checksum is left stale on purpose: VideoPad then shows its 'Damaged File' prompt and
    'Try Load' opens the project untouched (the hash is a corruption warning, not a lock)."""
    nxt = [VPJ_FIRST_HANDLE]

    def new():
        nxt[0] += 1
        return nxt[0] - 1

    SEQ, SUBT = 9, 10
    # tracks: audio tracks first, then video tracks, as the template lists them; track 1 reuses 11 / 12
    atr = [11] + [new() for _ in range(n_atracks - 1)]
    vtr = [12] + [new() for _ in range(n_vtracks - 1)]
    track_lines = []
    for i, h in enumerate(atr, 1):
        track_lines.append(f"h={h}&type=2&name=Audio%20Track%20{i}&output=1&solo=0&volume=100&pan=0&collapsed0=0"
                           f"&collapsed1=0&collapsed2=1&collapsed3=0&collapsed4=0&collapsed5=0&collapsed6=0"
                           f"&collapsed7=0&locked=0&hsequence={SEQ}")
    for i, h in enumerate(vtr, 1):
        track_lines.append(f"h={h}&type=1&name=Video%20Track%20{i}&output=1&solo=0&collapsed0=0&collapsed1=0"
                           f"&collapsed2=0&collapsed3=0&collapsed4=1&collapsed5=0&collapsed6=0&collapsed7=0"
                           f"&locked=0&hsequence={SEQ}")

    # bin: audio record first, then its picture record (the order VideoPad writes them)
    mh, media_lines, chain_h = {}, [], []
    for m in media:
        h = new()
        hp = new() if m["kind"] == "pair" else None
        kind = m["kind"]
        media_lines += vpj_media_lines(h, m["path"], m["dur"], kind, hp, m.get("ctime"), m.get("name"))
        if kind == "pair":
            mh[m["key"]] = {"a": h, "v": hp}
        elif kind == "audio":
            mh[m["key"]] = {"a": h}
        else:
            mh[m["key"]] = {"v": h}
        chain_h += [x for x in (h, hp) if x]

    clip_lines, clip_h = [], []
    for c in clips:
        m = mh[c["media"]]
        src = next(x for x in media if x["key"] == c["media"])
        nm = c.get("name") or src.get("name") or os.path.basename(src["path"])
        hv = new() if c.get("v") else None
        ha = new() if c.get("a") else None
        both = hv and ha
        if ha:
            clip_lines.append(vpj_clip_line(ha, m["a"], nm, c["offset"], c["in"], c["out"],
                                            atr[c["a"] - 1], hv if both else None))
        if hv:
            clip_lines.append(vpj_clip_line(hv, m["v"], nm, c["offset"], c["in"], c["out"],
                                            vtr[c["v"] - 1], ha if both else None))
        clip_h += [x for x in (ha, hv) if x]

    export = VPJ_EXPORT_BLOB
    if export_path:
        export = export.replace(VPJ_EXPORT_DEFAULT_PATH, "Computer_FilePath=" + vpj_q(export_path))

    seq = (f"h={SEQ}&type=6&sphen=0&sphho=0&sphve=0&name={vpj_q(seq_name)}&note=&hfolder=5&duration={total_ms}"
           f"&in=0&out={total_ms}&thumb=1440000&seqcachename={VPJ_SEQ_CACHE}&thumbpos=1440000&timelinepos=0"
           f"&selected=1")
    chains = [vpj_chain_line(h) for h in clip_h] + [vpj_chain_line(SEQ)] + [vpj_chain_line(h) for h in chain_h]
    L = ["version=11", f"hindex={nxt[0]}", "folders=4",
         "h=8&name=Images&hfolder=0&open=0&type=2&foldertype=4&selected=0",
         "h=7&name=Audio%20Files&hfolder=0&open=0&type=5&foldertype=2&selected=0",
         "h=6&name=Video%20Files&hfolder=0&open=1&type=3&foldertype=1&selected=1",
         "h=5&name=Sequences&hfolder=0&open=0&type=6&foldertype=3&selected=0",
         f"clips={1 + len(media_lines)}&relativepaths=0", seq] + media_lines
    L += [f"tracks={len(track_lines)}"] + track_lines
    L += [f"trackclips={len(clip_lines)}"] + clip_lines
    L += ["subtitletracks=1", f"h={SUBT}&name=&subtitlechannels=0&hsequence={SEQ}", "subtitleclips=0",
          "transitions=0", f"effectchains={len(chains)}"] + chains
    L += ["groups=0", "bookmarks=0", export, VPJ_EDITOUT + "\r", "wizardused=0", "revision=565488",
          "checksum=" + "0" * 64]
    return "\n".join(L) + "\n"


def check_vpj(text):
    """Structural self-check of a .vpj: counts match, every handle that is referenced exists, links are
    mutual, clips stay inside their source, the sequence is exactly as long as its last clip. Returns a
    list of problems (empty = consistent)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    bad, sec, i = [], {}, 0

    def q(line):
        out = {}
        for part in line.split("&"):
            k, _, v = part.partition("=")
            out[k] = v
        return out

    if not lines or lines[0] != "version=11":
        bad.append("first line is not version=11")
    while i < len(lines):
        k, _, v = lines[i].partition("=")
        if k in ("folders", "tracks", "trackclips", "subtitletracks", "subtitleclips", "transitions",
                 "effectchains", "groups", "bookmarks"):
            n = int(v)
            sec[k] = [q(x) for x in lines[i + 1:i + 1 + n]]
            if len(sec[k]) != n:
                bad.append(f"{k}={n} but the file ends after {len(sec[k])} lines")
            i += 1 + n
        elif k == "clips":
            n = int(v.split("&")[0])
            sec[k] = [q(x) for x in lines[i + 1:i + n + 1]]
            if len(sec[k]) != n:
                bad.append(f"clips={n} but the file ends after {len(sec[k])} lines")
            i += 1 + n
        else:
            i += 1
    for need in ("clips", "tracks", "trackclips", "effectchains"):
        if need not in sec:
            bad.append(f"section '{need}' is missing")
    if bad:
        return bad
    seqs = [c for c in sec["clips"] if c.get("type") == "6"]
    media = {c["h"]: c for c in sec["clips"] if c.get("type") in ("3", "5")}
    tracks = {t["h"]: t for t in sec["tracks"]}
    if len(seqs) != 1:
        bad.append(f"expected 1 sequence record, found {len(seqs)}")
    handles = [c["h"] for c in sec["clips"]] + list(tracks) + [c["h"] for c in sec["trackclips"]]
    if len(set(handles)) != len(handles):
        bad.append("a handle is used twice")
    end = 0
    byh = {c["h"]: c for c in sec["trackclips"]}
    for c in sec["trackclips"]:
        m = media.get(c.get("horiginalclip"))
        t = tracks.get(c.get("htrack"))
        if m is None:
            bad.append(f"clip {c['h']}: horiginalclip {c.get('horiginalclip')} is not in the bin")
            continue
        if t is None:
            bad.append(f"clip {c['h']}: htrack {c.get('htrack')} does not exist")
            continue
        if (t["type"] == "1") != (m["type"] == "3"):
            bad.append(f"clip {c['h']}: a {'video' if m['type'] == '3' else 'audio'} source sits on a "
                       f"{'video' if t['type'] == '1' else 'audio'} track")
        tin, tout, off = int(c["in"]), int(c["out"]), int(c["offset"])
        if not (0 <= tin < tout <= int(m["out"])):
            bad.append(f"clip {c['h']}: trim {tin}-{tout} is outside its source (0-{m['out']})")
        end = max(end, off + tout - tin)
        if c.get("hlinked"):
            o = byh.get(c["hlinked"])
            if o is None or o.get("hlinked") != c["h"]:
                bad.append(f"clip {c['h']}: link to {c['hlinked']} is not mutual")
    for m in media.values():
        if m.get("hlinked") and media.get(m["hlinked"], {}).get("hlinked") != m["h"]:
            bad.append(f"bin item {m['h']}: link to {m['hlinked']} is not mutual")
    chains = [c.get("hclip") for c in sec["effectchains"]]
    want = [c["h"] for c in sec["trackclips"]] + [seqs[0]["h"]] + list(media)
    if sorted(chains) != sorted(want):
        bad.append("effectchains do not cover exactly the clips, the sequence and the bin items")
    if seqs and (int(seqs[0]["duration"]) != end or seqs[0]["out"] != seqs[0]["duration"]):
        bad.append(f"sequence is {seqs[0]['duration']} ms but its last clip ends at {end} ms")
    return bad


def write_vpj(path, text):
    # newline="\n": the file is LF-terminated like VideoPad's own (Windows must not turn it into CRLF)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write(text)


def vpj_mux_av(it, out_dir=VPJ_AV_DIR):
    """--simple: picture + voice in ONE file so VideoPad sees an ordinary video-with-sound source."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, it["id"] + ".mp4")
    cache = Cache(os.path.join(out_dir, "_cache.json"))
    key = f"{file_sig(it['video_file'])}|{file_sig(it['audio_file'])}|{it['frames']}|{FPS}|v1"
    if not cache.fresh(it["id"], key, out):
        ffrun(["ffmpeg", "-y", "-loglevel", "error", "-i", it["video_file"], "-i", it["audio_file"],
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{it['frames'] / FPS:.6f}", "-movflags", "+faststart", out], out)
        cache.set(it["id"], key)
    return os.path.abspath(out)


def write_videopad_project(items, music, simple=False, out=VPJ_OUT):
    """Same timeline as write_premiere_xml, as a .vpj. Returns (total_ms, problems)."""
    total_frames = sum(i["frames"] for i in items)
    total_ms = vpj_ms(total_frames, FPS)
    seq_name = os.path.basename(ROOT) or "Recap Sequence"
    media, clips = [], []
    has_gfx = (not simple) and any(i["gfx_file"] for i in items)
    has_orig = (not simple) and any(i["orig_file"] for i in items)
    has_music = (not simple) and bool(music)
    cur = 0
    for idx, it in enumerate(items):
        off, end = vpj_ms(cur, FPS), vpj_ms(cur + it["frames"], FPS)
        n = end - off
        if simple:
            f = vpj_mux_av(it)
            media.append({"key": f"s{idx}", "path": f, "dur": n, "kind": "pair"})
            clips.append({"media": f"s{idx}", "v": 1, "a": 1, "offset": off, "in": 0, "out": n})
        else:
            media.append({"key": f"v{idx}", "path": it["video_file"], "dur": n, "kind": "video"})
            media.append({"key": f"a{idx}", "path": it["audio_file"], "dur": n, "kind": "audio"})
            clips.append({"media": f"v{idx}", "v": 1, "a": None, "offset": off, "in": 0, "out": n})
            clips.append({"media": f"a{idx}", "v": None, "a": 1, "offset": off, "in": 0, "out": n})
            if has_gfx and it["gfx_file"]:
                media.append({"key": f"g{idx}", "path": it["gfx_file"], "dur": n, "kind": "video"})
                clips.append({"media": f"g{idx}", "v": 2, "a": None, "offset": off, "in": 0, "out": n})
            if has_orig and it["orig_file"]:
                media.append({"key": f"o{idx}", "path": it["orig_file"], "dur": n, "kind": "audio"})
                clips.append({"media": f"o{idx}", "v": None, "a": 2, "offset": off, "in": 0, "out": n})
        cur += it["frames"]
    if has_music:
        media.append({"key": "music", "path": music, "dur": total_ms, "kind": "audio"})
        clips.append({"media": "music", "v": None, "a": 2 + (1 if has_orig else 0), "offset": 0,
                      "in": 0, "out": total_ms, "name": "music bed"})
    n_v = 2 if has_gfx else 1
    n_a = 1 + (1 if has_orig else 0) + (1 if has_music else 0)
    text = assemble_vpj(seq_name, total_ms, n_v, n_a, media, clips,
                        export_path=os.path.abspath(os.path.splitext(out)[0] + ".mp4"))
    problems = check_vpj(text)
    write_vpj(out, text)
    return total_ms, problems


def step_videopad(args):
    data = load_data(find_json(args.json))
    segments = yt_segments(data)
    if not segments:
        die("No 'youtube' segments in the JSON.")
    simple = bool(getattr(args, "simple", False))
    items = build_items(segments, FPS, WIDTH, HEIGHT, CLIPS_DIR, CFG.get("fill", "pad"),
                        gfx=not simple, label="segments")
    music = None if simple else make_music_bed(sum(i["frames"] for i in items), FPS)
    total_ms, problems = write_videopad_project(items, music, simple)
    write_extras(items)
    write_shot_manifest(segments, default_video())

    slates = [i["id"] for i in items if i["kind"] == "slate"]
    print(f"\nDone. '{VPJ_OUT}' written: {len(items)} segments, {fmt_mmss(total_ms / 1000)}"
          + (" (simple: picture + voice only)." if simple else "."))
    if problems:
        print("[!] The project failed its own consistency check - please send this to whoever maintains the tool:")
        for p in problems[:12]:
            print("    -", p)
    if slates:
        print(f"[!] {len(slates)} placeholder slate(s) on V1 (missing footage): {', '.join(slates[:12])}"
              + (" ..." if len(slates) > 12 else "") + "\n    Add the footage (collect step), run this again - slates are replaced.")
    print("In VideoPad: File > Open Project > pick the .vpj (or double-click it).\n"
          "VideoPad will say 'The provided file may be damaged' - that is expected, click Try Load (it can appear more than once).\n"
          + ("Tracks: V1 picture | A1 voice (one file per segment)."
             if simple else
             "Tracks: V1 footage | V2 number/caption graphics | A1 voice | A2 original sound | A3 music."))
    print("If VideoPad refuses the full project, run it again with 'Build VideoPad project (simple)'.")
    print_srt_help()
    print("Keep clips/, clips_av/, gfx/ and audio_trim/ where they are (the project stores paths, not media).")
    reveal(".")


def write_extras(items):
    """captions .srt, on-screen text .srt, chapters, shot manifest."""
    write_timeline_srt(items)
    lab = []
    for it in items:
        t = ""
        if it["rank"] not in (None, ""):
            t = f"#{it['rank']}"
        if it["caption"]:
            t = (t + "  " if t else "") + it["caption"]
        lab.append((t, it["frames"]))
    if any(t for t, _ in lab):
        n = write_srt(ONSCREEN_SRT, lab, FPS)
        print(f"[+] on-screen text: {n} cue(s) -> {ONSCREEN_SRT} "
              "(backup option: import as captions if the graphics on V2 don't show)")
    cur, ch = 0, []
    for it in items:
        if it["chapter"]:
            ch.append((cur / FPS, it["chapter"]))
        cur += it["frames"]
    if ch:
        if ch[0][0] > 0.5:
            ch.insert(0, (0.0, "Intro"))
        with open(CHAPTERS_OUT, "w", encoding="utf-8") as f:
            for t, name in ch:
                f.write(f"{fmt_mmss(t)} {name}\n")
        print(f"[+] chapters: {len(ch)} -> {CHAPTERS_OUT} (paste into the YouTube description)")


def step_premiere(args):
    data = load_data(find_json(args.json))
    segments = yt_segments(data)
    if not segments:
        die("No 'youtube' segments in the JSON.")
    items = build_items(segments, FPS, WIDTH, HEIGHT, CLIPS_DIR, CFG.get("fill", "pad"),
                        label="segments")
    music = make_music_bed(sum(i["frames"] for i in items), FPS)
    total, markers = write_premiere_xml(items, music)
    write_extras(items)
    write_shot_manifest(segments, default_video())

    slates = [i["id"] for i in items if i["kind"] == "slate"]
    print(f"\nDone. '{XML_OUT}' written: {len(items)} segments, {fmt_mmss(total / FPS)}.")
    if slates:
        print(f"[!] {len(slates)} placeholder slate(s) on V1 (missing footage): {', '.join(slates[:12])}"
              + (" ..." if len(slates) > 12 else "") + "\n    Add the footage (collect step), run this again - slates are replaced.")
    print("In Premiere: File > Import > pick the XML. Double-click the sequence in the Project panel.\n"
          "Tracks: V1 footage | V2 number/caption graphics | A1 voice | A2 original sound | A3 music.")
    print_srt_help()
    print("Keep clips/, gfx/ and audio_trim/ where they are.")
    reveal(".")


def write_concat_list(path, files):
    with open(path, "w", encoding="utf-8") as f:
        for p in files:
            q = os.path.abspath(p).replace(os.sep, "/").replace("'", "'\\''")
            f.write(f"file '{q}'\n")




# ====================================================================
# STEP 4B: one finished video (picture + voice-over [+ original audio] [+ music])
# ====================================================================
def join_av(items, out, vlist_name, music=None):
    """Concats the picture clips and mixes narration (+ ducked original audio + music) into one mp4."""
    os.makedirs(TIKTOK_TEMP, exist_ok=True)
    vlist = os.path.join(TIKTOK_TEMP, f"{vlist_name}_video.txt")
    alist = os.path.join(TIKTOK_TEMP, f"{vlist_name}_audio.txt")
    olist = os.path.join(TIKTOK_TEMP, f"{vlist_name}_orig.txt")
    write_concat_list(vlist, [i["video_file"] for i in items])
    write_concat_list(alist, [i["audio_file"] for i in items])
    use_orig = any(i["orig_file"] for i in items)
    if use_orig:
        files = []
        for i in items:
            if i["orig_file"]:
                files.append(i["orig_file"])
            else:
                sf = os.path.join(TRIM_DIR, f"{i['fps']}fps", f"{i['id']}_sil.wav")
                files.append(silent_wav(i["frames"], i["fps"], sf))
        write_concat_list(olist, files)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", vlist,
           "-f", "concat", "-safe", "0", "-i", alist]
    n_audio = 1
    if use_orig:
        cmd += ["-f", "concat", "-safe", "0", "-i", olist]
        n_audio += 1
    if music:
        cmd += ["-i", music]
        n_audio += 1
    if n_audio == 1:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        ins = "".join(f"[{k}:a]" for k in range(1, n_audio + 1))
        cmd += ["-filter_complex", f"{ins}amix=inputs={n_audio}:duration=longest:dropout_transition=0,"
                                   f"volume={n_audio}[a]", "-map", "0:v:0", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
            "-shortest", "-movflags", "+faststart", out]
    res = run(cmd)
    if res.returncode != 0 or not os.path.exists(out):
        die(f"Could not join the clips:\n{tail(res.stderr)}")


def step_video(args):
    data = load_data(find_json(args.json))
    segments = yt_segments(data)
    if not segments:
        die("No 'youtube' segments in the JSON.")
    items = build_items(segments, FPS, WIDTH, HEIGHT, CLIPS_DIR, CFG.get("fill", "pad"),
                        gfx=False, label="segments")
    for i in items:
        i["fps"] = FPS
    total = sum(i["frames"] for i in items) / FPS
    music = make_music_bed(sum(i["frames"] for i in items), FPS)
    print(f"\nJoining {len(items)} clips into {FINAL_OUT} ...")
    join_av(items, FINAL_OUT, "full", music)
    write_timeline_srt(items)
    got = get_duration(FINAL_OUT)
    print(f"\nDone. {FINAL_OUT}  ({got:.1f}s, expected {total:.1f}s)")
    if any(i["rank"] not in (None, "") or i["caption"] for i in items):
        print("[i] Number/caption graphics are NOT burned into the mp4 - use the Premiere XML for those.")
    if abs(got - total) > 1.0:
        print("[!] The length is off by more than a second - please send me a screenshot of this window.")
    reveal(FINAL_OUT)


# ====================================================================
# SUBTITLES (.srt) - text comes from the narration, timing from the real audio
# ====================================================================
PAUSE_W = {".": 8, "!": 8, "?": 8, "\u2026": 8, ",": 4, ";": 5, ":": 5, "\u2014": 4, "\u2013": 3}
ABBREVS = {"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "jr.", "sr.", "prof.", "mt.", "no."}


def sub_text(seg):
    """Subtitle text: the optional "subtitle" field if present (use it when you respell a
    name for the voice), otherwise the narration itself."""
    t = seg.get("subtitle") or seg.get("narration") or ""
    return strip_tags(t)


def split_sentences(text):
    parts = [p.strip() for p in re.findall(r'.*?(?:[.!?\u2026]+["\'\u201d\u2019)\]]*(?:\s+|$)|$)', text, re.S)
             if p.strip()]
    out = []
    for p in parts:
        if out and out[-1].split()[-1].lower() in ABBREVS:
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def wrap_lines(text, maxc, max_lines):
    """Wraps into at most max_lines lines; two lines are balanced."""
    words = text.split()
    if len(text) <= maxc:
        return [text]
    if max_lines == 2 and len(words) > 1:
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            score = max(len(a), len(b))
            if best is None or score < best[0]:
                best = (score, a, b)
        if best[0] <= maxc:
            return [best[1], best[2]]
    return textwrap.wrap(text, maxc) or [text]


def make_cues(text, start, dur, maxc, max_lines):
    """Splits one narration into subtitle cues spread over [start, start+dur].
    Returns [(t0, t1, 'line1\\nline2'), ...]."""
    text = " ".join(text.split())
    if not text or dur <= 0:
        return []

    def fits(s):
        return len(textwrap.wrap(s, maxc)) <= max_lines

    def chunk_words(s):
        out, cur = [], ""
        for w in s.split():
            cand = (cur + " " + w).strip()
            if cur and not fits(cand):
                out.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            out.append(cur)
        return out

    units = []
    for s in split_sentences(text):
        if fits(s):
            units.append(s)
            continue
        for cl in re.split(r"(?<=[,;:])\s+", s):
            units.extend([cl] if fits(cl) else chunk_words(cl))

    cues, cur = [], ""
    for u in units:
        cand = (cur + " " + u).strip()
        ended = bool(cur) and cur[-1] in ".!?\u2026\"'\u201d\u2019)"
        if cur and (not fits(cand) or (ended and len(cur) >= maxc * 0.7)):
            cues.append(cur)
            cur = u
        else:
            cur = cand
    if cur:
        cues.append(cur)

    # How long each cue stays up: proportional to how much is spoken, with a little extra
    # weight for the natural pause after commas / full stops (not after the very last one).
    weights = []
    for c in cues:
        w = sum(ch.isalnum() for ch in c) + sum(PAUSE_W.get(ch, 0) for ch in c)
        weights.append(max(1.0, float(w)))
    tail = len(cues[-1]) - len(cues[-1].rstrip(".!?\u2026,;:\"'\u201d\u2019)"))
    weights[-1] = max(1.0, weights[-1] - sum(PAUSE_W.get(ch, 0) for ch in cues[-1][len(cues[-1]) - tail:]))

    total = sum(weights)
    out, acc = [], 0.0
    for c, w in zip(cues, weights):
        t0 = start + dur * acc / total
        acc += w
        t1 = start + dur * acc / total
        out.append((t0, t1, "\n".join(wrap_lines(c, maxc, max_lines))))
    return out


def srt_time(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path, timeline, fps):
    """timeline = [(text, frames), ...] played back to back at `fps`.
    Cue times line up with the Premiere sequence / the finished video."""
    sc = CFG.get("subtitles", {})
    maxc = int(sc.get("max_chars_per_line", 42))
    max_lines = int(sc.get("max_lines", 2))
    n, cur, lines = 0, 0, []
    for text, frames in timeline:
        start, dur = cur / fps, frames / fps
        cur += frames
        cues = make_cues(text, start, dur, maxc, max_lines)
        for i, (t0, t1, body) in enumerate(cues):
            n += 1
            # end exactly where the next cue starts (no overlaps, no flicker)
            lines.append(f"{n}\n{srt_time(t0)} --> {srt_time(t1)}\n{body}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return n


def write_timeline_srt(items):
    n = write_srt(SRT_OUT, [(i["text"], i["frames"]) for i in items], FPS)
    print(f"[+] subtitles: {n} cue(s) -> {SRT_OUT}")
    return n


def print_srt_help():
    print("In Premiere: File > Import the .srt, then drag it from the Project panel onto the "
          "timeline (above V1). It lands on a captions track you can style in Window > Text.")




def step_srt(args):
    """Subtitles only (no video rendering): same timeline as the Premiere XML."""
    need("ffmpeg", "ffprobe")
    data = load_data(find_json(args.json))
    segments = yt_segments(data)
    if not segments:
        die("No 'youtube' segments in the JSON.")
    items = build_items(segments, FPS, WIDTH, HEIGHT, CLIPS_DIR, CFG.get("fill", "pad"),
                        render=False, label="segments")
    write_extras(items)
    print_srt_help()
    reveal(SRT_OUT)


# ====================================================================
# STEP 5: TikTok (9:16, blurred background)
# ====================================================================
def step_tiktok(args):
    need("ffmpeg", "ffprobe")
    data = load_data(find_json(args.json))
    parts = tiktok_parts(data)
    if not parts:
        die("No 'tiktok' section in the JSON.")
    os.makedirs(TIKTOK_OUT, exist_ok=True)
    t = CFG["tiktok"]
    W, H, tfps = int(t["width"]), int(t["height"]), int(t["fps"])
    made = 0
    for part, clips in parts.items():
        print(f"\n=== TikTok: {part} ===")
        items = build_items(clips, tfps, W, H, TIKTOK_TEMP, "blur", gfx=False, label=f"{part} clips")
        for i in items:
            i["fps"] = tfps
        music = make_music_bed(sum(i["frames"] for i in items), tfps, name=f"music_{part}")
        dest = os.path.join(TIKTOK_OUT, f"{part}.mp4")
        join_av(items, dest, part, music)
        made += 1
        print(f"SUCCESS: {dest}")
        srt_path = os.path.join(TIKTOK_OUT, f"{part}.srt")
        n_cues = write_srt(srt_path, [(i["text"], i["frames"]) for i in items], tfps)
        print(f"         subtitles: {srt_path} ({n_cues} cues)")
    if made == 0:
        die("No TikTok videos were produced.")
    print(f"\nDone. {made} video(s) in {TIKTOK_OUT}/")
    reveal(TIKTOK_OUT)


# ====================================================================
# STATUS + STATE.md
# ====================================================================
def status_lines(args_json=None):
    L = []
    L.append(f"Project : {os.path.basename(ROOT)}")
    L.append(f"Module  : {MODULE}   Topic: {PROJECT.get('topic') or '-'}   Style: {PROJECT.get('style')}")
    tg = PROJECT.get("target_length") or DEFAULT_TARGETS.get(MODULE, "")
    L.append(f"Target  : {tg}   TTS mode: {PROJECT.get('tts_mode')}   Music: {'on' if PROJECT.get('music') else 'off'}")
    dv = default_video()
    n_foot = len([f for f in glob.glob(FOOTAGE_DIR + "/*") if f.lower().endswith(VIDEO_EXTS)]) if os.path.isdir(FOOTAGE_DIR) else 0
    n_img = len([f for f in glob.glob(IMAGES_DIR + "/*") if f.lower().endswith(IMAGE_EXTS)]) if os.path.isdir(IMAGES_DIR) else 0
    L.append(f"Source  : {dv or 'no main video in folder'}   footage/: {n_foot} clip(s)   images/: {n_img}")
    L.append(f"Subtitles (.srt in subs/): {len(glob.glob(SUBS_DIR + '/*.srt'))}")
    L.append(f"Engine  : {CFG['tts']['engine'] or '-'}")
    nxt = []
    try:
        data = load_data(find_json(args_json))
    except SystemExit:
        L.append("segments.json: EMPTY - paste the JSON from Claude")
        return L, ["Get segments.json from Claude (see PASTE_THIS_TO_CLAUDE.txt)"]
    yt, tt, segs = yt_segments(data), tiktok_parts(data), all_segments(data)
    if not segs:
        L.append("segments.json: no segments yet")
        return L, ["Get segments.json from Claude (see PASTE_THIS_TO_CLAUDE.txt)"]
    have = sum(1 for s in segs if os.path.exists(os.path.join(AUDIO_DIR, f"{s['id']}.mp3")))
    need_vis = [s for s in yt if s.get("need_visual")]
    sheets_have = len(glob.glob(SHEETS_DIR + "/*.jpg"))
    miss = []
    for s in iter_segments(data):
        if s.get("id") and seg_media(s, dv)["kind"] == "slate":
            miss.append(s["id"])
    miss = sorted(set(miss))
    L.append(f"Segments: {len(yt)} youtube, {sum(len(v) for v in tt.values())} tiktok clips in {len(tt)} part(s)")
    L.append(f"Sheets  : {sheets_have} file(s), {len(need_vis)} segment(s) flagged need_visual")
    L.append(f"Footage : {len(miss)} segment(s) still without footage/still" + (f": {', '.join(miss[:10])}" if miss else ""))
    L.append(f"Audio   : {have} / {len(segs)} clips")
    L.append(f"Premiere XML: {'built' if os.path.exists(XML_OUT) else 'not built'}   "
             f"Full video: {'built' if os.path.exists(FINAL_OUT) else 'not built'}   "
             f"Subtitles: {'built' if os.path.exists(SRT_OUT) else 'not built'}   "
             f"TikTok: {len(glob.glob(TIKTOK_OUT + '/*.mp4'))} video(s)")
    if miss and MODULE not in RECAP_MODULES:
        nxt.append("Collect footage: run the collect step (missing shots show as slates in Premiere)")
    elif miss:
        nxt.append(f"{len(miss)} segment(s) have no footage - check 'src' / file names")
    if have < len(segs):
        nxt.append("Generate the voice-over (preview a few segments first)")
    if have == len(segs) and not os.path.exists(XML_OUT) and not os.path.exists(FINAL_OUT):
        nxt.append("Build the Premiere XML (or the finished video for recaps)")
    if not nxt:
        nxt.append("Nothing pending - review the output, or edit segments.json and re-run a step")
    return L, nxt


def write_state(args_json=None):
    try:
        L, nxt = status_lines(args_json)
    except Exception:
        return
    with open(STATE_MD, "w", encoding="utf-8") as f:
        f.write("# STATE (auto-written by Recap Studio - paste this into a new chat to resume)\n\n")
        f.write(time.strftime("Updated: %Y-%m-%d %H:%M\n\n"))
        f.write("\n".join("- " + l for l in L) + "\n\n## Next\n")
        f.write("\n".join(f"{i}. {n}" for i, n in enumerate(nxt, 1)) + "\n")


def step_check(args):
    print(f"Tools\n")
    for t in ("ffmpeg", "ffprobe"):
        print(f"  {t:<9} {'OK' if shutil.which(t) else 'MISSING  -> run SETUP.bat'}")
    print(f"  {'yt-dlp':<9} {'OK' if ytdlp_cmd() else 'MISSING  -> run SETUP.bat (only needed for the collect step)'}")
    for mod in ("requests", "edge_tts"):
        try:
            __import__(mod)
            print(f"  {mod:<9} OK")
        except ImportError:
            print(f"  {mod:<9} MISSING  -> run SETUP.bat")
    for k in ("ELEVENLABS_API_KEY", "MINIMAX_API_KEY"):
        raw = os.environ.get(k, "")
        n = len([x for x in raw.replace(" ", ",").split(",") if x.strip()])
        print(f"  {k:<19}: {str(n) + ' key(s)' if n else 'not set'}")
    print()
    L, nxt = status_lines(args.json)
    print("\n".join("  " + l for l in L))
    print("\n  NEXT:")
    for i, n in enumerate(nxt, 1):
        print(f"    {i}. {n}")
    write_state(args.json)
    print(f"\n  ({STATE_MD} updated)")
    if os.path.exists(os.path.join(AUDIO_DIR, "_manifest.json")):
        length_report(args)


# ====================================================================
# DEMO: synthetic media so you can test the whole pipeline (and Premiere import) in a minute
# ====================================================================
def step_demo(args):
    need("ffmpeg", "ffprobe")
    try:
        existing = all_segments(load_data(find_json(args.json)))
    except SystemExit:
        existing = []
    if existing and not args.force:
        die("This project already has segments. Run 'demo' in a FRESH project (or add --force to overwrite segments.json).")
    for d in (FOOTAGE_DIR, IMAGES_DIR, AUDIO_DIR):
        os.makedirs(d, exist_ok=True)

    def ff(*a):
        r = run(["ffmpeg", "-y", "-loglevel", "error"] + list(a))
        if r.returncode != 0:
            die(f"demo: ffmpeg failed\n{tail(r.stderr)}")

    ff("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=24:d=8", "-f", "lavfi", "-i", "sine=f=330:d=8",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", f"{FOOTAGE_DIR}/demo_a.mp4")
    ff("-f", "lavfi", "-i", "testsrc=s=640x480:r=30:d=8", "-f", "lavfi", "-i", "sine=f=523:d=8",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", f"{FOOTAGE_DIR}/demo_b_4x3.mp4")
    ff("-f", "lavfi", "-i", "testsrc2=s=1000x1000:d=1", "-frames:v", "1", f"{IMAGES_DIR}/demo_still.png")
    lens = {"d_01": 3.2, "d_02": 4.0, "d_03": 3.0, "d_04": 3.0, "d_05": 4.0}
    for sid, ln in lens.items():
        ff("-f", "lavfi", "-i", f"sine=f=220:d={ln}", "-c:a", "libmp3lame", f"{AUDIO_DIR}/{sid}.mp3")
    demo = {"youtube": [
        {"id": "d_01", "src": "demo_a.mp4", "src_start": "00:00:00", "src_end": "00:00:08", "keep_audio": True,
         "chapter": "Intro", "caption": "Chapter one starts here", "narration": "This is the first demo segment."},
        {"id": "d_02", "src": "demo_b_4x3.mp4", "src_start": "00:00:01", "src_end": "00:00:07", "rank": 3,
         "caption": "Third place", "narration": "A four by three clip gets pillarboxed."},
        {"id": "d_03", "image": "demo_still.png", "rank": 2, "caption": "Second place",
         "narration": "A still image with a slow zoom."},
        {"id": "d_04", "rank": 1, "chapter": "Finale", "caption": "First place",
         "shot": {"description": "Test shot that does not exist yet", "queries": ["demo clip youtube", "demo clip x", "demo image"],
                  "fallback": "any b-roll"}, "narration": "This shot is missing, so you get a slate."},
        {"id": "d_05", "src": "demo_a.mp4", "src_start": "00:00:06", "src_end": "00:00:08",
         "narration": "Short footage, long voice: the last frame is held."}], "tiktok": {}}
    with open("segments.json", "w", encoding="utf-8") as f:
        json.dump(demo, f, indent=2)
    print("Demo media + audio + segments.json created. Now run: Build Premiere XML, import it, "
          "and tell me what you see on V1/V2/A1/A2 and whether the markers appear.")


# ====================================================================
STEPS = {"init": step_init, "module": step_module, "subs": step_subs, "index": step_index,
         "sheets": step_sheets, "collect": step_collect, "tts": step_tts, "review": step_review,
         "premiere": step_premiere, "videopad": step_videopad, "video": step_video, "srt": step_srt, "tiktok": step_tiktok,
         "check": step_check, "demo": step_demo,
         "missing": step_missing, "collect_one": step_collect_one}
NO_STATE = ("init", "module", "demo", "missing", "collect_one")


def main():
    ap = argparse.ArgumentParser(description="Recap Studio engine")
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--video")
    ap.add_argument("--json")
    ap.add_argument("--pick", action="store_true", help="tts: choose engine/voice again")
    ap.add_argument("--force", action="store_true", help="redo existing outputs")
    ap.add_argument("--only", help="tts: comma-separated segment ids to (re)voice")
    ap.add_argument("--preview", action="store_true", help="tts: voice a few segments into audio_preview/")
    ap.add_argument("--import", dest="do_import", action="store_true", help="review: import edits from the CSV")
    ap.add_argument("--simple", action="store_true", help="videopad: picture + voice only (one muxed file per segment)")
    ap.add_argument("--retry", action="store_true", help="collect: ask again for skipped shots")
    ap.add_argument("--engine", choices=("edge", "elevenlabs", "minimax"), help="tts: skip the engine prompt")
    ap.add_argument("--yes", action="store_true", help="auto-confirm destructive / re-voice prompts")
    ap.add_argument("--id", help="collect_one: segment id")
    ap.add_argument("--url", help="collect_one: source URL")
    ap.add_argument("--range", help="collect_one: optional 'start-end' time range")
    ap.add_argument("--file", help="collect_one: local media file to copy in")
    ap.add_argument("--skip", action="store_true", help="collect_one: mark the shot as skipped")
    args = ap.parse_args()
    try:
        STEPS[args.step](args)
        if args.step not in NO_STATE:
            write_state(args.json)
    except KeyboardInterrupt:
        die("Cancelled.")
    except KeyError as e:
        die(f"Your segments JSON is missing a field: {e}")


if __name__ == "__main__":
    main()
