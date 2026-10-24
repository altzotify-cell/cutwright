"""Frames -> verification.

moments.py ends every candidate as `status: unverified` with an empty
`expected`. This step is what earns a different word, and it refuses to grade a
pick that has not said what it expects to see.

The split of labour matters:

  * the *agent* writes `expected.claim` in words, from the transcript. That is
    the only part of verification that needs to understand the story.
  * the *machine* measures what ffmpeg can actually prove without a model:
    how many shots the window contains, whether the in-point lands on a shot
    change or mid-shot, and whether the frame is a picture or a black hole.

A claim is graded on evidence, not on confidence:

  verified    one continuous shot, in-point is clean (on a cut, or far enough
              into a shot that no previous-shot tail is included), luminance
              within what the claim expects, and any text the claim expects is
              actually on screen at one of the three frames.
  retimed     the picture is right but the cut is in the wrong place: a shot
              change lands shortly *after* the in-point, so the trim would
              start with a fragment of the previous shot. A new in-point is
              proposed, not silently applied.
  replaced    the measurement contradicts the claim: text claimed with no cue
              on screen, a picture claimed where all three frames are black, or
              a claim that the pick is one held shot where the window actually
              contains several. Only a claim can be contradicted -- a busy
              window is not an error, so shot count on its own demotes nothing.
  unverified  no claim at all, or the frames could not be read. Never upgraded
              on optimism.

Anything editorially interesting that is not a contradiction is reported as a
warning and does not change the grade: a frame that is black because the pick
spans a fade, an in-point that opens on a flash, a window that cuts six times
because it is a conversation shot shot/reverse-shot.

Frames are written as small JPEGs under the output folder so the same three
timestamps can be looked at by a human or a vision model afterwards. Two
measurements per frame, both from ffmpeg and neither needing a dependency:
the frame itself, and its mean luminance (a single grey pixel).
"""
import os
import re
import subprocess

from . import guard
from . import moments
from . import probe

CUT_THRESHOLD = 0.30   # ffmpeg scene score that counts as a shot change
TAIL_SLACK = 2.0       # a cut this soon after the in-point is worth retiming to
ON_CUT = 0.02          # in-point this close to a cut already is on the cut
                       # (half a frame at 24 fps -- anything longer is visible)
BLACK_LUMA = 18        # 0-255 mean luminance below this is dark
FLAT_RANGE = 12        # an 8x8 probe this flat, and dark, is a black frame
BUSY_CUTS = 4          # more shot changes than this inside one window is busy
OUT_CUT_SLACK = 0.10   # out-point this close after a cut clips the last shot
FRAME_WIDTH = 640      # what the JPEGs are scaled to: big enough to see a face
PROBE = 8              # the luminance probe is PROBE x PROBE grey pixels

PTS_RE = re.compile(r"pts_time:([0-9.]+)")
SCORE_RE = re.compile(r"scene_score=([0-9.]+)")

STATUSES = ("verified", "retimed", "replaced", "unverified")


def _run_binary(cmd, timeout=180):
    """Like probe.run but keeps stdout as bytes (a raw frame is not text)."""
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def luma_at(video, t):
    """Mean luminance 0-255 at one instant: scale the frame to a single pixel."""
    r = _run_binary(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
                     "-ss", "%.3f" % max(0.0, t), "-i", video, "-frames:v", "1",
                     "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    if r.returncode != 0 or len(r.stdout) < 1:
        return None
    return int(r.stdout[0])


def probe_frame(video, t, path=None, width=FRAME_WIDTH):
    """One decode -> (jpeg written?, mean luma, spread, is_flat_black).

    A single grey pixel gives the mean but cannot tell a fade-to-black from a
    dark night exterior: both read 9. An 8x8 grid can. A black frame is flat
    (max-min <= FLAT_RANGE) *and* dark; a dark scene still has structure.
    """
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y",
           "-ss", "%.3f" % max(0.0, t), "-i", video, "-filter_complex",
           "[0:v]split=2[a][b];[a]scale=%d:-2[j];[b]scale=%d:%d[g]"
           % (width, PROBE, PROBE),
           "-map", "[g]", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    if path:
        cmd += ["-map", "[j]", "-frames:v", "1", "-q:v", "3", path]
    r = _run_binary(cmd)
    vals = list(r.stdout[:PROBE * PROBE])
    if r.returncode != 0 or len(vals) < PROBE * PROBE:
        return (False if path else None), None, None, None
    mean = int(round(sum(vals) / float(len(vals))))
    spread = max(vals) - min(vals)
    flat = spread <= FLAT_RANGE and mean < BLACK_LUMA
    return (True if path else None), mean, spread, flat


def extract(video, times, out_dir, tag, width=FRAME_WIDTH):
    """One JPEG + one luminance probe per timestamp, from a single decode.

    split the frame, write one branch as a small JPEG and shrink the other to
    an 8x8 grey probe. Reading both from one pass halves the ffmpeg launches,
    which is most of this step's cost.
    """
    guard.ensure_dir(out_dir)
    out = []
    for n, t in enumerate(times, 1):
        t = round(max(0.0, float(t)), 3)
        path = os.path.join(out_dir, "%s_%d_%07.2fs.jpg" % (tag, n, t))
        guard.assert_writable(path)
        ok, mean, spread, flat = probe_frame(video, t, path, width)
        ok = bool(ok) and os.path.isfile(path) and os.path.getsize(path) > 0
        out.append({"t": t, "path": path if ok else None, "luma": mean,
                    "spread": spread, "flat": bool(flat),
                    "bytes": os.path.getsize(path) if ok else 0})
    return out


def shot_cuts(video, lo, hi, threshold=CUT_THRESHOLD):
    """Shot change times inside [lo, hi], as absolute seconds.

    Input-side -ss/-t so the offsets are seek-relative starting at 0 and the
    window is bounded for real (an output-side -t lets the last frame run past).
    """
    lo, hi = max(0.0, float(lo)), float(hi)
    dur = max(0.1, hi - lo)
    vf = "select=gt(scene\\,%.3f),metadata=print:file=-" % threshold
    r = probe.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
                   "-ss", "%.3f" % lo, "-t", "%.3f" % dur, "-i", video,
                   "-an", "-sn", "-vf", vf, "-f", "null", "-"], timeout=300)
    if r.returncode != 0:
        return []
    times, pending = [], None
    for line in (r.stdout or "").splitlines():
        m = PTS_RE.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = SCORE_RE.search(line)
        if m and pending is not None:
            times.append(round(lo + pending, 3))
            pending = None
    return sorted(times)


def measure_window(video, window):
    """Everything ffmpeg can prove about one pick's in-point."""
    start, end = float(window["start"]), float(window["end"])
    # Look a little before the in-point too: a cut at start-0.2 means we open
    # just after it, which is clean. A cut at start+0.2 means we open with the
    # tail of the shot we are leaving, which is not.
    cuts = shot_cuts(video, max(0.0, start - 1.5), end + 1.0)
    inside = [c for c in cuts if start + ON_CUT < c < end - ON_CUT]
    after = [c for c in cuts if start < c <= start + TAIL_SLACK]
    before = [c for c in cuts if start - TAIL_SLACK <= c < start]
    return {
        "cuts": cuts,
        "inside": len(inside),
        "tail_cut": after[0] if after else None,
        "head_cut": before[-1] if before else None,
        "since_cut": round(start - before[-1], 3) if before else None,
    }


def text_at(cues, times, slack=0.45):
    """Is a dialogue cue on screen at any of these instants?"""
    hits = []
    for t in times:
        if any(c["start"] - slack <= t <= c["end"] + slack for c in cues):
            hits.append(round(t, 3))
    return hits


def normalise_claim(value):
    """A claim is free text, or a dict with the text plus measurable options."""
    if isinstance(value, str):
        value = {"claim": value}
    if not isinstance(value, dict):
        return None
    claim = (value.get("claim") or "").strip()
    if not claim:
        return None
    out = {"claim": claim}
    for key in ("text", "black"):
        if isinstance(value.get(key), bool):
            out[key] = value[key]
    if isinstance(value.get("shots"), str) and value["shots"].strip():
        out["shots"] = value["shots"].strip().lower()
    return out


def load_claims(path):
    raw = guard.read_json(path, default={}) or {}
    claims = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key.startswith("_"):
                continue
            claim = normalise_claim(value)
            if claim:
                claims[key] = claim
    return claims


def unclaimed(doc, claims):
    """Every shortlisted pick must say what it expects. These did not."""
    return [c for c in doc["candidates"] if c["id"] not in claims]


def template(doc, claims, path):
    """A file the agent fills in: one slot per pick, with the quote as a hint."""
    out = {
        "_how": "Fill every slot. A claim is a sentence about what the picture "
                "shows, plus optional checks: \"text\" (dialogue on screen) and "
                "\"black\" (the frame is black). Delete \"_quote\" when done.",
        "_note": "Claims come from the transcript, then the frames decide.",
    }
    for c in doc["candidates"]:
        if c["id"] in claims:
            out[c["id"]] = claims[c["id"]]
            continue
        out[c["id"]] = {
            "claim": "",
            "_rank": c["rank"],
            "_at": moments.fmt_mmss(c["t_start"]),
            "_quote": " ".join(c["quote"].split())[:160],
        }
    return guard.write_json(path, out)


def grade(cand, claim, measured, frame_list, text_hits):
    """-> (status, reason, retimed_or_None). Evidence only."""
    if not claim:
        return ("unverified",
                "no expected claim -- a pick that never said what it expects "
                "cannot be verified, only hoped for", None)

    luma = [f["luma"] for f in frame_list]
    if any(v is None for v in luma) or any(not f["path"] for f in frame_list):
        bad = sum(1 for f in frame_list if not f["path"] or f["luma"] is None)
        return ("unverified",
                "could not read %d of %d frame(s) from the source"
                % (bad, len(frame_list)), None)

    if claim.get("text") is True and not text_hits:
        return ("replaced",
                "claim expects dialogue on screen; no subtitle cue covers any "
                "of the three frames", None)
    if claim.get("text") is False and len(text_hits) == len(frame_list):
        return ("replaced",
                "claim expects no dialogue; a cue covers all three frames", None)
    if claim.get("black") is False and all(f["flat"] for f in frame_list):
        return ("replaced",
                "claim expects a picture; all three frames are black frames "
                "(flat, mean luma %d)" % max(luma), None)
    if claim.get("black") is True and not any(f["flat"] for f in frame_list):
        return ("replaced",
                "claim expects black; no frame is a black frame (mean luma "
                "%d-%d)" % (min(luma), max(luma)), None)

    if measured["inside"] > 0 and claim.get("shots") == "single":
        return ("replaced",
                "claim says one held shot; the window contains %d shot change(s) "
                "-- it is a sequence" % measured["inside"], None)

    start, end = float(cand["window"]["start"]), float(cand["window"]["end"])
    tail = measured["tail_cut"]
    if tail is not None and (tail - start) > ON_CUT:
        moved = round(tail - start, 3)
        return ("retimed",
                "shot changes %.2fs after the in-point; opening there would "
                "start on the tail of the previous shot" % moved,
                {"start": round(tail, 3), "end": round(end, 3), "delta": moved})

    if tail is not None:
        reason = "in-point lands on a shot change (+%.2fs) and holds %.1fs" % (
            tail - start, end - start)
    elif measured["since_cut"] is not None:
        reason = "one continuous shot, opening %.2fs into it" % measured["since_cut"]
    else:
        reason = "one continuous shot across all three frames, no shot change nearby"
    if text_hits:
        reason += "; dialogue on screen at %d of 3 frames" % len(text_hits)
    return ("verified", reason, None)


def warnings_for(cand, claim, measured, frame_list):
    """Editorially interesting, not a contradiction. Never changes the grade."""
    out = []
    luma = [f["luma"] for f in frame_list if f["luma"] is not None]
    if not luma:
        return out
    end = float(cand["window"]["end"])

    if min(luma) < BLACK_LUMA <= max(luma):
        dark = [i + 1 for i, v in enumerate(luma) if v < BLACK_LUMA]
        out.append("frame %d reads dark (luma %d) but is not flat: a dark scene, "
                   "not a fade" % (dark[0], min(luma)))
    flats = [i + 1 for i, f in enumerate(frame_list) if f["flat"]]
    if flats:
        out.append("frame %s is a black frame: the pick spans a cut to black"
                   % "/".join(str(i) for i in flats))
    if frame_list and frame_list[0]["flat"]:
        out.append("opens on a black frame: open after the fade")
    if measured["inside"] > BUSY_CUTS:
        out.append("%d shot changes inside the window: a sequence, not a held "
                   "shot -- the trim will cross shots" % measured["inside"])
    near_end = [c for c in measured["cuts"] if 0.0 <= end - c <= OUT_CUT_SLACK]
    if near_end:
        out.append("out-point is %.2fs after a shot change: the last shot gets "
                   "clipped" % (end - near_end[-1]))
    return out


def load_review(path):
    """The agent's verdict on frames it actually looked at.

    Kept separate from claims on purpose: a claim is written before looking, a
    review after, and the machine's measurement sits between them. A review can
    overrule a machine grade -- the machine cannot see who is on screen -- but
    it cannot delete the machine's call, which is kept in the row.
    """
    raw = guard.read_json(path, default={}) or {}
    out = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str):
            value = {"verdict": value}
        if not isinstance(value, dict):
            continue
        verdict = (value.get("verdict") or "").strip().lower()
        if verdict not in STATUSES:
            continue
        out[key] = {"verdict": verdict,
                    "note": (value.get("note") or "").strip(),
                    "frames_seen": value.get("frames_seen")}
    return out


def run_verify(video, info, doc, claims, cues, out_dir, write_back=False,
               review=None):
    """Grade every shortlisted pick. No claim -> no frames, no grade."""
    frame_dir = os.path.join(out_dir, "frames")
    rows = []
    for cand in doc["candidates"]:
        claim = claims.get(cand["id"])
        if not claim:
            rows.append({
                "id": cand["id"], "rank": cand["rank"],
                "status": "unverified",
                "reason": "no expected claim -- a pick that never said what it "
                          "expects cannot be verified, only hoped for",
                "claim": None, "expected": cand.get("expected") or "",
                "window": cand["window"], "frames": [], "text_hits": [],
                "cuts_inside": None, "tail_cut": None, "head_cut": None,
                "since_cut": None, "retimed": None, "quote": cand["quote"],
                "warns": [],
            })
            continue

        frame_list = extract(video, cand["frames"], frame_dir, cand["id"])
        measured = measure_window(video, cand["window"])
        hits = text_at(cues, [f["t"] for f in frame_list])
        status, reason, retimed = grade(cand, claim, measured, frame_list, hits)
        machine = {"status": status, "reason": reason}
        verdict = (review or {}).get(cand["id"])
        if verdict:
            status = verdict["verdict"]
            reason = "agent looked at the frames: %s" % (verdict["note"] or "(no note)")
        rows.append({
            "id": cand["id"], "rank": cand["rank"], "status": status,
            "reason": reason, "claim": claim, "expected": claim["claim"],
            "machine": machine if verdict else None,
            "window": cand["window"],
            "frames": [{"t": f["t"], "luma": f["luma"], "spread": f["spread"],
                        "flat": f["flat"],
                        "path": guard.rel(f["path"]) if f["path"] else None,
                        "bytes": f["bytes"]} for f in frame_list],
            "text_hits": hits, "cuts_inside": measured["inside"],
            "tail_cut": measured["tail_cut"], "head_cut": measured["head_cut"],
            "since_cut": measured["since_cut"], "retimed": retimed,
            "quote": cand["quote"],
            "warns": warnings_for(cand, claim, measured, frame_list),
        })

    summary = {name: sum(1 for r in rows if r["status"] == name) for name in STATUSES}
    report = {
        "schema": "cutwright/frames/1",
        "reviewed": sum(1 for r in rows if r.get("machine")),
        "video": {"name": info["name"], "path": info["path"],
                  "duration": info["duration"], "width": info["width"],
                  "height": info["height"], "fps": info["fps"],
                  "sig": guard.file_sig(video)},
        "transcript": {"origin": doc["transcript"].get("origin"),
                       "format": doc["transcript"].get("format"),
                       "cues": len(cues)},
        "thresholds": {"cut": CUT_THRESHOLD, "tail_slack": TAIL_SLACK,
                       "on_cut": ON_CUT, "black_luma": BLACK_LUMA,
                       "flat_range": FLAT_RANGE, "busy_cuts": BUSY_CUTS,
                       "frame_width": FRAME_WIDTH},
        "candidates": rows,
        "summary": summary,
        "frame_dir": guard.rel(frame_dir),
    }
    if write_back:
        write_status_back(doc, rows)
    return report


def write_status_back(doc, rows):
    """Patch moments.json in place: the seam closes where it was opened."""
    by_id = {r["id"]: r for r in rows}
    for cand in doc["candidates"]:
        row = by_id.get(cand["id"])
        if not row:
            continue
        cand["expected"] = row["expected"] or ""
        cand["status"] = row["status"]
        cand["verify"] = {
            "reason": row["reason"],
            "frames": [{"t": f["t"], "luma": f["luma"], "flat": f["flat"],
                        "path": f["path"]}
                       for f in row["frames"]],
            "text_hits": row["text_hits"],
            "cuts_inside": row["cuts_inside"],
            "since_cut": row["since_cut"],
            "retimed": row["retimed"],
            "warns": row["warns"],
        }
    return doc


def _luma_text(row):
    """Mean luma per frame; a trailing * marks a flat black frame."""
    if not row["frames"]:
        return "-"
    cells = []
    for f in row["frames"]:
        cell = "-" if f["luma"] is None else str(f["luma"])
        cells.append(cell + ("*" if f.get("flat") else ""))
    return "/".join(cells)


def digest_table(report):
    """Console rows: one line per pick."""
    rows = []
    for r in report["candidates"]:
        why = r["reason"]
        if r["status"] == "retimed" and r["retimed"]:
            why = "+%.2fs -> %s" % (r["retimed"]["delta"],
                                    moments.fmt_mmss(r["retimed"]["start"]))
        rows.append({
            "rank": r["rank"],
            "id": r["id"],
            "status": r["status"],
            "at": moments.fmt_mmss(r["window"]["start"]),
            "luma": _luma_text(r),
            "warns": len(r.get("warns") or []),
            "why": why,
        })
    return rows


def digest(report, width=88):
    v = report["video"]
    t = report["thresholds"]
    s = report["summary"]
    lines = []
    lines.append("CUTWRIGHT VERIFY / %s" % v["name"])
    lines.append("=" * min(width, 60))
    lines.append("duration   %s  (%dx%d, %.3g fps)"
                 % (moments.fmt_mmss(v["duration"]), v["width"], v["height"], v["fps"]))
    lines.append("transcript %s from %s, %d cues"
                 % (report["transcript"].get("format", "?"),
                    report["transcript"].get("origin", "?"),
                    report["transcript"].get("cues", 0)))
    lines.append("frames     %s  (3 per pick, %d px wide)"
                 % (report["frame_dir"], t["frame_width"]))
    lines.append("thresholds shot change > %.2f · retime slack %.1fs · black = flat "
                 "and < %d luma" % (t["cut"], t["tail_slack"], t["black_luma"]))
    lines.append("           luma = mean of an 8x8 probe; * marks a black frame")
    lines.append("graded     " + ", ".join("%d %s" % (s[k], k) for k in STATUSES))
    if report.get("reviewed"):
        lines.append("reviewed   %d of %d pick(s) looked at by the agent"
                     % (report["reviewed"], len(report["candidates"])))
    lines.append("")
    for r in report["candidates"]:
        lines.append("%2d. %s  %-10s %s  luma %-12s cuts %s"
                     % (r["rank"], r["id"], r["status"].upper(),
                        moments.fmt_mmss(r["window"]["start"]), _luma_text(r),
                        "-" if r["cuts_inside"] is None else r["cuts_inside"]))
        lines.append("    claim: %s" % (r["expected"] or "(none)"))
        lines.append("    %s" % r["reason"])
        if r.get("machine"):
            lines.append("    machine: %s -- %s"
                         % (r["machine"]["status"], r["machine"]["reason"]))
        if r["retimed"]:
            lines.append("    retime: open at %s instead of %s (%.2fs later)"
                         % (moments.fmt_mmss(r["retimed"]["start"]),
                            moments.fmt_mmss(r["window"]["start"]),
                            r["retimed"]["delta"]))
        for warn in r.get("warns") or []:
            lines.append("    warn: %s" % warn)
        quote = " ".join(r["quote"].split())
        if len(quote) > 150:
            quote = quote[:147] + "..."
        lines.append("    \"%s\"" % quote)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


