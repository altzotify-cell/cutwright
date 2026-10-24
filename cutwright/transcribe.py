"""Whisper transcription: what happens after the subtitle ladder runs out.

subs.py never invents a transcript -- rung 4 returns `needs_whisper` and says so.
This module is that rung: a local whisper.cpp binary, one fixed model, and the
*same* gate in subs.validate() applied to what comes back. A transcript is not
trusted because we produced it; it is trusted because it survives the checks a
downloaded .srt has to survive.

Three signals are added on top of the gate, and all three are warnings -- they
describe how the model felt about its own output, they do not overrule a check.
whisper.cpp 1.9.5 exposes only per-token probabilities, so each is derived from
those rather than read out of a field that does not exist:

  * decoder confidence -- mean ln(p) per segment, which is what OpenAI whisper
    calls avg_logprob. Segments below -1.0 are where the model was guessing.
  * weak tokens        -- share of tokens below p=0.3: localised stumbles, the
    shape of a half-heard line rather than a whole invented one.
  * repetition risk    -- text bytes over zlib-compressed bytes (>2.4), which is
    whisper's own loop tripwire, recomputed. Fires when the decoder repeats.

Why a separate 16 kHz mono WAV: whisper.cpp reads flac/mp3/ogg/wav and wants
16 kHz mono PCM. ffmpeg does the downmix once, so the model's input is
predictable and the whole step is reproducible by hand from a command line.

Why a reference is optional but useful: for a clip cut out of a longer film, the
film's own subtitles are an answer key. They cannot be used for timing -- they
are offset by however much was trimmed off the front -- but they can be used for
*wording*. If the transcript's lines are found in the reference and their time
deltas agree to within a second, the transcript is provably the dialogue that is
really in the clip, and the delta says where the clip sits in the film.
"""
import json
import math
import os
import re
import shutil
import time
import zlib

from . import guard
from . import probe
from . import subs

# Newest release layout first: b5454/v1.9.5 unzips into Release\.
WHISPER_CANDIDATES = (
    os.path.join("bin", "whisper", "Release", "whisper-cli.exe"),
    os.path.join("bin", "whisper", "whisper-cli.exe"),
    os.path.join("bin", "whisper", "Release", "main.exe"),
    os.path.join("bin", "whisper", "main.exe"),
)
MODEL_DIR = os.path.join(guard.ROOT, "models")
DEFAULT_MODEL = "ggml-small.en.bin"

# Thresholds as module constants, so the digest can quote them the way
# frames.py quotes its cut threshold.
LOW_LOGPROB = -1.0       # below this the decoder was guessing
WEAK_TOKEN_P = 0.30      # a token this unlikely is a stumble, not a choice
WEAK_TOKEN_SHARE = 0.05  # warn when more than this share of tokens stumble
COMPRESSION_RATIO = 2.4  # whisper's own loop tripwire
LOW_CONF_SHARE = 0.25    # warn when more than this share is low-confidence
OFFSET_TOLERANCE = 1.0   # seconds; deltas must agree this closely to count

WORD_RE = re.compile(r"[a-z0-9']+")


def _check(name, level, ok, detail):
    return {"name": name, "level": level, "ok": bool(ok), "detail": detail}


def _rel(path):
    return guard.rel(path) if path else ""


# ---------------------------------------------------------------------------
# finding the pieces
# ---------------------------------------------------------------------------
def find_binary(override=None):
    """Path to whisper-cli.exe, or None. Override wins if it exists."""
    if override:
        path = os.path.abspath(override)
        return path if os.path.isfile(path) else None
    for rel_path in WHISPER_CANDIDATES:
        full = os.path.join(guard.ROOT, rel_path)
        if os.path.isfile(full):
            return full
    return None


def find_model(override=None, name=DEFAULT_MODEL):
    """Path to the ggml model file, or None."""
    if override:
        path = os.path.abspath(override)
        return path if os.path.isfile(path) else None
    full = os.path.join(MODEL_DIR, name)
    return full if os.path.isfile(full) else None


def version_of(binary):
    """Ask the binary what it is. Never assume: a folder name goes stale after a
    re-unzip, and an engine that lies about its version makes every number
    below untraceable."""
    try:
        r = probe.run([binary, "--version"], timeout=60)
    except Exception:
        return "?"
    text = (r.stdout or "") + (r.stderr or "")
    for line in text.splitlines():
        m = re.search(r"version[:\s]+v?(\d+\.\d+(?:\.\d+)?)", line, re.I)
        if m:
            return m.group(1)[:80]
    # Some builds (Shotcut's bundle) reject --version and print a help block or
    # GPU probe output instead. Better "?" than a temperature reading.
    return "?"

def install_note(binary_missing=True, model_missing=True):
    """Install steps for whatever is actually missing -- not a wall of both."""
    lines = []
    if binary_missing:
        lines += [
            "whisper.cpp binary missing. It is one unzip, no build:",
            "  https://github.com/ggml-org/whisper.cpp/releases/tag/b5454",
            "    -> whisper-bin-x64.zip   (the Windows build of the v1.9.5 commit)",
            "  unpack so that bin\\whisper\\Release\\whisper-cli.exe exists",
        ]
    if model_missing:
        lines += [
            "model missing: %s" % DEFAULT_MODEL,
            "  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/%s"
            % DEFAULT_MODEL,
            "    -> save as %s" % os.path.join(MODEL_DIR, DEFAULT_MODEL),
        ]
    if lines:
        lines.append("sha256 for the binary and the model are in PROVENANCE.md.")
    return "\n".join(lines)


def free_gb():
    try:
        return shutil.disk_usage(guard.ROOT).free / (1024.0 ** 3)
    except OSError:
        return 0.0


def preflight(binary, model, binary_arg=None, model_arg=None):
    """Everything knowable before the slow step. -> list of problems."""
    problems = []
    if not binary:
        problems.append("no such whisper binary: %s" % binary_arg if binary_arg
                        else "no whisper-cli.exe found under %s"
                        % os.path.join(guard.ROOT, "bin", "whisper"))
    if not model:
        problems.append("no such model file: %s" % model_arg if model_arg
                        else "no %s found in %s" % (DEFAULT_MODEL, MODEL_DIR))
    free = free_gb()
    if free and free < 1.0:
        problems.append("only %.2f GB free on the fork's drive; the WAV for a "
                        "feature needs room" % free)
    return problems


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------
def choose_audio(info, language="en"):
    """Pick the audio stream to listen to. -> (index, stream) or (None, None).

    A DUAL file carries the dub *and* the original. Transcribing the wrong one
    produces a perfect transcript of a language nobody asked for, so a declared
    language tag decides and the first stream is the fallback.
    """
    streams = info.get("audio") or []
    if not streams:
        return None, None
    want = (language or "").lower()[:2]
    if want:
        for n, st in enumerate(streams):
            if (st.get("language") or "").lower().startswith(want):
                return n, st
    return 0, streams[0]


def extract_wav(video, info, wav_path, language="en", timeout=900):
    """-> dict describing the extracted audio. Raises RuntimeError on failure."""
    index, stream = choose_audio(info, language)
    if stream is None:
        raise RuntimeError("no audio stream in %s -- nothing to transcribe"
                           % os.path.basename(video))
    guard.ensure_dir(os.path.dirname(wav_path))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video,
           "-map", "0:a:%d" % index, "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", wav_path]
    r = probe.run(cmd, timeout=timeout)
    if r.returncode != 0 or not os.path.isfile(wav_path):
        raise RuntimeError("ffmpeg could not extract audio: %s"
                           % (r.stderr or "").strip()[:200])
    size = os.path.getsize(wav_path)
    return {
        "path": wav_path,
        "index": index,
        "stream": stream,
        "bytes": size,
        "seconds": round(max(0, size - 44) / 32000.0, 3),
        "cmd": "ffmpeg -map 0:a:%d -ac 1 -ar 16000 -c:a pcm_s16le" % index,
    }


# ---------------------------------------------------------------------------
# the slow step
# ---------------------------------------------------------------------------
def run_whisper(binary, model, wav, prefix, language="en", threads=None,
                timeout=7200):
    """Run whisper-cli once. -> dict; raises RuntimeError if it produced nothing.

    -ojf keeps the machine's own numbers -- offsets, avg_logprob, no_speech_prob,
    compression_ratio -- which the gate cannot see and a .srt cannot carry.
    -oj alone looks like it does, right up until the signals below report
    "0 of 0 segment(s)": plain -oj writes only timestamps, offsets and text.
    -osrt is the shape everything downstream already reads.
    """
    threads = threads or max(1, min(8, os.cpu_count() or 4))
    guard.ensure_dir(os.path.dirname(prefix))
    cmd = [binary, "-m", model, "-f", wav, "-l", language,
           "-t", str(threads), "-ojf", "-osrt", "-otxt", "-of", prefix]
    started = time.time()
    r = probe.run(cmd, timeout=timeout)
    wall = round(time.time() - started, 1)
    wanted = {"json": prefix + ".json", "srt": prefix + ".srt",
              "txt": prefix + ".txt"}
    missing = [k for k, p in wanted.items() if not os.path.isfile(p)]
    tail = ((r.stderr or "").replace("\r", "\n").strip().splitlines() or [""])[-1]
    if r.returncode != 0 or missing:
        raise RuntimeError("whisper-cli failed (exit %d, missing %s): %s"
                           % (r.returncode, ", ".join(missing) or "nothing",
                              tail[:200]))
    out = {"threads": threads, "wall_s": wall, "stderr_tail": tail[:200],
           "cmd": " ".join([os.path.basename(cmd[0])] + cmd[1:])}
    out.update(wanted)
    return out


# ---------------------------------------------------------------------------
# what came back
# ---------------------------------------------------------------------------
def segments_from_json(path):
    """whisper's own JSON -> (segments, whole document)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)
    return (data.get("transcription") or []), data


def cues_from_segments(segments):
    """-> (cues for the gate, counts).

    Only two things are dropped, and both are counted so nothing disappears
    quietly: text with no letters or digits at all (a lone music note, a bare
    dash) and zero-length segments. Timing is never nudged -- if whisper emits
    a bad timestamp the gate should say so, not be quietly protected from it.
    """
    cues, dropped = [], 0
    for seg in segments:
        off = seg.get("offsets") or {}
        start = float(off.get("from") or 0) / 1000.0
        end = float(off.get("to") or 0) / 1000.0
        text = " ".join((seg.get("text") or "").split())
        if not text or not WORD_RE.search(text.lower()):
            if text:
                dropped += 1
            continue
        if end <= start:
            dropped += 1
            continue
        cues.append({"start": round(start, 3), "end": round(end, 3),
                     "text": text})
    return cues, {"segments": len(segments), "kept": len(cues),
                  "dropped_nonspeech": dropped}


def _segment_logprob(seg):
    """Mean ln(p) over the segment's tokens -- the same quantity OpenAI's
    `avg_logprob` is, recomputed because whisper.cpp 1.9.5 does not write it."""
    ps = []
    for tok in (seg.get("tokens") or []):
        p = tok.get("p")
        if isinstance(p, (int, float)) and p > 0:
            ps.append(float(p))
    if not ps:
        return None
    return sum(math.log(p) for p in ps) / len(ps)


def _compression_ratio(text):
    """text bytes / zlib-compressed bytes. Whisper's own loop tripwire: normal
    prose sits near 1.5-1.9, a decoder stuck on one phrase climbs past 2.4."""
    raw = text.encode("utf-8")
    if not raw:
        return 1.0
    return len(raw) / float(max(1, len(zlib.compress(raw, 9))))


def whisper_signals(segments):
    """What only a machine transcript can tell you. Warnings, never a grade.

    whisper.cpp 1.9.5 writes per-token `p` under -ojf and nothing else -- no
    segment-level avg_logprob, no no_speech_prob, no compression_ratio. So the
    numbers are derived from what exists: mean ln(p) per segment (that *is*
    avg_logprob), the share of tokens the decoder was unsure about, and the
    compression ratio recomputed with zlib. An earlier version of this function
    read the fields anyway and reported "0 of 0 segment(s) below avg_logprob",
    which looks like health and is actually silence -- hence the explicit
    signal_data warning when there is nothing to measure.
    """
    logprobs, token_ps = [], []
    for seg in segments:
        value = _segment_logprob(seg)
        if value is not None:
            logprobs.append(value)
        for tok in (seg.get("tokens") or []):
            p = tok.get("p")
            if isinstance(p, (int, float)):
                token_ps.append(float(p))
    ratios = [_compression_ratio(" ".join((s.get("text") or "").split()))
              for s in segments if (s.get("text") or "").strip()]

    if not logprobs and not token_ps:
        return {
            "checks": [_check("signal_data", "warn", False,
                              "whisper wrote no token probabilities; run with "
                              "-ojf to get the signals")],
            "mean_logprob": None,
            "mean_token_p": None,
            "warns": ["no decoder statistics in the whisper output"],
        }

    low = [v for v in logprobs if v < LOW_LOGPROB]
    weak = [p for p in token_ps if p < WEAK_TOKEN_P]
    loops = [r for r in ratios if r > COMPRESSION_RATIO]
    checks = [
        _check("decoder_confidence", "warn",
               (len(low) / float(len(logprobs) or 1)) <= LOW_CONF_SHARE,
               "%d of %d segment(s) with mean ln(p) below %.1f"
               % (len(low), len(logprobs), LOW_LOGPROB)),
        _check("weak_tokens", "warn",
               (len(weak) / float(len(token_ps) or 1)) <= WEAK_TOKEN_SHARE,
               "%d of %d token(s) below p=%.1f"
               % (len(weak), len(token_ps), WEAK_TOKEN_P)),
        _check("repetition_risk", "warn", not loops,
               "%d of %d segment(s) with compression ratio above %.1f"
               % (len(loops), len(ratios), COMPRESSION_RATIO)),
    ]
    return {
        "checks": checks,
        "mean_logprob": round(sum(logprobs) / len(logprobs), 3) if logprobs else None,
        "mean_token_p": (round(sum(token_ps) / len(token_ps), 3)
                         if token_ps else None),
        "warns": [c["detail"] for c in checks if not c["ok"]],
    }


def normalise(text):
    """Comparison form: lowercase, curly quotes flattened, punctuation gone."""
    t = (text or "").lower().replace("\u2019", "'").replace("\u2018", "'")
    return " ".join(WORD_RE.findall(t))


def reference_match(cues, ref_cues, path="", min_words=3):
    """Are the transcript's lines really in the reference subtitle file?

    -> {matched, rate, offset_s, offset_support, examples}. The offset is only
    reported when a majority of matched lines agree on it to within
    OFFSET_TOLERANCE; otherwise the deltas are inconsistent and the number would
    be meaningless. `min_words` keeps two-word lines ("Yes, sir") out of the
    count, because those match by coincidence.
    """
    index = {}
    for cue in ref_cues:
        key = normalise(cue["text"])
        if len(key.split()) >= min_words:
            index.setdefault(key, []).append(cue["start"])
    if not index:
        return {"path": path, "cues": len(cues), "matched": 0, "rate": 0.0,
                "offset_s": None, "offset_support": 0, "examples": [],
                "note": "reference had no line long enough to compare"}

    deltas, examples = [], []
    for cue in cues:
        key = normalise(cue["text"])
        if len(key.split()) < min_words:
            continue
        starts = index.get(key)
        if not starts:
            continue
        # a line can repeat in a film; keep whichever placement agrees best with
        # the running median rather than the first one alphabetically
        base = sorted(deltas)[len(deltas) // 2] if deltas else None
        if base is None:
            ref_start = starts[0]
        else:
            ref_start = min(starts, key=lambda s: abs((s - cue["start"]) - base))
        deltas.append(round(ref_start - cue["start"], 2))
        if len(examples) < 4:
            examples.append({"line": cue["text"][:70],
                             "at": round(cue["start"], 2),
                             "ref_at": round(ref_start, 2),
                             "delta": round(ref_start - cue["start"], 2)})

    matched = len(deltas)
    rate = round(matched / float(max(1, len(cues))), 3)
    offset, support = None, 0
    if deltas:
        best = []
        for candidate in deltas:
            cluster = [d for d in deltas if abs(d - candidate) <= OFFSET_TOLERANCE]
            if len(cluster) > len(best):
                best = cluster
        support = len(best)
        if support >= max(3, matched // 2):
            offset = round(sorted(best)[len(best) // 2], 2)
    return {"path": path, "cues": len(cues), "matched": matched, "rate": rate,
            "offset_s": offset, "offset_support": support, "examples": examples}

# ---------------------------------------------------------------------------
# cache: whisper is the slow step, so it must never run twice for one file
# ---------------------------------------------------------------------------
def cache_key(video, info, language, binary, model):
    """Everything that changes what whisper would produce, as data that can be
    compared for equality. Sizes and mtimes, never the 487 MB model's hash --
    hashing it would cost more than the run it protects."""
    def stamp(path):
        try:
            st = os.stat(path)
            return [st.st_size, int(st.st_mtime)]
        except (OSError, TypeError):
            return [0, 0]
    return {"video": stamp(video),
            "duration": round(float(info.get("duration") or 0.0), 2),
            "language": language or "en",
            "model": stamp(model),
            "binary": stamp(binary)}


def cached_run(out_dir, key):
    """-> a run dict describing a previous whisper pass on identical inputs, or
    None when the cache cannot be trusted.

    The cache is keyed on the actual inputs, not on the output file existing: a
    different clip, a different model, a re-encode or a whisper upgrade all
    miss. A JSON older than its own inputs is stale even if the key matches.
    """
    prefix = os.path.join(out_dir, "whisper")
    paths = {ext: prefix + "." + ext for ext in ("json", "srt", "txt")}
    if not all(os.path.isfile(p) for p in paths.values()):
        return None
    try:
        with open(os.path.join(out_dir, "whisper_cache.json"), "r",
                  encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    if meta.get("key") != key:
        return None
    newest_input = max(key["model"][1], key["binary"][1], key["video"][1])
    try:
        if int(os.path.getmtime(paths["json"])) < newest_input:
            return None
    except OSError:                       # deleted between the checks above
        return None
    return {"json": paths["json"], "srt": paths["srt"], "txt": paths["txt"],
            "wall_s": meta.get("wall_s"), "threads": meta.get("threads"),
            "cmd": "reused cache, no model run", "cached": True,
            "ran_at": meta.get("ran_at"), "audio": meta.get("audio")}


def remember_run(out_dir, key, run, audio=None):
    """Record what was run so the next call can prove it does not need to."""
    return guard.write_json(
        os.path.join(out_dir, "whisper_cache.json"),
        {"key": key, "wall_s": run.get("wall_s"), "threads": run.get("threads"),
         "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cmd": run.get("cmd", ""),
         "audio": audio or {}})


# ---------------------------------------------------------------------------
# the whole step
# ---------------------------------------------------------------------------
def run_transcribe(video, info, out_dir, language="en", expect=None,
                   binary=None, model=None, threads=None, reference=None,
                   fresh=False, timeout=7200):
    """-> report dict. Never raises for a missing install or a failed gate: a
    transcript that cannot be trusted is a *result*, not a crash.

    status:
      blocked   the pieces are not there (binary, model, disk) -- nothing ran
      error     ffmpeg or whisper-cli failed -- nothing was produced
      verified  produced, and it passed the same gate a downloaded .srt must
      failed    produced, but it does not survive the gate. Do not ship it.
    """
    expect = expect or ("english" if (language or "en").lower().startswith("en")
                        else language)
    out_dir = guard.ensure_dir(out_dir)
    binary_arg, model_arg = binary, model
    binary = find_binary(binary_arg)
    model = find_model(model_arg)
    problems = preflight(binary, model, binary_arg, model_arg)

    report = {
        "video": {"path": video, "name": info.get("name", os.path.basename(video)),
                  "duration": info.get("duration", 0.0),
                  "size": info.get("size", 0)},
        "engine": {"name": "whisper.cpp",
                   "version": version_of(binary) if binary else "?",
                   "binary": _rel(binary), "model": _rel(model),
                   "model_bytes": os.path.getsize(model) if model else 0,
                   "language": language, "threads": None,
                   "wall_s": None, "cmd": "", "audio_map": "",
                   "cached": False, "ran_at": None,
                   "reported_language": None},
        "audio": None,
        "counts": None,
        "metrics": None,
        "checks": {},
        "fails": [],
        "warns": [],
        "signals": None,
        "reference": None,
        "cues_preview": [],
        "artifacts": {},
        "status": "blocked",
        "ok": False,
        "note": "",
        "problems": problems,
        "hints": [],
    }
    if problems:
        report["note"] = "; ".join(problems)
        report["hints"] = install_note(binary is None,
                                       model is None).splitlines()
        return report

    # The model is 487 MB: hashing it on every run would cost more than the step
    # it is meant to protect. Its hash is recorded once in PROVENANCE.md.
    wav_path = os.path.join(out_dir, "audio", "%s_16k.wav" % (language or "en"))
    key = cache_key(video, info, language, binary, model)
    run = None if fresh else cached_run(out_dir, key)

    if run is None:
        try:
            if fresh or not os.path.isfile(wav_path):
                audio = extract_wav(video, info, wav_path, language)
            else:
                index, stream = choose_audio(info, language)
                size = os.path.getsize(wav_path)
                audio = {"path": wav_path, "index": index, "stream": stream,
                         "bytes": size,
                         "seconds": round(max(0, size - 44) / 32000.0, 3),
                         "cmd": "reused %s" % guard.rel(wav_path)}
        except RuntimeError as exc:
            report["status"] = "error"
            report["note"] = str(exc)
            return report
        report["audio"] = {"path": guard.rel(audio["path"]),
                           "stream_index": audio["index"],
                           "language": (audio["stream"] or {}).get("language", "und"),
                           "bytes": audio["bytes"], "seconds": audio["seconds"],
                           "cmd": audio["cmd"]}

        prefix = os.path.join(out_dir, "whisper")
        try:
            run = run_whisper(binary, model, wav_path, prefix, language=language,
                              threads=threads, timeout=timeout)
        except RuntimeError as exc:
            report["status"] = "error"
            report["note"] = str(exc)
            return report
        remember_run(out_dir, key, run, report["audio"])
    else:
        # Cache hit: whisper already read this exact audio, so there is nothing
        # to extract and no reason to touch the 8 MB WAV.
        audio_note = run.get("audio") or {
            "path": guard.rel(wav_path), "stream_index": None,
            "language": (choose_audio(info, language)[1] or {}).get("language", "und"),
            "bytes": os.path.getsize(wav_path) if os.path.isfile(wav_path) else 0,
            "seconds": None, "cmd": "not re-read"}
        report["audio"] = audio_note

    report["engine"].update({"threads": run["threads"], "wall_s": run["wall_s"],
                             "cmd": run["cmd"], "cached": bool(run.get("cached")),
                             "ran_at": run.get("ran_at"),
                             "audio_map": (report["audio"] or {}).get("cmd", "")})

    segments, doc = segments_from_json(run["json"])
    cues, counts = cues_from_segments(segments)
    report["counts"] = counts
    report["engine"]["reported_language"] = (doc.get("result") or {}).get("language")

    gate = subs.validate(cues, info.get("duration", 0.0), expect=expect)
    report["metrics"] = gate["metrics"]
    report["checks"] = {c["name"]: ("ok" if c["ok"] else c["level"])
                        for c in gate["checks"]}
    report["fails"] = [c["name"] + ": " + c["detail"] for c in gate["fails"]]
    report["warns"] = [c["name"] + ": " + c["detail"] for c in gate["warns"]]
    report["examples"] = gate["examples"]
    report["signals"] = whisper_signals(segments)
    report["cues_preview"] = [{"start": c["start"], "end": c["end"],
                               "text": c["text"]} for c in cues[:10]]

    if reference and os.path.isfile(reference):
        try:
            ref = subs.load_cues(reference)["cues"]
            report["reference"] = reference_match(
                cues, ref, path=guard.rel(reference))
        except Exception as exc:                    # unreadable answer key
            report["reference"] = {"path": guard.rel(reference),
                                   "error": str(exc)[:160]}

    # The SRT downstream reads is a byte-identical copy through the guard: the
    # raw whisper artifact stays untouched, and the checked one is the same bytes
    # that passed the gate (guard.write_text would rewrite CRLF to LF).
    with open(run["srt"], "rb") as f:
        srt_bytes = f.read()
    checked_srt = guard.write_bytes(os.path.join(out_dir, "transcript.srt"),
                                    srt_bytes)
    report["artifacts"] = {
        "srt": guard.rel(checked_srt),
        "raw_json": guard.rel(run["json"]),
        "raw_srt": guard.rel(run["srt"]),
        "raw_txt": guard.rel(run["txt"]),
        "wav": report["audio"]["path"],
    }

    report["ok"] = bool(gate["ok"])
    report["status"] = "verified" if gate["ok"] else "failed"
    if gate["ok"]:
        report["note"] = ("%d cue(s) from %d whisper segment(s) survived the "
                          "subtitle gate" % (len(cues), len(segments)))
    else:
        first = gate["fails"][0] if gate["fails"] else {"detail": "unknown"}
        report["note"] = ("transcribed, but the gate rejected it -- %s"
                          % first["detail"])
    return report


def _clean_version(text):
    """whisper-cli reports "whisper.cpp version: 1.9.5"; the digest already says
    whisper.cpp, so keep only the number."""
    return re.sub(r"(?i)^whisper\.cpp\s*(?:version)?:?\s*", "", str(text or "?")).strip()


def digest(report, width=88):
    """The text an agent reads instead of the JSON."""
    v = report["video"]
    e = report["engine"]
    version = _clean_version(e.get("version"))
    lines = ["CUTWRIGHT TRANSCRIBE / %s" % v["name"], "=" * min(width, 60)]
    dur = v.get("duration") or 0.0
    lines.append("duration   %d:%05.2f" % (int(dur // 60), dur % 60))
    if report.get("audio"):
        a = report["audio"]
        lines.append("audio      stream %d (%s), 16000 Hz mono, %.1fs of WAV"
                     % (a["stream_index"], a["language"], a["seconds"]))
    if e.get("wall_s"):
        lines.append("engine     %s %s, %d thread(s), %.1fs wall"
                     % (e["name"], version, e["threads"] or 0, e["wall_s"]))
    else:
        lines.append("engine     %s %s" % (e["name"], version))
    if e.get("cached"):
        lines.append("cache      whisper not re-run -- identical inputs, cached %s"
                     % (e.get("ran_at") or "earlier"))
    lines.append("model      %s" % (e.get("model") or "(missing)"))
    if report.get("counts"):
        c = report["counts"]
        lines.append("segments   %d -> %d cue(s), %d dropped as non-speech"
                     % (c["segments"], c["kept"], c["dropped_nonspeech"]))
    if report.get("metrics"):
        m = report["metrics"]
        lines.append("metrics    %.1f cues/min, mean %.2fs, %.0f wpm, %d words, "
                     "covers %.0f%%"
                     % (m["cues_per_min"], m["mean_dur"], m["wpm"], m["words"],
                        m["coverage"] * 100))
    checks = report.get("checks") or {}
    if checks:
        ok = sum(1 for value in checks.values() if value == "ok")
        lines.append("gate       %d of %d check(s) passed" % (ok, len(checks)))
    lines.append("status     %s -- %s" % (report["status"].upper(),
                                          report.get("note", "")))
    sig = report.get("signals") or {}
    if sig.get("checks"):
        lines.append("signals    " + " | ".join(
            "%s %s" % (c["name"], "ok" if c["ok"] else "WARN")
            for c in sig["checks"]))
        if sig.get("mean_logprob") is not None:
            lines.append("           mean ln(p) %.2f, mean token p %.3f"
                         % (sig["mean_logprob"], sig.get("mean_token_p") or 0.0))
    ref = report.get("reference")
    if ref:
        if ref.get("error"):
            lines.append("reference  could not be read: %s" % ref["error"])
        elif not ref.get("matched"):
            lines.append("reference  none of %d line(s) appear in %s -- that "
                         "reference is for a different film or edition"
                         % (ref["cues"], os.path.basename(ref.get("path") or "?")))
        else:
            lines.append("reference  %d of %d line(s) found in %s (%.0f%% match)"
                         % (ref["matched"], ref["cues"],
                            os.path.basename(ref.get("path") or "?"),
                            ref["rate"] * 100))
            if ref.get("offset_s") is not None:
                lines.append("           consistent offset %+.1fs (%d line(s) agree)"
                             % (ref["offset_s"], ref["offset_support"]))
            else:
                lines.append("           matched lines disagree on an offset -- "
                             "wording agrees, timing does not")
    for line in (report.get("fails") or []):
        lines.append("FAIL       %s" % line)
    for line in (report.get("warns") or []):
        lines.append("warn       %s" % line)
    for line in ((sig.get("warns")) or []):
        lines.append("warn       %s" % line)
    if report.get("cues_preview"):
        lines.append("")
        lines.append("first lines:")
        for c in report["cues_preview"]:
            lines.append("  %6.2f  %s" % (c["start"], c["text"][:70]))
    return "\n".join(lines).rstrip() + "\n"
