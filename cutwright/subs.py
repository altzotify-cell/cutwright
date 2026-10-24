"""Subtitle sources, parsing, and the validation gate.

Priority ladder (highest trust first), as agreed:

  1. a file the user points at          --subs FILE
  2. a sidecar next to the video        film.mp4 -> film.srt / film.vtt / film.ass
  3. a TEXT track embedded in the file  (extracted with ffmpeg)
  4. nothing usable                     -> "needs_whisper", and we say so

Rung 3 is only used if it passes the gate. Rung 4 never fabricates a transcript:
the caller decides whether to run Whisper, and a failed gate is reported loudly.

Why a gate at all: recap.py's extract_subs_from() faithfully pulls every track
out of the container, but a file that extracts cleanly can still be useless --
picture subs with no text, cp1251 read as UTF-8, subtitles for the extended cut
of a different edit, or the Spanish track. Cheap structural checks catch all of
those before they poison everything downstream.
"""
import os
import re

from . import probe

SRT_EXTS = (".srt", ".vtt", ".ass", ".ssa", ".sub")

# decoding candidates, most-likely first
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "cp1251")

TAG_RE = re.compile(r"\{[^}]*\}")          # ASS override blocks {\an8}
HTML_RE = re.compile(r"</?[a-zA-Z][^>]*>")  # <i>, <font ...>
BRACE_ONLY_RE = re.compile(r"^\{[^}]*\}$")

# mojibake tells: UTF-8 bytes read as cp1252/latin-1
MOJIBAKE_RE = re.compile(r"(Ã[\x80-\xbf]|â€|Ð[\x80-\xbf]|Ñ[\x80-\xbf]|Â[\x80-\xbf])")

TS_RE = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})")          # [H:]MM:SS[.,]mmm
TS_SHORT_RE = re.compile(r"^(\d{1,2}):(\d{1,2})[.,](\d{1,3})$")  # MM:SS.mmm


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------
def _score_text(text):
    """Higher is better: rewards letters/spaces, punishes replacement chars,
    control chars and mojibake markers."""
    if not text:
        return -1e9
    sample = text[:20000]
    n = len(sample)
    letters = sum(ch.isalpha() for ch in sample)
    spaces = sample.count(" ") + sample.count("\n")
    bad = sum(1 for ch in sample if ch in "\ufffd\x00\x01\x02\x03")
    moji = len(MOJIBAKE_RE.findall(sample))
    return (letters * 1.0 + spaces * 0.3 - bad * 8.0 - moji * 4.0) / max(n, 1)


def decode_bytes(raw):
    """-> (text, encoding, score, alternatives).

    Rule one: strict UTF-8 wins outright. Valid UTF-8 is an extremely strong
    signal -- random 8-bit text almost never validates -- and trusting it avoids
    a real trap: "..." in UTF-8 is e2 80 a6, which cp1251 happily turns into the
    Cyrillic letters "вЂ¦", scoring *higher* on any letter-counting metric.

    Only when UTF-8 fails do we weigh the legacy 8-bit candidates, where ASCII
    letters are the thing worth counting.
    """
    seen = []
    for enc in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        score = _score_text(text)
        seen.append({"encoding": enc, "score": round(score, 4)})
        return text, enc, score, seen

    best = None
    for idx, enc in enumerate(ENCODINGS):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        score = _score_text(text)
        seen.append({"encoding": enc, "score": round(score, 4)})
        # ties go to the earlier candidate: cp1252 before cp1251
        if best is None or score > best[3] + 0.02:
            best = (text, enc, score, idx)
    if best is None:                      # nothing decodes cleanly: last resort
        text = raw.decode("utf-8", errors="replace")
        return text, "utf-8/replace", _score_text(text), seen
    seen.sort(key=lambda d: -d["score"])
    return best[0], best[1], best[2], seen


# ---------------------------------------------------------------------------
# timestamps + cue parsing
# ---------------------------------------------------------------------------
def parse_ts(value):
    """'00:01:02,500' / '1:02.5' / '62.5' -> seconds (float) or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = TS_RE.search(value)
    if m:
        h = int(m.group(1) or 0)
        mi, se, frac = int(m.group(2)), int(m.group(3)), m.group(4)
        return h * 3600 + mi * 60 + se + int(frac.ljust(3, "0")) / 1000.0
    m = TS_SHORT_RE.match(value)
    if m:
        mi, se, frac = int(m.group(1)), int(m.group(2)), m.group(3)
        return mi * 60 + se + int(frac.ljust(3, "0")) / 1000.0
    return None


def clean_text(raw):
    r"""Strip ASS override blocks, HTML tags, styling; \N -> newline."""
    t = raw.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    t = TAG_RE.sub("", t)
    t = HTML_RE.sub("", t)
    t = t.replace("\u200b", "").replace("\ufeff", "")
    lines = [" ".join(line.split()) for line in t.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def styling_ratio(raw):
    """Share of characters that live inside markup rather than in the words."""
    if not raw:
        return 0.0
    markup = sum(len(m.group(0)) for m in TAG_RE.finditer(raw))
    markup += sum(len(m.group(0)) for m in HTML_RE.finditer(raw))
    markup += raw.count("\\N") * 2 + raw.count("\\n") * 2
    return markup / float(len(raw))


def _cues_from_blocks(text):
    """SRT and WebVTT: blank-line separated blocks with 'a --> b'."""
    cues, bad = [], []
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            left, right = line.split("-->", 1)
            start = parse_ts(left.strip())
            end = parse_ts(right.strip().split()[0]) if right.strip() else None
            body = "\n".join(lines[i + 1:])
            if start is None or end is None:
                bad.append(line.strip()[:80])
                break
            cues.append({"start": round(start, 3), "end": round(end, 3),
                         "text": clean_text(body), "raw": body})
            break
    return cues, bad


def _cues_from_ass(text):
    """ASS/SSA: [Events] with a Format: header and Dialogue: rows."""
    cues, bad = [], []
    section, order = None, None
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].lower()
            continue
        if section != "events":
            continue
        if s.lower().startswith("format:"):
            order = [p.strip().lower() for p in s.split(":", 1)[1].split(",")]
            continue
        if not s.lower().startswith("dialogue:"):
            continue
        payload = s.split(":", 1)[1]
        order = order or ["layer", "start", "end", "style", "name",
                          "marginl", "marginr", "marginv", "effect", "text"]
        # Text is the last field and may itself contain commas.
        parts = payload.split(",", len(order) - 1)
        row = dict(zip(order, parts))
        start, end = parse_ts(row.get("start", "")), parse_ts(row.get("end", ""))
        if start is None or end is None:
            bad.append(payload[:80])
            continue
        cues.append({"start": round(start, 3), "end": round(end, 3),
                     "text": clean_text(row.get("text", "")),
                     "raw": row.get("text", ""),
                     "style": row.get("style", "")})
    return cues, bad


DRAWING_RE = re.compile(r"^\s*[mlbsqc]\s+-?\d")
DRAW_TAG_RE = re.compile(r"\\p[1-9]")
# Styles that carry spoken dialogue. Anything else in a fansub .ass is a sign,
# a song lyric, a phone screen or a vector drawing of a logo.
DIALOGUE_STYLES = {"", "default", "dialogue", "main", "sub", "subtitle",
                   "eng", "english", "cc", "dialog"}


def looks_like_drawing(text):
    """ASS vector art converted to text looks like 'm -362 77 l -362 77 ...'."""
    t = (text or "").strip()
    if not t:
        return False
    if DRAWING_RE.match(t):
        return True
    letters = sum(ch.isalpha() for ch in t)
    return letters == 0 and any(ch.isdigit() for ch in t)


def is_drawing(cue):
    return bool(DRAW_TAG_RE.search(cue.get("raw", ""))) or looks_like_drawing(cue["text"])


def filter_cues(cues, by_style=False):
    """Drop vector drawings, and for native .ass also drop decorative styles.

    Returns (kept, summary). The summary is reported so a cleaned-up track never
    looks identical to a pristine one -- if we removed 3000 sign layers, you
    should see that.
    """
    kept, styles, drawings = [], {}, 0
    for cue in cues:
        if is_drawing(cue):
            drawings += 1
            continue
        if by_style:
            style = (cue.get("style") or "").strip()
            if style.lower() not in DIALOGUE_STYLES:
                styles[style] = styles.get(style, 0) + 1
                continue
        kept.append(cue)

    # Safety net: if style filtering left almost nothing of the *text* cues (an
    # unusual release with no recognised dialogue style), fall back to every
    # non-drawing cue rather than handing back an empty transcript. Measured
    # against the non-drawing count, because fansub .ass files are mostly signs
    # and songs -- comparing to the raw total made this fire on healthy files.
    non_drawing = len(cues) - drawings
    if by_style and non_drawing and len(kept) < max(10, non_drawing * 0.05):
        kept = [c for c in cues if not is_drawing(c)]
        styles = {"(unfiltered: no dialogue style found)": non_drawing - len(kept)}


    return kept, {"drawings": drawings, "styles": styles,
                  "input": len(cues), "kept": len(kept)}


def load_cues(path):
    """Read one subtitle file -> dict with cues, encoding, format and cleanup."""
    with open(path, "rb") as f:
        raw = f.read()
    text, encoding, score, alts = decode_bytes(raw)
    ext = os.path.splitext(path)[1].lower()
    head = text[:2000].lower()
    if ext in (".ass", ".ssa") or "[events]" in head:
        fmt = "ass"
        cues, bad = _cues_from_ass(text)
    elif ext == ".vtt" or head.lstrip().startswith("webvtt"):
        fmt = "vtt"
        cues, bad = _cues_from_blocks(text)
    else:
        fmt = "srt"
        cues, bad = _cues_from_blocks(text)

    # Drop cues whose text vanished after cleaning (pure styling rows).
    cues = [c for c in cues if c["text"]]
    cues, dropped = filter_cues(cues, by_style=(fmt == "ass"))

    # ASS stores events in layer order, not time order, so filtering by style can
    # leave the list shuffled. Everything downstream assumes sorted cues.
    reordered = 0
    for i in range(1, len(cues)):
        if cues[i]["start"] < cues[i - 1]["start"] - 0.001:
            reordered += 1
    if reordered:
        cues.sort(key=lambda c: (c["start"], c["end"]))
    dropped["reordered"] = reordered

    return {"path": os.path.abspath(path), "format": fmt, "encoding": encoding,
            "encoding_score": round(score, 4), "encodings": alts,
            "cues": cues, "bad_lines": bad[:20], "bytes": len(raw),
            "dropped": dropped}



# Function-word frequency. Script alone cannot separate Spanish from English --
# both are Latin -- so the giveaway is which little words carry the sentence.
STOPWORDS = {
    "english": {"the", "and", "you", "that", "was", "for", "are", "with", "his",
                "her", "they", "this", "have", "from", "not", "but", "what", "all",
                "when", "your", "just", "know", "like", "did", "she", "him",
                "there", "their", "been", "would", "about", "were", "will"},
    "spanish": {"el", "la", "los", "las", "que", "de", "en", "un", "una", "por",
                "con", "para", "se", "su", "es", "lo", "como", "pero", "sus", "le",
                "ya", "este", "porque", "cuando", "muy", "sin", "hay", "todo",
                "bien", "aquí", "nada", "quiero", "tiene", "está", "eres"},
    "french": {"le", "les", "des", "est", "pour", "dans", "qui", "pas", "vous",
               "nous", "sur", "avec", "plus", "mais", "ce", "je", "tu", "il",
               "elle", "son", "sont", "être", "tout", "bien", "moi", "toi"},
    "portuguese": {"não", "uma", "para", "com", "isso", "você", "os", "as", "do",
                   "da", "em", "um", "é", "se", "mais", "como", "mas", "foi",
                   "ele", "ela", "muito", "aqui", "está", "tem", "vou"},
    "german": {"der", "das", "und", "nicht", "ich", "du", "ist", "es", "sie", "wir",
               "was", "mit", "auf", "für", "ein", "eine", "zu", "den", "dem",
               "sich", "auch", "aber", "noch", "nur", "mich", "dich"},
}
TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_language(text):
    """-> {"guess": lang, "scores": {lang: share}} or None when there is too
    little text to judge. Deliberately dumb and dependency-free: on subtitle
    dialogue, function-word share separates languages cleanly."""
    tokens = TOKEN_RE.findall(text.lower())
    if len(tokens) < 40:
        return None
    scores = {}
    for lang, words in STOPWORDS.items():
        hits = sum(1 for t in tokens if t in words)
        scores[lang] = round(hits / float(len(tokens)), 4)
    guess = max(scores, key=scores.get)
    return {"guess": guess, "scores": scores}


# ---------------------------------------------------------------------------
# metrics + the gate itself
# ---------------------------------------------------------------------------
def metrics(cues, duration):
    n = len(cues)
    if not n:
        return {"cues": 0, "spoken_s": 0.0, "cues_per_min": 0.0, "mean_dur": 0.0,
                "chars_per_cue": 0.0, "wpm": 0.0, "first_start": 0.0,
                "last_end": 0.0, "max_gap": 0.0, "words": 0, "coverage": 0.0}
    spoken = sum(max(0.0, c["end"] - c["start"]) for c in cues)
    words = sum(len(c["text"].split()) for c in cues)
    first, last = cues[0]["start"], max(c["end"] for c in cues)
    gaps = [cues[i]["start"] - cues[i - 1]["end"] for i in range(1, n)]
    span_min = max((last - first) / 60.0, 1e-6)
    return {
        "cues": n,
        "spoken_s": round(spoken, 1),
        "cues_per_min": round(n / span_min, 1),
        "mean_dur": round(spoken / n, 2),
        "chars_per_cue": round(sum(len(c["text"]) for c in cues) / float(n), 1),
        "wpm": round(words / spoken * 60.0, 0) if spoken > 0 else 0.0,
        "words": words,
        "first_start": round(first, 2),
        "last_end": round(last, 2),
        "max_gap": round(max(gaps), 2) if gaps else 0.0,
        "coverage": round(spoken / duration, 3) if duration > 0 else 0.0,
    }


def _check(name, level, ok, detail):
    return {"name": name, "level": level, "ok": bool(ok), "detail": detail}


def validate(cues, duration, expect="english", dropped=None):
    """Run every structural check. -> {ok, checks, fails, warns, metrics, examples}"""
    checks, examples = [], []
    n = len(cues)
    m = metrics(cues, duration)

    checks.append(_check("has_cues", "fail", n > 0, "%d cue(s) parsed" % n))

    bad_dur = [c for c in cues if c["end"] <= c["start"]]
    non_mono = [cues[i] for i in range(1, n)
                if cues[i]["start"] < cues[i - 1]["start"] - 0.05]
    checks.append(_check("cue_durations", "fail", not bad_dur,
                         "%d cue(s) with end <= start" % len(bad_dur)))
    checks.append(_check("monotonic", "fail", not non_mono,
                         "%d cue(s) out of order" % len(non_mono)))
    overlaps = sum(1 for i in range(1, n)
                   if cues[i]["start"] < cues[i - 1]["end"] - 0.01)
    checks.append(_check("cue_overlap", "warn", n == 0 or overlaps < n * 0.25,
                         "%d of %d cue(s) start before the previous one ends"
                         % (overlaps, n)))
    for c in (bad_dur + non_mono)[:4]:
        examples.append({"start": c["start"], "end": c["end"],
                         "text": c["text"][:70], "why": "timing"})

    if duration > 0:
        beyond = [c for c in cues if c["end"] > duration + 2.0]
        checks.append(_check("in_range", "fail", not beyond,
                             "%d cue(s) past the end (+2s)" % len(beyond)))
        tail = max(0.0, duration - (m["last_end"] or 0.0))
        late_ok = tail <= max(60.0, duration * 0.10)
        checks.append(_check("covers_end", "warn", late_ok,
                             "transcript ends %.0fs before the video does" % tail))
        if not late_ok:
            examples.append({"at": round(m["last_end"], 2),
                             "why": "transcript stops early", "text": ""})
        for c in beyond[:3]:
            examples.append({"start": c["start"], "end": c["end"],
                             "text": c["text"][:70], "why": "past end of video"})

    if n:
        cpm = m["cues_per_min"]
        # Hard band is wide on purpose: overlapping sign layers and song
        # translations are real; what is not real is 0 cues/min or machine spam.
        checks.append(_check("cue_density", "fail", 0.4 <= cpm <= 250.0,
                             "%.1f cues/min" % cpm))
        checks.append(_check("cue_density_typical", "warn", 1.0 <= cpm <= 80.0,
                             "%.1f cues/min (a film is usually 8-25)" % cpm))
        checks.append(_check("cue_length", "warn",
                             0.3 <= m["mean_dur"] <= 12.0,
                             "%.2fs mean cue length" % m["mean_dur"]))
        checks.append(_check("text_volume", "warn",
                             2.0 <= m["chars_per_cue"] <= 220.0,
                             "%.0f chars per cue" % m["chars_per_cue"]))
        checks.append(_check("speech_rate", "warn",
                             60.0 <= m["wpm"] <= 300.0,
                             "%.0f words/min while speaking" % m["wpm"]))

    drawings = sum(1 for c in cues if is_drawing(c))
    checks.append(_check("no_drawing_commands", "fail", drawings == 0,
                         "%d cue(s) are vector-drawing commands, not words"
                         % drawings))


    letters = [ch for c in cues for ch in c["text"] if ch.isalpha()]
    if letters:
        latin = sum(1 for ch in letters if ch.isascii())
        ratio = latin / float(len(letters))
        need = 0.85 if expect == "english" else 0.30
        level = "fail" if ratio < need * 0.6 else "warn"
        checks.append(_check("script_latin", level, ratio >= need,
                             "%.1f%% ASCII letters (need %.0f%% for %s)"
                             % (ratio * 100, need * 100, expect)))
        if ratio < need:
            ex = next((c for c in cues if any(ord(ch) > 127 for ch in c["text"])),
                      cues[0])
            examples.append({"start": ex["start"], "text": ex["text"][:70],
                             "why": "not English"})
    else:
        checks.append(_check("script_latin", "fail", False, "no letters at all"))

    joined = "\n".join(c["text"] for c in cues)
    if expect == "english":
        lang = detect_language(joined)
        if lang:
            scores = lang["scores"]
            other = scores.get(lang["guess"], 0.0)
            eng = scores.get("english", 0.0)
            # only object when the other language clearly beats English
            foreign = lang["guess"] != "english" and other > eng * 1.5 and other >= 0.06
            checks.append(_check(
                "language", "fail", not foreign,
                "reads as %s (%.1f%% function words; english %.1f%%)"
                % (lang["guess"], other * 100, eng * 100)))
            if foreign:
                ex = cues[0] if cues else {"start": 0.0, "text": ""}
                examples.append({"start": ex["start"], "text": ex["text"][:70],
                                 "why": "looks %s, not english" % lang["guess"]})

    moji = MOJIBAKE_RE.findall(joined)
    checks.append(_check("no_mojibake", "fail", len(moji) <= max(2, n // 200),
                         "%d mojibake marker(s)" % len(moji)))

    if n:
        styled = sum(styling_ratio(c.get("raw", "")) for c in cues) / float(n)
        checks.append(_check("styling", "warn", styled <= 0.35,
                             "%.0f%% of raw characters are markup" % (styled * 100)))

    seen, repeats = {}, 0
    for c in cues:
        key = c["text"].lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 6:
            repeats += 1
    checks.append(_check("no_repetition_spam", "warn", n == 0 or repeats < max(2, n // 100),
                         "%d line(s) repeated 6+ times" % repeats))

    if dropped:
        style_counts = dropped.get("styles") or {}
        if dropped.get("drawings") or style_counts:
            checks.append(_check(
                "source_cleanliness", "warn", False,
                "removed %d drawing cue(s) and %d cue(s) in non-dialogue styles (%s)"
                % (dropped.get("drawings", 0), sum(style_counts.values()),
                   ", ".join(sorted(style_counts)[:4]) or "-")))

    fails = [c for c in checks if not c["ok"] and c["level"] == "fail"]
    warns = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    return {"ok": not fails, "checks": checks, "fails": fails, "warns": warns,
            "metrics": m, "examples": examples[:8]}


# ---------------------------------------------------------------------------
# source discovery: the ladder
# ---------------------------------------------------------------------------
def sidecars(video):
    """Subtitle files sitting next to the video or in a sibling subs/ folder --
    same naming rule recap.py already uses (Episode03.srt for Episode03.mkv)."""
    folder = os.path.dirname(os.path.abspath(video))
    stem = os.path.splitext(os.path.basename(video))[0]
    found = []
    for directory in (folder, os.path.join(folder, "subs")):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            low = name.lower()
            if not low.endswith(SRT_EXTS):
                continue
            if low.startswith(stem.lower()):
                found.append(os.path.join(directory, name))
    return found


def candidates_for(video, info, subs_arg, extract_dir, guard):
    """Ordered candidate list, highest trust first."""
    out = []
    if subs_arg:
        out.append({"rank": 1, "origin": "user", "path": os.path.abspath(subs_arg),
                    "language": "given", "codec": os.path.splitext(subs_arg)[1].lstrip(".")})
    for path in sidecars(video):
        out.append({"rank": 2, "origin": "sidecar", "path": path,
                    "language": "unknown", "codec": os.path.splitext(path)[1].lstrip(".")})
    for saved in probe.extract_text_subs(video, info, extract_dir, guard):
        out.append({"rank": 3, "origin": "embedded", "path": saved["path"],
                    "language": saved["language"], "codec": saved["codec"]})
    return out


def quality_of(row):
    """How much to trust one passing rung. A declared 'eng' tag is a nudge, not
    a trump card: a clean untagged track beats a sign-heavy one that claims English."""
    checks = row.get("checks") or {}
    passed = sum(1 for v in checks.values() if v == "ok") / float(max(1, len(checks)))
    score = passed
    if (row.get("language") or "").lower().startswith("en"):
        score += 0.05
    for penalty in ("cue_overlap", "source_cleanliness", "cue_density_typical"):
        if checks.get(penalty) not in (None, "ok"):
            score -= 0.03
    return round(score, 4)


def run_gate(video, info, subs_arg=None, expect="english", extract_dir=None,
             guard=None):
    """Walk the ladder, validate each rung, stop at the first that passes.

    Returns a report dict. `status` is one of:
      verified     -- a source passed the gate; use it
      needs_whisper-- nothing usable; caller must transcribe or ask for a file
      rejected_all -- sources existed but every one failed the gate
    """
    ladder, chosen, rejections, passing = [], None, [], []
    picture_subs = [s for s in info.get("subs", []) if s.get("picture")]

    if subs_arg and not os.path.isfile(subs_arg):
        rejections.append({"origin": "user", "path": subs_arg,
                           "reason": "file not found"})

    for cand in candidates_for(video, info, subs_arg, extract_dir, guard):
        row = dict(cand)
        try:
            loaded = load_cues(cand["path"])
        except Exception as exc:                       # unreadable or not a subclass
            row["ok"] = False
            row["error"] = str(exc)[:200]
            ladder.append(row)
            rejections.append({"origin": cand["origin"], "path": cand["path"],
                               "reason": "unreadable: %s" % str(exc)[:120]})
            continue
        verdict = validate(loaded["cues"], info.get("duration", 0.0), expect,
                           loaded.get("dropped"))
        row.update({"ok": verdict["ok"], "format": loaded["format"],
                    "encoding": loaded["encoding"],
                    "encodings": loaded["encodings"],
                    "native": cand.get("native", False),
                    "dropped": loaded.get("dropped"),
                    "language_detail": next(
                        (c["detail"] for c in verdict["checks"]
                         if c["name"] == "language"), None),
                    "bad_lines": len(loaded["bad_lines"]),
                    "metrics": verdict["metrics"],
                    "checks": {c["name"]: ("ok" if c["ok"] else c["level"])
                               for c in verdict["checks"]},
                    "fails": [f["name"] + ": " + f["detail"] for f in verdict["fails"]],
                    "warns": [w["name"] + ": " + w["detail"] for w in verdict["warns"]],
                    "examples": verdict["examples"]})
        row["quality"] = quality_of(row)
        ladder.append(row)
        if verdict["ok"]:
            passing.append((row, loaded["bytes"]))
        else:
            rejections.append({"origin": cand["origin"], "path": cand["path"],
                               "reason": "; ".join(row["fails"]) or "passed with warnings"})

    if passing:
        # The user's own file outranks everything. Between equally-trusted
        # sources, the cleaner track wins rather than whichever came first.
        mine = [pair for pair in passing if pair[0]["origin"] == "user"]
        best = max(mine or passing, key=lambda pair: pair[0]["quality"])
        chosen = dict(best[0])
        chosen["bytes"] = best[1]


    if chosen:
        status = "verified"
        note = ("using the %s subtitle file (%s, %s)" %
                (chosen["origin"], chosen["format"], chosen["encoding"]))
    elif ladder:
        # Something was tried and rejected. Saying "no subtitles found" here would
        # hide the reason and invite the user to just re-run it.
        first = (rejections[0]["reason"] if rejections else "unknown reason")[:130]
        status = "rejected_all"
        note = ("checked %d subtitle source(s) and none passed the gate; "
                "first failure -- %s" % (len(ladder), first))
    elif picture_subs:
        status = "needs_whisper"
        note = ("only picture-based subtitles (%s) are present -- no text exists "
                "without OCR, so transcription is required"
                % ", ".join(sorted({s["codec"] for s in picture_subs})))
    else:
        status = "needs_whisper"
        note = "no subtitle tracks embedded and no subtitle file alongside the video"


    return {
        "status": status,
        "note": note,
        "chosen": chosen,
        "ladder": ladder,
        "rejections": rejections,
        "picture_subs": [{"codec": s["codec"], "language": s["language"]}
                         for s in picture_subs],
    }




