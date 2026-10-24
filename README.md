# Cutwright

Agent control of a Desktop video-editing fork: perception first, editing second.

The half that writes an edit today is `build`: a JSON list of cuts goes in, a
Shotcut `.mlt` project comes out, and four checks prove the file is what it
claims to be -- the XML resolves, every effect name exists in the installed
Shotcut, the track lengths add up, and a small render really shows the frames
the edit asked for.

This is a **self-contained fork**. All copied code and text lives in `vendor/`
with a SHA256 manifest. Footage is never copied -- source files are referenced
by absolute path and read only.

## What is and is not in this repo

Code, docs and one demo project are committed (108 files, 0.9 MB). The three
things Cutwright wraps are **not**, because together they are 1.2 GB and none of
them is mine to redistribute:

| absent from git | size (MiB) | published at |
|---|---|---|
| `shotcut\Shotcut\` -- Shotcut 26.9.27, provides `melt.exe` 7.41.0 | 522 MB | `github.com/mltframework/shotcut/releases`, v26.9.27 win64 zip |
| `models\ggml-small.en.bin` -- whisper small.en, f16 | 465 MB | `huggingface.co/ggerganov/whisper.cpp` |
| `bin\` -- whisper.cpp 1.9.5 build, plus both downloaded zips | 234 MB | `github.com/ggml-org/whisper.cpp/releases`, build `b5454` |
| `testclips\` -- the footage the demo cuts from | 35 MB | not mine to publish; use your own |

`PROVENANCE.md` has the URL, byte size and sha256 each one must match. Unpack
them at the paths above, relative to this folder: `.gitignore` only keeps them
out of git, nothing in the code assumes a different location.
`python -m cutwright doctor` lists what is missing and what stops working
without it. The demo project is committed without its `check\` folder (proof
renders, 5 MB); `build` recreates those.

## The one invariant

Every write goes through `cutwright/guard.py`. It refuses to write:

* anywhere inside either original project folder
* anywhere outside this folder

That is enforced in one place, tested by `doctor`, and nothing in the codebase
opens a file for writing any other way.

```
C:\Users\user\Downloads\RecapStudio_v2_ui_videopad   read only
C:\Users\user\Downloads\videopad                    read only
C:\Users\user\Desktop\Cutwright\                     the only writable place
```

## Layout

```
Cutwright\
  vendor\           copied code + text from both projects (0.68 MB, 89 files)
    MANIFEST.sha256 every file's hash
  bin\whisper\      whisper.cpp 1.9.5 binaries        (not in git, see PROVENANCE.md)
  bin\_dl\          the downloaded zips, kept so their hashes stay re-checkable
  models\           ggml weights, ggml-small.en.bin    (not in git, 465 MiB)
  shotcut\Shotcut\  Shotcut 26.9.27 portable, incl. melt.exe 7.41.0   (not in git)
  testclips\        short samples cut from real footage for tests      (not in git)
  cutwright\        the new tool, standard library only
    guard.py        write invariant, hashing, provenance
    probe.py        ffprobe/ffmpeg, stream discovery, subtitle extraction
    subs.py         the subtitle gate: find a transcript, then prove it is usable
    moments.py      transcript -> beats -> ranked candidate moments
    frames.py       frame verification: grade picks against pictures
    transcribe.py   whisper.cpp fallback: produce a transcript, gate it too
    mlt.py          plan -> Shotcut .mlt, then the four checks on the file
    cli.py          doctor / probe / subs / moments / verify / transcribe / build
  projects\<name>\   plan.json + <name>.mlt + checks.json + digest.txt + check\
  out\<video>\      per-video analysis output
  out\cache\        melt's filter/transition/producer lists, keyed to that exe
```

## What works today

**`subs` -- the subtitle gate.** Walks a trust ladder (`your file` > `sidecar`
> `embedded text track` > `needs_whisper`) and validates every candidate before
anything downstream is allowed to use it:

| check | catches |
|---|---|
| `has_cues`, `cue_durations`, `monotonic` | empty, inverted or shuffled timing |
| `in_range`, `covers_end` | subtitles for a **different cut or film** |
| `script_latin` | the Spanish or Japanese track |
| `no_mojibake` | cp1251 read as UTF-8 |
| `no_drawing_commands` | ASS vector art leaking in as text |
| `cue_density`, `cue_overlap`, `cue_length` | sign-layer spam, machine output |
| `styling`, `source_cleanliness` | decorative layers, markup pollution |

It also does real cleanup that `recap.py` does not: it keeps the native `.ass`
instead of the flattened `.srt`, then drops vector drawings (`\p1`) and
non-dialogue styles (`Signs`, `ED Translation`, ...). On a real fansub episode
that turned 3024 raw cues into 357 usable dialogue cues.

No gate pass means no transcript. It stops and asks rather than quietly
substituting Whisper.

**`moments` -- transcript to candidate moments.** Groups cues into beats on
silence and length, scores them on dramatic language density, and picks a
shortlist that covers the whole runtime instead of 12 deaths from the last five
minutes. Emits `moments.json` plus a plain-text digest meant to be read by an
agent, mirroring recap.py's `ALL_EPISODES_for_claude.txt`.

Every candidate is `status: unverified` with an empty `expected` field and three
`frames[]` timestamps. That is the seam where perception takes over: the
transcript says what is *said*, never what is *seen*.

**`verify` -- frame verification.** The agent writes `expected` in words; the
machine measures what ffmpeg can prove without a model: shot changes inside the
window, whether the in-point lands on a cut or mid-shot, and mean luma from an
8x8 grey probe (which tells a flat black frame apart from a dark scene). Every
pick is graded **verified / retimed / replaced / unverified**, and only a
contradiction demotes: a busy window is a warning, not an error. A separate
`review.json` lets the agent overrule the machine after actually opening the
JPEGs, and the machine's original call is kept in `frames.json` beside it.

**`transcribe` -- the whisper fallback.** When the ladder ends in
`needs_whisper`, this runs whisper.cpp on a 16 kHz mono WAV and puts the result
through **the same gate** a downloaded `.srt` must pass. Three signals a human
subtitle file cannot offer are added as warnings, all derived from the per-token
probabilities `-ojf` writes (whisper.cpp 1.9.5 has no segment-level
`avg_logprob` or `no_speech_prob` anywhere in its JSON, so claiming them would be
a vacuous pass): decoder confidence = mean `ln(p)` over each segment's tokens,
weak-token share (`p < 0.30`), and whisper's own repetition tripwire
(`compression_ratio`, recomputed with zlib). If a run produces no probabilities
at all, `signal_data` warns instead of reporting three greens. With `--subs` it
can also cross-check the wording against a reference subtitle file: matching
lines plus a consistent time delta prove the transcript is the dialogue really in
the clip, and the delta says where the clip sits in the longer film.

**Transcribing is cached.** `out\<video>\whisper_cache.json` keys on the clip's
size and mtime, its duration, the language and the model/binary stamps, so a
second `transcribe` on the same file reuses the transcript in well under a
second instead of re-running the model (measured: 44.8 s -> 0.4 s, byte-identical
`.srt`). Change the clip, the language or the model and it misses; `--fresh`
ignores the cache outright.

**`build` -- plan to Shotcut project.** Reads a plan (an ordered list of clips
with in/out points), writes a `.mlt` Shotcut can open as an editable timeline,
and then checks the file it just wrote:

| check | proves |
|---|---|
| `xml` | it parses, ids are unique, every `producer=`/`track=` reference resolves, transition track numbers are in range, and the Shotcut/MLT version it records is the installed one |
| `effects` | every `mlt_service` is a name `melt -query` reports -- nothing invented (674 filters / 59 transitions / 42 producers on this build) |
| `lengths` | every track is exactly as long as the tractor, no entry overruns its producer, and the clip lengths add up to the timeline |
| `render` | a small render really shows the source frames the edit claims: PSNR against the same frames rendered through the same pipeline, plus the audio level per clip |

The render check compares against a **reference rendered by this same writer**
rather than against the source decoded by ffmpeg. Measured on a clip that was
demonstrably at the right frames, ffmpeg's decode and scale agreed with melt to
45 dB on chroma but only 22.8 dB on luma -- two pipelines disagreeing, not
footage. Comparing like with like, a correct clip scores 32-37 dB and a
deliberately mismatched frame scores 13 dB, so the 24 dB threshold has room on
both sides. Each sample is scored at offsets of 0, +-1 and +-2 frames so a
rounding disagreement fails nothing that is otherwise correct.

The file is a background colour producer, a **V1** video playlist and an **A1**
audio playlist holding the same producers, `hide="audio"` on V1 and
`hide="video"` on A1 so nothing plays twice, and the per-track `mix`/`blend`
transitions Shotcut writes. Frame counts are integers throughout -- no timecode
strings, nothing to round twice. Shotcut 26.9.27 and MLT 7.41.0 are recorded in
the root `title` and in `cutwright:` properties, and `xml` fails if either
disagrees with the binaries on disk.

Two melt behaviours are worth knowing, both measured rather than guessed:

* A single pass that encodes a project **with audio** reaches the last frame and
  then never exits (`melt` sits at 99% forever). melt's own serialized XML does
  the same, so it is the build, not the file. Hence two passes: picture to H.264,
  audio to PCM, both of which finish in seconds.
* A playlist entry seeks *relative to its producer's* `in=`. Setting a producer's
  `in=` to the trim start double-counts it: clip 2 started at source frame 1415
  and landed at 2830, past the end, frozen on the last frame. Producers now span
  the whole file and the entries carry the trim.

## Testing rules

Never test on a full episode or a long file. Every test uses a short sample cut
out of the footage first, because a 24-minute file turns a 30-second check into a
30-minute wait and a 500 MB WAV.

```
testclips\          short samples cut from real footage (the only media in this fork)
out\                analysis output, per video
```

* **30-90 seconds per clip, hard cap 2 minutes.** Cut with stream copy so it is
  instant and lossless and the sample is bit-identical to the source range:
  `ffmpeg -ss 00:05:00 -to 00:05:01:30 -i "<source>" -c copy -avoid_negative_ts make_zero "testclips\<name>.mp4"`
* **Pick samples that cover what is being tested**, not just the first minute:
  one clip with dialogue, one silent action clip, one with a hard cut on a known
  timestamp. A test that only sees dialogue proves nothing about shot detection.
* **Never write into the original folders.** Samples are cut *from* the
  originals and saved *into* `testclips\`; the guard enforces this.
* **If a test would take more than about 2 minutes, say the estimate and ask**
  before running it. Measured: whisper runs at ~0.75x the clip's length on 8 CPU
  threads, so a 60 s clip is ~45-50 s and a 90 s clip is ~70 s.
* **Cache anything slow.** A transcript is written once and reused; re-running
  `transcribe` on the same file must not re-run whisper.
* **Renders are the slow part of `build`.** melt decodes 1080x1920 at ~15 fps
  here, so the proof render costs about the timeline's length: 11.9 s for a
  10.4 s edit, including three reference windows and the frame comparisons. The
  filter/transition/producer lists are cached in `out\cache\` keyed to the exe's
  size and mtime, because asking melt three times costs ~30 s on its own.
* **Full-length runs only when explicitly asked for.**

## Usage

```powershell
cd C:\Users\user\Desktop\Cutwright
python -m cutwright doctor
python -m cutwright probe "C:\path\to\film.mp4"
python -m cutwright subs "C:\path\to\film.mp4"
python -m cutwright moments "C:\path\to\film.mp4" --top 10
python -m cutwright moments "C:\path\to\film.mp4" --subs "C:\path\to\film.srt"
python -m cutwright verify  "C:\path\to\film.mp4"
python -m cutwright transcribe "C:\path\to\clip.mp4" --subs "C:\path\to\film.srt"
python -m cutwright transcribe "C:\path\to\clip.mp4" --fresh   # ignore the cache
python -m cutwright build   "projects\demo_cuts\plan.json"
python -m cutwright build   "projects\demo_cuts\plan.json" --width 320 --crf 30
python -m cutwright build   "projects\demo_cuts\plan.json" --checks xml,effects
```

A plan is just the cuts, in order, in seconds (`out` exclusive):

```json
{
  "name": "demo_cuts",
  "title": "three cuts from one test clip",
  "clips": [
    {"source": "testclips/part1_1_60-120.mp4", "in": 0.0,  "out": 4.0,  "label": "crash into the wall"},
    {"source": "testclips/part1_1_60-120.mp4", "in": 34.2, "out": 37.6, "label": "he takes a bite"},
    {"source": "testclips/part1_1_60-120.mp4", "in": 47.2, "out": 50.2, "label": "the word is meat"}
  ]
}
```

`source` is resolved against the fork root first, then against the plan's own
folder. `build` writes `<name>.mlt`, `checks.json` and `digest.txt` into
`projects\<name>\`, keeps the proof render and its frames in `check\`, and exits
5 if any check fails.

Standard library only. ffmpeg and ffprobe must be on PATH (they already are).
`transcribe` additionally needs `bin\whisper\Release\whisper-cli.exe` and
`models\ggml-small.en.bin`; without them it prints the exact install steps and
exits 3 instead of guessing.

## Not built yet

| piece | status |
|---|---|
| fade in / out | not built -- `brightness` and `volume` are both confirmed present for this |
| title text | not built -- `dynamictext`, `qtext` and `text` are all confirmed present |
| transition between two clips | not built -- `luma`, `mix` and `composite` are all confirmed present |
| music dipping under the voice | not built -- a second audio track with keyframed `volume` |

Nothing gets installed without approval. Shotcut was installed on explicit
approval; it is only unpacked, never launched as a GUI. `build` has now written
`projects\demo_cuts\demo_cuts.mlt`, and all four checks pass on it -- but the
GUI has not opened that file yet, so "Shotcut opens it as an editable timeline"
is still unproven. What is proven is narrower and checkable: melt renders it to
the right frames and the right audio, the XML is well formed, and every effect
name in it exists in this Shotcut.
