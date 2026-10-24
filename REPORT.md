# Report

What is built, what each demo project is, and exactly what to look for when you
open it. `LOG.md` is the timestamped working log; `README.md` is the reference.

As of 2026-10-24: **fade in / fade out and titles are built and passing seven
checks.** The titles were re-done after the Shotcut GUI showed none of them: they
are track filters on V1 now, not clips on a V2 track, and a `shotcut` check
renders the file after the rewrite that hid them. Transition, music-dipping, the
planner and the end-to-end run are not.

## Demo projects

Each one is a folder under `projects\`. Open the `.mlt` in Shotcut by
`File > Open File`. The `check\` folder beside it holds the proof render, the
frames it compared and the profile it rendered at; `checks.json` and
`digest.txt` hold the numbers. `check\` is not in git -- re-run
`python -m cutwright build projects\<name>\plan.json` to recreate it.

### `projects\demo_cuts\demo_cuts.mlt` -- three cuts, no fade

Three clips from `testclips\part1_1_60-120.mp4`, 311 frames, 10.377 s, cut at
0.0-4.0 s, 34.2-37.6 s and 47.2-50.2 s of the source.

What to look for:

1. **V1 has three clips** at 0:00, 4:00 and 7:24 (the ruler counts frames at
   30 fps, so 4.004 s = `00:00:04.00`). Each clip carries its label.
2. **A1 has the same three clips with waveforms** -- audio is on its own track,
   `hide="video"` on A1 and `hide="audio"` on V1, so nothing plays twice.
3. **The ruler reads `00:00:10.377`** at the end, and the playhead stops on the
   last frame (310) rather than on 311.
4. **No fade**: frame 0 is picture, not black.
5. Playback: three picture jumps exactly where the clip ends are, no frozen
   frame at any clip start (that symptom is the double-trim bug in the README),
   and the sound matches the picture.

Verified by hand on 2026-10-23: three clips on V1 with captions, three on A1 with
captions and waveforms, ruler `00:00:10.377`.

### `projects\demo_fade\demo_fade.mlt` -- the same three cuts, fading in and out

Identical cuts under a **0.8 s fade in** (24 frames) and a **1.0 s fade out**
(30 frames), picture and sound together. 311 frames, 10.377 s.

What to look for:

1. **The first frame is black**, and the picture lifts smoothly to full by
   frame 24 (0:00:00.80). It should not pop: no jump at the start, no grey
   starting point.
2. **The last frame is black**, and the picture falls from full at frame 280
   (about 0:00:09.35) to black on frame 310. Nothing should be visibly dark
   before 9.35 s -- the old bug dimmed the timeline 35 frames early, which is
   what a fade-at-the-wrong-fps looks like.
3. **The sound follows the picture**: the first moment is silent, it comes up
   with the picture, and it drops away at the end.
4. **The middle of the timeline is untouched** -- between 0.8 s and 9.35 s the
   picture is exactly as bright as `demo_cuts` at the same frame.
5. **Nothing else changed**: V1 still has three clips with labels, A1 three with
   waveforms, ruler still `00:00:10.377`. The fade is two filters on the
   program, not something baked into the clips, so every clip is still trimmable.

Not yet opened by hand. The checks measure it -- 0.00 on frame 0, 0.28 half way
into the fade in, 0.99 on frame 24, 1.00 on frame 279, 0.45 half way into the
fade out, 0.01 on the last frame, 0.99-1.00 at three points inside the body,
sound -76.0 dB at the head against -23.5 dB in the middle -- but "Shotcut shows
the ramp where I expect it" is the one thing only opening it can prove.

### `projects\demo_title\demo_title.mlt` -- the same three cuts, fading, with two titles

The same cuts and the same 0.8 s / 1.0 s fade, plus two titles drawn on **V1**:
`the three cuts` at 72 px in the middle band for 0.9-3.2 s (frames 27-95), and
`the word is meat` at 48 px in the lower band for 6.4-8.6 s (frames 192-257).
311 frames, 10.377 s. There is no third track: each title is one `dynamictext`
filter on the picture track, with an `in`/`out` window.

What to look for:

1. **V1 has three clips and two track filters.** Select V1 in the timeline (or
   press the track-head "Filters" button) and the Filters panel lists
   `Text: Simple` twice, once for each title, with the times the plan asked for.
2. **The first title sits over the opening shot** (0.9 s in, once the fade has
   finished opening), centred vertically, white with a black outline so it reads
   over the picture. The clip under it is untouched and still trimmable.
3. **Between the titles nothing is drawn.** From 3.2 s to 6.4 s there is no
   filter window, and the frame there is identical to the same frame of the same
   project with the text left off.
4. **The second title crosses a cut.** It starts at 6.4 s, inside the second clip,
   and the cut to the third clip is at 7.4 s (frame 222), so the same text stays
   on screen across the cut rather than being tied to a clip.
5. **The envelope at the ends is respected**: the first title appears after the
   fade in has finished, and both titles are dimmed by the fade like the picture,
   because the fade is two filters on the program and the text is on the track
   under it.
6. **The ruler still reads `00:00:10.377`** and A1 still holds the three clips
   with waveforms: the titles changed nothing about the edit.
7. Playback: the text does not flicker or slide, it holds still in its band, and
   it is gone on the frame after its out point.

This is the project that failed in the GUI. It used to carry the titles as clips
on a V2 track, blended down onto V1 with `a_track=1`; melt drew them and the six
checks passed, while Shotcut's preview showed the bare shot -- it rebuilds that
blend with `a_track=0`, which lands the composite in the background frame, under
V1. `demo_title_saved.mlt`, in the same folder, is Shotcut's own save of that
version and is kept as the evidence. What the checks measure now: at the first,
middle and last frame of title 1 the frame changes by 29.5 / 26.2 / 26.8 dB
against the same frame without the text, with 23.3 / 20.0 / 20.6 dB inside the
middle band and less elsewhere; title 2 reads 29.9 / 32.4 / 27.5 dB whole-frame
with 23.8 / 26.3 / 21.3 dB in the lower band; frames 25, 96, 190 and 258 -- just
outside both windows -- are **identical** to the control render; and the
`shotcut` check re-renders the project after that rewrite and finds the same
text in the same bands.

## Check results, as recorded in each `checks.json`

| project | xml | effects | lengths | render | fade | titles | shotcut |
|---|---|---|---|---|---|---|---|
| `demo_cuts` | 83 elements, 11 ids, 11 refs | 4 names | 311 f = 120+102+89 | 30.6 / 34.5 / 31.5 dB, control 13.5 dB | -- (no fade in the plan) | -- (no titles in the plan) | -- (no titles in the plan) |
| `demo_fade` | 99 elements, 15 ids, 11 refs | 6 names (+ brightness, volume) | 311 f = 120+102+89 | 30.7 / 34.4 / 31.5 dB, control 13.5 dB | level 0.00 / 0.28 / 0.99 and 1.00 / 0.45 / 0.01, body 0.99-1.00 | -- (no titles in the plan) | -- (no titles in the plan) |
| `demo_title` | 127 elements, 17 ids, 11 refs | 7 names (+ dynamictext, color, frei0r.cairoblend, mix) | 311 f = 120+102+89; A1 311, Background 311, V1 311 | 26.0 / 34.4 / 31.6 dB, control 13.4 dB | level 0.00 / 0.28 / 0.99 and 1.00 / 0.45 / 0.00, body 0.99-1.00 | band 23.3 / 20.0 / 20.6 dB against 29.5 / 26.2 / 26.8 dB whole-frame, identical outside the window | the rewrite changes no blend; title 1 frame 61 band 20.0 / frame 26.2 dB, title 2 frame 224 band 26.3 / frame 32.4 dB |

The `render` numbers are PSNR against the same frames put through the same
pipeline: 30-35 dB for a correct clip, 13.5 dB for a deliberately mismatched
frame, threshold 24 dB. `demo_title` reads 26.0 dB on its first sample because
that frame (60, 2.0 s) carries title 1 -- white text over the shot is a real
difference from the source, and this check counts it as one. The `titles` check is
the one that judges that text: it compares the frame against the same frame with
the text left off, so there the text is the signal and not the error.

## Open decisions (waiting on you)

* **`LICENSE`** -- none in the repo yet. MIT suggested: the code is mine, the
  vendored files under `vendor\` are not, and `PROVENANCE.md` already says where
  they came from.
* **`vendor\` in git** -- 89 files, 0.68 MB, committed in the first commit. They
  are a copy of code from the two original projects, kept so the fork can be
  audited. Whether that copy belongs in a public repo is your call; if not,
  `git rm -r --cached vendor` (it stays on disk, `MANIFEST.sha256` still
  verifies it) and `PROVENANCE.md` says where to get it.
