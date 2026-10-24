"""Transcript -> candidate moments.

The gate in subs.py guarantees the cue list can be trusted. This step turns it
into story beats, ranks them, and writes a shortlist plus a digest the agent
reads. Pure text arithmetic: deterministic, no model, no network, no install.

Every candidate comes out as `status: unverified` with an empty `expected`
field. That is deliberate: the transcript says what is *said*, never what is
*seen*. The next step fills `expected` with what the picture should show and
then earns the right to call the moment verified by looking at frames.
"""
import re

from . import guard

BEAT_GAP = 1.25        # seconds of silence that ends a beat
BEAT_MAX_CUES = 8      # a beat is at most this many cues
BEAT_MAX_CHARS = 380   # ...and at most this much text
BEAT_MIN_CHARS = 40    # shorter than this gets folded into its neighbour

SDH_RE = re.compile(r"[\[\(][^\]\)]{1,60}[\]\)]")
WORD_RE = re.compile(r"[a-z']+")

# What tends to matter in a recap. Deliberately small and loud -- a long list
# is just noise. Weight 3 = the beat almost certainly contains the turn.
IMPACT = {
    3: ("dies", "died", "dead", "death", "kill", "killed", "kills", "murder",
        "murderer", "blood", "gun", "shoot", "shoots", "shot", "stabbed",
        "explosion", "explodes", "betray", "betrays", "betrayal", "revenge",
        "escapes", "escaped", "escape", "trapped", "secret", "reveals",
        "revealed", "twist", "discovers", "discovered", "realizes", "realized",
        "confesses", "confession", "corpse", "poison", "kidnapped", "hostage",
        "blackmail", "lies", "liar", "threatens"),
    2: ("fight", "fights", "attack", "attacked", "screams", "yells", "shouts",
        "chase", "chased", "runs", "hiding", "hides", "plan", "plans", "deal",
        "truth", "trust", "promise", "warns", "warning", "danger", "dangerous",
        "accident", "hospital", "police", "arrest", "arrested", "court",
        "trial", "verdict", "guilty", "innocent", "witness", "evidence",
        "debt", "pregnant", "wedding", "funeral", "missing", "alone", "sorry",
        "please", "stop", "help", "never"),
}
IMPACT_W = {word: weight for weight, words in IMPACT.items() for word in words}


def has_sdh(text):
    """Subtitle-for-the-deaf-and-hard-of-hearing markers: [door slams] etc."""
    return bool(SDH_RE.search(text))


def strip_sdh(text):
    return SDH_RE.sub(" ", text)


def build_beats(cues):
    """Group cues into beats: contiguous speech, split on silence or length."""
    raw, cur = [], []
    for cue in cues:
        if cur:
            gap = cue["start"] - cur[-1]["end"]
            chars = sum(len(c["text"]) for c in cur) + len(cue["text"])
            if gap > BEAT_GAP or len(cur) >= BEAT_MAX_CUES or chars > BEAT_MAX_CHARS:
                raw.append(cur)
                cur = []
        cur.append(cue)
    if cur:
        raw.append(cur)

    out = []
    for beat in raw:
        chars = sum(len(c["text"]) for c in beat)
        merged = False
        if out and chars < BEAT_MIN_CHARS:
            prev = out[-1]
            if beat[0]["start"] - prev[-1]["end"] < 3.0:
                prev.extend(beat)
                merged = True
        if not merged:
            out.append(list(beat))
    return out


def score_beat(text):
    """-> (score, hits, reason). Density-weighted so long quiet beats lose."""
    spoken = strip_sdh(text)
    words = WORD_RE.findall(spoken.lower())
    if not words:
        return 0.0, [], "no words"

    counted, hits = 0, []
    for word in words:
        weight = IMPACT_W.get(word)
        if weight:
            counted += weight
            if word not in hits:
                hits.append(word)

    per_25 = counted / max(1.0, len(words) / 25.0)      # ~25 words is 10s
    length_fit = 1.0 if 15 <= len(words) <= 120 else (
        max(0.35, len(words) / 15.0) if len(words) < 15
        else max(0.45, 120.0 / len(words)))
    bonus = min(spoken.count("?"), 2) * 0.5 + min(spoken.count("!"), 3) * 0.25
    score = round(per_25 * length_fit + bonus, 2)
    if hits:
        reason = "dramatic language: " + ", ".join(hits[:5])
    elif bonus:
        reason = "question / exclamation"
    else:
        reason = "connective dialogue"
    return score, hits, reason


def select(cands, top=12, acts=5, min_gap=20.0, duration=0.0):
    """Pick a shortlist that is both strong and spread across the runtime.

    Pure top-N scoring gives you four deaths from the last five minutes; act
    coverage first, then scored fill with a minimum spacing, keeps the spine of
    the story intact.
    """
    if not cands:
        return []
    ranked = sorted(cands, key=lambda c: (-c["score"], c["t_start"]))
    picked = []

    if duration > 0 and acts > 0:
        for a in range(acts):
            lo, hi = duration * a / float(acts), duration * (a + 1) / float(acts)
            best = next((c for c in ranked
                         if lo <= c["t_start"] < hi and c not in picked), None)
            if best is not None and best["score"] >= 0.75 and len(picked) < top:
                picked.append(best)

    for cand in ranked:
        if len(picked) >= top:
            break
        if cand in picked:
            continue
        if any(abs(cand["t_start"] - p["t_start"]) < min_gap for p in picked):
            continue
        picked.append(cand)

    picked.sort(key=lambda c: c["t_start"])
    return picked


def fmt_mmss(sec):
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def build_doc(info, gate, transcript, cues, top=12, acts=5, min_gap=20.0):
    """Assemble moments.json: what was analyzed, what it found, what to check."""
    beats = [make_beat(b, i) for i, b in enumerate(build_beats(cues))]
    cands = [b for b in beats if b["t_end"] > b["t_start"]]
    picked = select(cands, top, acts, min_gap, info.get("duration", 0.0))
    for rank, cand in enumerate(picked, 1):
        cand["rank"] = rank

    metrics = (gate.get("chosen") or {}).get("metrics", {})
    return {
        "schema": "cutwright/moments/1",
        "video": {
            "path": info["path"], "name": info["name"],
            "duration": info.get("duration", 0.0),
            "size": info.get("size", 0),
            "width": info.get("width", 0), "height": info.get("height", 0),
            "fps": info.get("fps", 0.0),
            "vertical": info.get("height", 0) > info.get("width", 0),
            "sig": guard.file_sig(info["path"]) if info.get("exists") else None,
        },
        "transcript": dict(transcript, metrics=metrics),
        "gate": {"status": gate["status"], "note": gate["note"],
                 "rejections": gate["rejections"],
                 "warns": (gate.get("chosen") or {}).get("warns", [])},
        "beats": len(beats),
        "candidates": picked,
        "all_beats_file": None,
        "notes": [
            "candidates are unverified: the transcript says what is said, not what is seen",
            "each candidate carries frames[] -- three timestamps to sample before trusting it",
            "window{} is deliberately wider than t_start/t_end; the voice sets the final out",
        ],
    }


def digest(doc, width=96):
    """The agent-readable summary. Mirrors recap.py's ALL_EPISODES_for_claude.txt:
    one text file a model can read without parsing JSON."""
    v = doc["video"]
    t = doc["transcript"]
    m = t.get("metrics") or {}
    lines = []
    lines.append("CUTWRIGHT MOMENTS / %s" % v["name"])
    lines.append("=" * min(width, 60))
    lines.append("duration   %s  (%dx%d, %.3g fps%s)"
                 % (fmt_mmss(v["duration"]), v["width"], v["height"], v["fps"],
                    ", vertical" if v.get("vertical") else ""))
    lines.append("transcript %s from %s (%s), %d cues"
                 % (t.get("format", "?"), t.get("origin", "?"),
                    t.get("encoding", "?"), t.get("cues", 0)))
    if m:
        lines.append("speech     %.0f words, %.0f wpm, %.1f cues/min, mean cue %.2fs"
                     % (m.get("words", 0), m.get("wpm", 0),
                        m.get("cues_per_min", 0), m.get("mean_dur", 0)))
    lines.append("gate       %s -- %s" % (doc["gate"]["status"], doc["gate"]["note"]))
    if doc["gate"]["warns"]:
        lines.append("warnings   " + " | ".join(doc["gate"]["warns"]))
    lines.append("%d beats -> %d candidates" % (doc["beats"], len(doc["candidates"])))
    lines.append("")

    for c in doc["candidates"]:
        lines.append("%2d. [%s - %s]  %4.1fs  score %.2f%s"
                     % (c["rank"], fmt_mmss(c["t_start"]), fmt_mmss(c["t_end"]),
                        c["duration"], c["score"], "  [SDH]" if c["sdh"] else ""))
        lines.append("    %s" % c["reason"])
        quote = " ".join(c["quote"].split())
        if len(quote) > 150:
            quote = quote[:147] + "..."
        lines.append("    \"%s\"" % quote)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def digest_table(doc, width=58):
    """Compact one-line-per-candidate version for the console."""
    rows = []
    for c in doc["candidates"]:
        quote = " ".join(c["quote"].split())
        if len(quote) > width:
            quote = quote[:width - 3] + "..."
        rows.append({
            "rank": c["rank"],
            "at": fmt_mmss(c["t_start"]),
            "len": "%.1fs" % c["duration"],
            "score": c["score"],
            "hits": ",".join(c["hits"][:3]) or "-",
            "quote": quote,
        })
    return rows


def make_beat(cue_list, index):
    """One beat -> a candidate record with its verification window precomputed."""
    text = " ".join(c["text"].replace("\n", " ") for c in cue_list).strip()
    score, hits, reason = score_beat(text)
    start = cue_list[0]["start"]
    end = max(c["end"] for c in cue_list)
    # Pick in/out as a window with slack: the voice sets the final out later,
    # and extending src_end into the next shot is cheaper than re-cutting.
    return {
        "id": "b%03d" % (index + 1),
        "t_start": round(start, 3),
        "t_end": round(end, 3),
        "duration": round(end - start, 3),
        "window": {"start": round(max(0.0, start - 0.35), 3),
                   "end": round(end + 0.60, 3)},
        "frames": [round(start + 0.05, 3),
                   round((start + end) / 2.0, 3),
                   round(max(start, end - 0.05), 3)],
        "quote": text,
        "words": len(text.split()),
        "sdh": has_sdh(text),
        "hits": hits,
        "score": score,
        "reason": reason,
        "status": "unverified",
        "expected": "",
    }
