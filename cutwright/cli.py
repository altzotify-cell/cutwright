"""Cutwright -- agent-grade control of a Desktop video-editing fork.

Steps:
  doctor   What this machine has, and proof the write guard works
  probe    One source file: streams, duration, subtitle tracks -> stdout
  subs     Subtitle gate: find the best subtitle source and prove it is usable
  moments  Transcript -> ranked candidate moments + agent digest
  verify   Grade picks against frames: verified / retimed / replaced
  transcribe  whisper.cpp fallback: produce a transcript, then gate it
  build    Plan -> Shotcut .mlt, then the four checks on the file itself

Every step is dry by default and writes only inside this folder.
"""
import argparse
import os
import shutil
import sys

from . import guard
from . import frames
from . import mlt
from . import moments
from . import probe
from . import subs
from . import transcribe

VERSION = "0.1.0"


def out_dir_for(video, override=None):
    if override:
        return guard.ensure_dir(os.path.abspath(override))
    stem = os.path.splitext(os.path.basename(video))[0]
    return guard.ensure_dir(os.path.join(guard.OUT, stem))


def print_table(rows, cols):
    """rows = [dict]; cols = [(key, header, width)] -- fixed width, ASCII."""
    if not rows:
        return
    head = "  ".join(str(h).ljust(w) for _k, h, w in cols)
    print("  " + head)
    print("  " + "-" * len(head))
    for row in rows:
        cells = []
        for key, _h, width in cols:
            value = str(row.get(key, ""))
            cells.append(value[:width].ljust(width))
        print("  " + "  ".join(cells))


def rule(char="-", width=74):
    print(char * width)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args):
    rule("=")
    print("CUTWRIGHT %s  doctor" % VERSION)
    rule("=")
    print("root        %s" % guard.ROOT)
    print("python      %s" % sys.version.split()[0])

    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path:
            print("[!] %-9s NOT FOUND on PATH" % tool)
            continue
        r = probe.run([tool, "-version"])
        first = (r.stdout or "").splitlines()[0] if r.stdout else "?"
        print("[+] %-9s %s" % (tool, path))
        print("             %s" % first[:110])

    free = shutil.disk_usage(guard.ROOT).free / (1024.0 ** 3)
    print("disk free   %.1f GB on the fork's drive" % free)

    print("")
    print("originals (read-only, never written to):")
    for original in guard.ORIGINALS:
        print("  %s  %s" % ("present" if os.path.isdir(original) else "MISSING",
                            original))
    print("vendored   %d file(s), %.2f MB" %
          (_count_files(guard.VENDOR),
           _tree_size(guard.VENDOR) / (1024.0 * 1024.0)))

    print("")
    print("write guard self-test:")
    tests = []
    try:
        guard.assert_writable(os.path.join(guard.OUT, "_probe.tmp"))
        tests.append(("inside the fork", True))
    except guard.GuardError:
        tests.append(("inside the fork", False))
    for original in guard.ORIGINALS:
        try:
            guard.assert_writable(os.path.join(original, "_probe.tmp"))
            tests.append(("refuses %s" % os.path.basename(original), False))
        except guard.GuardError:
            tests.append(("refuses %s" % os.path.basename(original), True))
    try:
        guard.assert_writable(r"C:\Windows\_probe.tmp")
        tests.append(("refuses outside the fork", False))
    except guard.GuardError:
        tests.append(("refuses outside the fork", True))
    for label, ok in tests:
        print("  [%s] %s" % ("+" if ok else "!", label))

    print("")
    print("transcription / render engines:")
    binary = transcribe.find_binary()
    model = transcribe.find_model()
    if binary:
        print("  [+] %-12s %s" % ("whisper.cpp", transcribe.version_of(binary)))
        print("                 %s" % guard.rel(binary))
    else:
        print("  [ ] %-12s %-32s %s" % ("whisper.cpp", "offline transcription fallback",
                                        "not installed"))
    if model:
        print("  [+] %-12s %s, %.0f MB" % ("model", os.path.basename(model),
                                           os.path.getsize(model) / (1024.0 * 1024.0)))
    else:
        print("  [ ] %-12s %-32s %s" % ("model", "ggml weights for whisper.cpp",
                                        "not installed"))
    melt = mlt.melt_version()
    if melt:
        print("  [+] %-12s %s" % ("Shotcut", "%s (MLT renderer/writer)" % melt))
        print("                 %s" % guard.rel(mlt.MELT))
        print("      [i] .mlt projects: python -m cutwright build <plan.json>"
              "  (Shotcut %s)" % mlt.shotcut_version())
    else:
        print("  [ ] %-12s %-32s %s" % ("Shotcut", "the .mlt renderer/writer",
                                        "not installed"))
    if binary and model:
        print("      [i] transcribe needs no further setup")
    else:
        print("      [i] run: python -m cutwright transcribe <video>   for the "
              "exact steps")
    return 0 if all(ok for _l, ok in tests) else 3


def _count_files(folder):
    return sum(len(files) for _d, _s, files in os.walk(folder))


def _tree_size(folder):
    total = 0
    for dirpath, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------
def cmd_probe(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print("[!] no such file: %s" % video)
        return 3
    info = probe.media_info(video)
    print("[i] %s" % info["name"])
    print("    duration  %s  (%.3fs)" % (moments.fmt_mmss(info["duration"]),
                                         info["duration"]))
    print("    picture   %dx%d @ %.3g fps, %s" %
          (info["width"], info["height"], info["fps"], info["video_codec"] or "?"))
    print("    size      %.1f MB   format %s" %
          (info["size"] / (1024.0 * 1024.0), info["format"]))
    print("    audio     %s" % (", ".join(
        "%s/%dch/%dHz/%s" % (a["codec"], a["channels"], a["sample_rate"], a["language"])
        for a in info["audio"]) or "none"))
    if not info["subs"]:
        print("    subs      none")
    for s in info["subs"]:
        kind = "text" if s["text"] else ("PICTURE" if s["picture"] else "?")
        print("    subs      #%d %-18s %-4s %s%s" %
              (s["index"], s["codec"], s["language"], kind,
               " (forced)" if s["forced"] else ""))
    return 0


# ---------------------------------------------------------------------------
# the gate, for humans
# ---------------------------------------------------------------------------
def _print_gate(report):
    rule()
    print("SUBTITLE GATE")
    rule()
    if not report["ladder"]:
        print("  no candidates found")
    for row in report["ladder"]:
        mark = "[+]" if row.get("ok") else "[!]"
        name = os.path.basename(row.get("path", "?"))
        print("  %s rung %d  %-9s %s" %
              (mark, row.get("rank", 0), row.get("origin", "?"), name))
        if row.get("error"):
            print("       error    %s" % row["error"])
            continue
        if "metrics" in row:
            m = row["metrics"]
            checks = row.get("checks") or {}
            ok = sum(1 for v in checks.values() if v == "ok")
            print("       format   %s, decoded as %s" % (row["format"], row["encoding"]))
            print("       metrics  %d cues, %.1f cues/min, mean %.2fs, %.0f wpm, "
                  "%d words" % (m["cues"], m["cues_per_min"], m["mean_dur"],
                                m["wpm"], m["words"]))
            print("       checks   %d of %d passed" % (ok, len(checks)))
            if row.get("language_detail") and checks.get("language") == "ok":
                print("       language %s" % row["language_detail"])
            dropped = row.get("dropped") or {}
            if dropped.get("drawings") or dropped.get("styles"):
                print("       cleaned  %d drawing cue(s), %d non-dialogue cue(s) "
                      "removed of %d before checks"
                      % (dropped.get("drawings", 0),
                         sum((dropped.get("styles") or {}).values()),
                         dropped.get("input", 0)))
        for fail in row.get("fails") or []:
            print("       FAIL     %s" % fail)
        for warn in row.get("warns") or []:
            print("       warn     %s" % warn)
        for ex in (row.get("examples") or [])[:2]:
            stamp = ("%.1fs" % ex["start"]) if "start" in ex else ("%.1fs" % ex.get("at", 0))
            print("       e.g.     %s  %s  %s" % (stamp, ex.get("why", ""),
                                                  (ex.get("text") or "")[:60]))
    print("")
    print("  status   %s" % report["status"].upper())
    print("  note     %s" % report["note"])
    rule()


def _run_gate_for(args, video, info, out):
    return subs.run_gate(video, info, args.subs, args.expect,
                         os.path.join(out, "subs_extracted"), guard)


def cmd_subs(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print("[!] no such file: %s" % video)
        return 3
    info = probe.media_info(video)
    out = out_dir_for(video, args.out)
    report = _run_gate_for(args, video, info, out)
    report["video"] = {"path": video, "name": info["name"],
                       "duration": info["duration"]}
    path = guard.write_json(os.path.join(out, "subs_report.json"), report)
    _print_gate(report)
    print("[i] wrote %s" % guard.rel(path))
    if report["status"] == "verified":
        return 0
    print("[!] no trustworthy transcript. Do not proceed to moments.")
    print("    Either transcribe the audio, or supply a subtitle file with --subs.")
    return 2


# ---------------------------------------------------------------------------
# moments
# ---------------------------------------------------------------------------
def cmd_moments(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print("[!] no such file: %s" % video)
        return 3

    info = probe.media_info(video)
    out = out_dir_for(video, args.out)
    gate = _run_gate_for(args, video, info, out)
    guard.write_json(os.path.join(out, "subs_report.json"),
                     dict(gate, video={"path": video, "name": info["name"],
                                       "duration": info["duration"]}))

    if gate["status"] != "verified":
        _print_gate(gate)
        print("[!] refusing to build moments from an unverified transcript.")
        print("    The gate exists so a wrong or garbage subtitle file cannot quietly")
        print("    become the spine of your edit.")
        return 2

    chosen = gate["chosen"]
    loaded = subs.load_cues(chosen["path"])
    transcript = {"origin": chosen["origin"], "path": chosen["path"],
                  "format": loaded["format"], "encoding": loaded["encoding"],
                  "cues": len(loaded["cues"]), "bytes": loaded["bytes"],
                  "language": chosen.get("language", "unknown")}

    doc = moments.build_doc(info, gate, transcript, loaded["cues"],
                            args.top, args.acts, args.min_gap)
    json_path = guard.write_json(os.path.join(out, "moments.json"), doc)
    digest_path = guard.write_text(os.path.join(out, "moments_digest.txt"),
                                   moments.digest(doc))

    rule()
    print("MOMENTS / %s" % info["name"])
    rule()
    print("  duration    %s   %dx%d%s" % (
        moments.fmt_mmss(info["duration"]), info["width"], info["height"],
        "  vertical" if info["height"] > info["width"] else ""))
    print("  transcript  %s from %s (%s), %d cues" % (
        loaded["format"], chosen["origin"], loaded["encoding"],
        len(loaded["cues"])))
    print("  gate        %s" % gate["note"])
    print("  beats       %d -> %d candidates" % (doc["beats"],
                                                len(doc["candidates"])))
    print("")
    print_table(moments.digest_table(doc),
                [("rank", "#", 3), ("at", "starts", 8), ("len", "len", 6),
                 ("score", "score", 6), ("hits", "what fires", 26),
                 ("quote", "what is said", 60)])
    print("")
    print("[i] wrote %s" % guard.rel(json_path))
    print("[i] wrote %s" % guard.rel(digest_path))
    rule()
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def cmd_verify(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print("[!] no such file: %s" % video)
        return 3

    info = probe.media_info(video)
    out = out_dir_for(video, args.out)
    moments_path = (os.path.abspath(args.moments) if args.moments
                    else os.path.join(out, "moments.json"))
    doc = guard.read_json(moments_path)
    if not doc or not doc.get("candidates"):
        print("[!] no moments at %s" % guard.rel(moments_path))
        print("    run: cutwright moments \"%s\"" % video)
        return 2

    claims_path = (os.path.abspath(args.claims) if args.claims
                   else os.path.join(out, "claims.json"))
    claims = frames.load_claims(claims_path)
    missing = frames.unclaimed(doc, claims)
    if missing:
        if not os.path.isfile(claims_path):
            frames.template(doc, claims, claims_path)
        rule()
        print("VERIFY / %s" % info["name"])
        rule()
        print("  %d of %d pick(s) have no expected claim -- refusing to grade them."
              % (len(missing), len(doc["candidates"])))
        print("")
        for c in missing:
            print("  %-6s %-8s %s" % (c["id"], moments.fmt_mmss(c["t_start"]),
                                      " ".join(c["quote"].split())[:62]))
        print("")
        print("  A pick is worth exactly what its claim is worth. Fill in")
        print("    %s" % guard.rel(claims_path))
        print("  then run verify again. Claims come from the transcript; the")
        print("  frames decide whether the claim survives.")
        rule()
        return 2

    gate = _run_gate_for(args, video, info, out)
    if gate["status"] != "verified":
        _print_gate(gate)
        print("[!] refusing to verify against an unverified transcript.")
        return 2
    cues = subs.load_cues(gate["chosen"]["path"])["cues"]

    review_path = (os.path.abspath(args.review) if args.review
                   else os.path.join(out, "review.json"))
    review = frames.load_review(review_path)

    print("[i] grading %d pick(s) against %s ..."
          % (len(doc["candidates"]), info["name"]))
    report = frames.run_verify(video, info, doc, claims, cues, out,
                               write_back=True, review=review)

    json_path = guard.write_json(os.path.join(out, "frames.json"), report)
    digest_path = guard.write_text(os.path.join(out, "verify_digest.txt"),
                                   frames.digest(report))
    if args.write_back:
        guard.write_json(moments_path, doc)

    s = report["summary"]
    rule()
    print("VERIFY / %s" % info["name"])
    rule()
    print("  duration    %s   %dx%d" % (moments.fmt_mmss(info["duration"]),
                                        info["width"], info["height"]))
    print("  frames      %s" % report["frame_dir"])
    print("  graded      %s" % ", ".join("%d %s" % (s[k], k) for k in frames.STATUSES))
    if report.get("reviewed"):
        print("  reviewed    %d of %d pick(s): the agent looked at the frames"
              % (report["reviewed"], len(report["candidates"])))
    print("")
    print_table(frames.digest_table(report),
                [("rank", "#", 3), ("id", "id", 6), ("status", "status", 10),
                 ("at", "starts", 8), ("luma", "luma", 12),
                 ("warns", "warn", 4), ("why", "why", 40)])
    print("")
    warned = [r for r in report["candidates"] if r.get("warns")]
    if warned:
        print("  warnings -- kept as warnings, none of these changes a grade:")
        for r in warned:
            for warn in r["warns"]:
                print("    %-6s %s" % (r["id"], warn))
        print("")
    if s["retimed"]:
        print("  %d pick(s) retimed: the picture is there, the cut is not. New"
              % s["retimed"])
        print("  in-points are proposed above, not applied.")
    if s["replaced"]:
        print("  [!] %d pick(s) replaced: what is on screen is not what the claim"
              % s["replaced"])
        print("      said. Drop them or re-describe them -- do not ship them.")
    if s["unverified"]:
        print("  [!] %d pick(s) still unverified." % s["unverified"])
    print("")
    print("[i] wrote %s" % guard.rel(json_path))
    print("[i] wrote %s" % guard.rel(digest_path))
    if args.write_back:
        print("[i] wrote %s  (statuses patched back)" % guard.rel(moments_path))
    rule()
    return 2 if (s["unverified"] or s["replaced"]) else 0


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------
def cmd_transcribe(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print("[!] no such file: %s" % video)
        return 3
    info = probe.media_info(video)
    out = out_dir_for(video, args.out)

    rule("=")
    print("CUTWRIGHT TRANSCRIBE / %s" % info["name"])
    rule("=")
    if not info["audio"]:
        print("[!] this file has no audio stream -- nothing to transcribe")
        return 3
    index, stream = transcribe.choose_audio(info, args.language)
    print("audio      stream %d (%s, %s, %dch) of %d"
          % (index, stream.get("language", "und"), stream.get("codec", "?"),
             stream.get("channels", 0), len(info["audio"])))
    print("engine     whisper.cpp + %s, language %s"
          % (os.path.basename(args.model) if args.model else transcribe.DEFAULT_MODEL,
             args.language))
    cached = None
    if not args.fresh:
        cached = transcribe.cached_run(
            out, transcribe.cache_key(video, info, args.language,
                                      transcribe.find_binary(args.whisper),
                                      transcribe.find_model(args.model)))
    if cached:
        print("[i] a transcript for these exact inputs already exists (%s) -- "
              "reusing it, no model run." % (cached.get("ran_at") or "earlier"))
    else:
        print("[i] this is the slow step: roughly a quarter of real time on 8 CPU "
              "threads.")
    print("[i] nothing is written outside this fork.")
    print("")

    report = transcribe.run_transcribe(
        video, info, out, language=args.language, expect=args.expect,
        binary=args.whisper, model=args.model, threads=args.threads,
        reference=args.subs, fresh=args.fresh)

    if report["status"] == "blocked":
        print("[!] cannot transcribe yet:")
        for problem in report["problems"]:
            print("    - %s" % problem)
        print("")
        for line in report.get("hints") or []:
            print("  " + line)
        rule()
        return 3
    if report["status"] == "error":
        print("[!] %s" % report["note"])
        rule()
        return 3

    json_path = guard.write_json(os.path.join(out, "transcript.json"), report)
    digest_path = guard.write_text(os.path.join(out, "transcript_digest.txt"),
                                   transcribe.digest(report))

    counts = report["counts"]
    m = report["metrics"]
    if report["engine"].get("cached"):
        print("whisper    reused %d cached segment(s); no model run (original pass "
              "%s, %.1fs)" % (counts["segments"],
                              report["engine"].get("ran_at") or "earlier",
                              report["engine"].get("wall_s") or 0.0))
    else:
        print("whisper    %d segment(s) in %.1fs, %d thread(s)"
              % (counts["segments"], report["engine"]["wall_s"],
                 report["engine"]["threads"]))
    print("cues       %d kept, %d dropped as non-speech"
          % (counts["kept"], counts["dropped_nonspeech"]))
    print("metrics    %.1f cues/min  mean %.2fs  %.0f wpm  %d words  covers %.0f%%"
          % (m["cues_per_min"], m["mean_dur"], m["wpm"], m["words"],
             m["coverage"] * 100))
    checks = report["checks"]
    print("gate       %d of %d check(s) passed"
          % (sum(1 for value in checks.values() if value == "ok"), len(checks)))
    for line in report["fails"]:
        print("  FAIL     %s" % line)
    for line in report["warns"]:
        print("  warn     %s" % line)
    for check in report["signals"]["checks"]:
        print("  %-8s %s" % ("signal" if check["ok"] else "signal!",
                             "%s: %s" % (check["name"], check["detail"])))
    ref = report.get("reference")
    if ref and not ref.get("error"):
        print("reference  %d of %d line(s) found in %s (%.0f%% match)"
              % (ref["matched"], ref["cues"], os.path.basename(ref["path"]),
                 ref["rate"] * 100))
        if ref.get("offset_s") is not None:
            print("           offset %+.1fs agreed by %d line(s)"
                  % (ref["offset_s"], ref["offset_support"]))
    elif ref and ref.get("error"):
        print("reference  could not be read: %s" % ref["error"])
    print("")
    for cue in report["cues_preview"][:6]:
        print("  %7.2f  %s" % (cue["start"], cue["text"][:64]))
    print("")
    print("  status   %s" % report["status"].upper())
    print("  note     %s" % report["note"])
    rule()
    print("[i] wrote %s" % guard.rel(json_path))
    print("[i] wrote %s" % guard.rel(digest_path))
    print("[i] srt     %s  (checked copy; raw whisper output kept beside it)"
          % report["artifacts"]["srt"])
    if report["ok"]:
        print("[i] next: python -m cutwright moments \"%s\" --subs \"%s\""
              % (video, os.path.join(out, "transcript.srt")))
        return 0
    print("[!] the gate did not pass. Do not build a subtitle track from this.")
    print("    Re-run with --fresh, a bigger model, or supply a real subtitle file.")
    return 2


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def cmd_build(args):
    plan = os.path.abspath(args.plan)
    if not os.path.isfile(plan):
        print("[!] no such plan: %s" % plan)
        return 3
    rule("=")
    print("CUTWRIGHT %s  build" % VERSION)
    rule("=")
    wanted = None
    if args.checks:
        wanted = [c.strip().lower() for c in args.checks.split(",") if c.strip()]
    try:
        result = mlt.build(plan, width=args.width, crf=args.crf,
                           samples=args.samples, checks=wanted)
    except mlt.PlanError as exc:
        print("[!] %s" % exc)
        return 4

    project = result["project"]
    profile = project.profile
    print("plan        %s" % guard.rel(result["plan"]["path"]))
    print("project     %s" % guard.rel(result["path"]))
    print("shotcut     Shotcut %s / MLT %s  (written into the file)"
          % (project.shotcut, project.mlt))
    print("profile     %dx%d @ %.3f fps (%d/%d), colorspace %s"
          % (profile.width, profile.height, profile.fps, profile.fps_num,
             profile.fps_den, profile.colorspace))
    print("timeline    %d frames, %.3f s, %d clip(s)"
          % (project.length, profile.seconds(project.length),
             len(project.clips)))
    print("")

    rows = []
    for index, clip in enumerate(project.clips):
        rows.append({"n": str(index), "track": "V1 + A1",
                     "file": os.path.basename(clip["source"]),
                     "in": "%.2f" % (clip["in"] / profile.fps),
                     "out": "%.2f" % ((clip["out"] + 1) / profile.fps),
                     "frames": str(clip["frames"]), "label": clip["label"]})
    print_table(rows, [("n", "#", 2), ("track", "track", 7), ("file", "file", 24),
                       ("in", "in", 6), ("out", "out", 6), ("frames", "frames", 6),
                       ("label", "label", 26)])
    print("")
    rule("-")
    for check in result["checks"]:
        print("  [%s] %-8s %s" % ("+" if check["ok"] else "!", check["name"],
                                  check["detail"]))
    for name in result["skipped"]:
        print("  [ ] %-8s not run" % name)
    rule("-")

    failed = [c for c in result["checks"] if not c["ok"]]
    if failed:
        print("verdict     NOT ready: %d check(s) failed" % len(failed))
        return 5
    if result["skipped"]:
        print("verdict     %d check(s) passed, NOT RUN: %s"
              % (len(result["checks"]), ", ".join(result["skipped"])))
        return 0
    print("verdict     all checks passed")
    print("open it     %s" % os.path.abspath(result["path"]))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="cutwright",
        description="Transcript-first editing control. Writes only inside this folder.")
    ap.add_argument("--version", action="version", version="cutwright %s" % VERSION)
    sub = ap.add_subparsers(dest="step", metavar="STEP")

    p = sub.add_parser("doctor", help="what this machine has; proves the write guard")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("probe", help="streams and duration of one file")
    p.add_argument("video")
    p.set_defaults(func=cmd_probe)

    for name, func, help_text in (
            ("subs", cmd_subs, "validate the best available subtitle source"),
            ("moments", cmd_moments, "rank candidate moments from the transcript")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("video")
        p.add_argument("--subs", metavar="FILE",
                       help="a subtitle file to trust above everything else")
        p.add_argument("--expect", default="english",
                       help="language the subtitles should be in (default: english)")
        p.add_argument("--out", metavar="DIR",
                       help="output folder (default: out/<video name>/)")
        p.set_defaults(func=func)
        if name == "moments":
            p.add_argument("--top", type=int, default=12,
                           help="how many candidates to shortlist (default 12)")
            p.add_argument("--acts", type=int, default=5,
                           help="split the runtime into this many acts (default 5)")
            p.add_argument("--min-gap", type=float, default=20.0, dest="min_gap",
                           help="minimum seconds between two picks (default 20)")
    p = sub.add_parser("verify",
                       help="grade picks against frames: verified/retimed/replaced")
    p.add_argument("video")
    p.add_argument("--subs", metavar="FILE",
                   help="a subtitle file to trust above everything else")
    p.add_argument("--expect", default="english",
                   help="language the subtitles should be in (default: english)")
    p.add_argument("--out", metavar="DIR",
                   help="output folder (default: out/<video name>/)")
    p.add_argument("--moments", metavar="FILE",
                   help="moments.json to grade (default: <out>/moments.json)")
    p.add_argument("--claims", metavar="FILE",
                   help="expected claims per pick (default: <out>/claims.json)")
    p.add_argument("--review", metavar="FILE",
                   help="agent verdicts on frames actually looked at "
                        "(default: <out>/review.json)")
    p.add_argument("--write-back", action="store_true", dest="write_back",
                   help="patch status and expected back into moments.json")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("build",
                       help="write a Shotcut .mlt from a plan, then check it")
    p.add_argument("plan", help="plan JSON: clips with in/out (see README)")
    p.add_argument("--width", type=int, default=270,
                   help="width of the proof render in pixels (default 270)")
    p.add_argument("--crf", type=int, default=34,
                   help="proof render quality, higher is smaller (default 34)")
    p.add_argument("--samples", type=int, default=3,
                   help="how many clips to compare frames for (default 3)")
    p.add_argument("--checks", metavar="LIST",
                   help="subset of xml,effects,lengths,render to run "
                        "(default: all four)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("transcribe",
                       help="whisper.cpp fallback: transcribe the audio, gate it")
    p.add_argument("video")
    p.add_argument("--language", default="en",
                   help="spoken language code to transcribe (default: en)")
    p.add_argument("--expect", default=None,
                   help="language the checks expect (default: derived from "
                        "--language)")
    p.add_argument("--whisper", metavar="EXE",
                   help="whisper-cli.exe to use (default: bin\\whisper\\Release\\)")
    p.add_argument("--model", metavar="BIN",
                   help="ggml model to use (default: models\\%s)"
                        % transcribe.DEFAULT_MODEL)
    p.add_argument("--threads", type=int, default=None,
                   help="CPU threads for whisper (default: up to 8)")
    p.add_argument("--subs", metavar="FILE",
                   help="reference subtitles to cross-check the wording against; "
                        "these do not set timing")
    p.add_argument("--fresh", action="store_true",
                   help="re-extract the 16 kHz WAV instead of reusing it")
    p.add_argument("--out", metavar="DIR",
                   help="output folder (default: out/<video name>/)")
    p.set_defaults(func=cmd_transcribe)
    return ap


def main(argv=None):
    # Subtitles are multilingual by nature; a cp1252 console must not be able to
    # crash the tool (or mangle the report) just because a line is Japanese.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "step", None):
        ap.print_help()
        return 0
    return args.func(args) or 0


