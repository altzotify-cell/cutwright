"""ffprobe/ffmpeg wrappers. Read-only: nothing here ever writes to its input."""
import json
import os
import shutil
import subprocess

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".mts",
              ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg")

# Same sets recap.py already uses, so the two stay in step.
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text",
                   "subviewer", "microdvd"}
IMAGE_SUB_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub",
                    "dvb_teletext"}


def have(tool):
    return shutil.which(tool) is not None


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def ffprobe_json(path, extra=None):
    cmd = ["ffprobe", "-v", "error", "-of", "json"]
    cmd += extra or ["-show_format", "-show_streams"]
    cmd.append(path)
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError("ffprobe failed on %s: %s" % (path, (r.stderr or "").strip()[:300]))
    return json.loads(r.stdout or "{}")


def _fps(stream):
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key) or ""
        if "/" in raw:
            num, den = raw.split("/", 1)
            try:
                num, den = float(num), float(den)
            except ValueError:
                continue
            if den:
                return round(num / den, 3)
        elif raw:
            try:
                return round(float(raw), 3)
            except ValueError:
                pass
    return 0.0


def media_info(path):
    """Everything Cutwright needs to know about one source file."""
    info = {
        "path": os.path.abspath(path),
        "name": os.path.basename(path),
        "exists": os.path.isfile(path),
        "duration": 0.0,
        "size": 0,
        "format": "",
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "video_codec": "",
        "audio": [],
        "subs": [],
    }
    if not info["exists"]:
        return info

    info["size"] = os.path.getsize(path)
    data = ffprobe_json(path)
    fmt = data.get("format", {}) or {}
    info["format"] = fmt.get("format_name", "")
    try:
        info["duration"] = round(float(fmt.get("duration", 0)), 3)
    except (TypeError, ValueError):
        info["duration"] = 0.0

    for st in data.get("streams", []) or []:
        kind = st.get("codec_type")
        tags = st.get("tags") or {}
        if kind == "video" and not info["video_codec"]:
            info["width"] = int(st.get("width") or 0)
            info["height"] = int(st.get("height") or 0)
            info["fps"] = _fps(st)
            info["video_codec"] = st.get("codec_name", "")
        elif kind == "audio":
            info["audio"].append({
                "codec": st.get("codec_name", ""),
                "channels": int(st.get("channels") or 0),
                "sample_rate": int(st.get("sample_rate") or 0),
                "language": tags.get("language", "und"),
            })
        elif kind == "subtitle":
            codec = st.get("codec_name", "")
            info["subs"].append({
                "index": int(st.get("index", -1)),
                "codec": codec,
                "language": tags.get("language", "und"),
                "title": tags.get("title", ""),
                "forced": bool((st.get("disposition") or {}).get("forced")),
                "text": codec in TEXT_SUB_CODECS,
                "picture": codec in IMAGE_SUB_CODECS,
            })
    return info


def extract_text_subs(video, info, out_dir, guard):
    """Pull every TEXT subtitle track out of the container. Picture subs are
    reported but never extracted -- they hold no text without OCR.

    For ASS/SSA we keep a native copy as well as the flattened .srt, and make
    the native copy the candidate: only the .ass keeps style names, which is how
    sign layers and vector drawings can be told apart from dialogue. Flattening
    to SRT first (what recap.py does) throws that information away and leaves
    drawing commands sitting in the transcript as if they were words.
    """
    saved = []
    for n, sub in enumerate(info["subs"]):
        if sub["picture"] or not sub["text"]:
            continue
        base = os.path.splitext(info["name"])[0]
        label = "%s.%d.%s" % (base, n, sub["language"] or "und")
        label = "".join(c if c.isalnum() or c in "-_." else "_" for c in label)
        guard.ensure_dir(out_dir)

        srt_out = os.path.join(out_dir, label + ".srt")
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", video,
                 "-map", "0:s:%d" % n, "-c:s", "srt", srt_out])
        srt_ok = r.returncode == 0 and os.path.isfile(srt_out)

        ass_out = None
        if sub["codec"] in ("ass", "ssa"):
            ass_out = os.path.join(out_dir, label + ".ass")
            r2 = run(["ffmpeg", "-y", "-loglevel", "error", "-i", video,
                      "-map", "0:s:%d" % n, "-c:s", "copy", ass_out])
            if r2.returncode != 0 or not os.path.isfile(ass_out):
                ass_out = None

        primary = ass_out or (srt_out if srt_ok else None)
        if not primary:
            continue
        saved.append({"path": primary, "language": sub["language"],
                      "codec": sub["codec"], "track": n,
                      "native": bool(ass_out),
                      "also": [p for p in (srt_out, ass_out) if p and p != primary]})
    return saved
