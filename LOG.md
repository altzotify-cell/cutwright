# Log

Newest last. A timestamp is when the line was written, not when the work began;
`~` marks a time reconstructed from the transcript rather than read off a clock.
Everything before 2026-10-24 has no clock on it -- the log starts with the fade.

## 2026-10-24

```
~11:20  fade      wrote Project.set_fade / _fade_filters in cutwright/mlt.py:
                  brightness level 0->1 and volume level -60dB->0, both animated,
                  both on the tractor (producer-level filters do nothing here).
~11:35  fade      first demo_fade build: 4 checks pass, fade check fails. Head
                  measured 26 luma against 129 in the middle.
~11:50  probe     four spellings of the keyframe positions (relative, absolute,
                  clock-time, tractor vs playlist) all behaved identically, and
                  the "fade" appeared to start black 35 frames before it should.
~12:05  profile   cause found: melt ignores the .mlt's own <profile> and renders
                  at 25 fps unless -profile is passed. Proven with a hard cut:
                  a cut at source frame 377 showed up at render frame 63 (25 fps
                  x 0.52 s) instead of 77. Profile.write_file() now writes a
                  .prof beside every render and _melt_render passes -profile.
~12:20  profile   re-probed with -profile: the cut moved to frame 76 and the
                  "black tail" turned out to be the source's own scene change.
                  Nothing was wrong with the filter. All four old checks still
                  pass on demo_cuts, and demo_cuts.mlt is byte-identical
                  (4234355f...), so the fix changed renders, not the writer.
~12:40  fade      rewrote check_fade to measure against a control: the same
                  project re-rendered by this writer with the fade removed, then
                  divided frame by frame. The old yardstick (middle of the
                  timeline) read a brighter shot as "full brightness".
12:46  fade       demo_fade build: all five checks pass. Level 0.00 at frame 0,
                  0.28 half way into the fade in, 0.99 at frame 24, 1.00 at 279,
                  0.45 half way into the fade out, 0.01 at the last frame,
                  0.99-1.00 inside the body; sound -76.0 dB at the head against
                  -23.5 dB in the middle.
12:49  docs      README (five checks, fade section, the -profile finding),
                  PROVENANCE (demo_fade hash, and the note that demo_cuts' hash
                  did not move), REPORT.md and this log created.
~12:55 titles    titles were written into V2 and never appeared: melt 7.41 here
                  ignores a blend's a_track=0 for any track above V1 -- it
                  composites onto the *background* instead of the running
                  picture. Shotcut writes a_track=0 in its own files; this writer
                  had copied it. Three-track probe (black / green / red):
                  composite a=0 b=2 changed nothing, a=1 b=2 put red over green
                  in the requested half. Centre-band YMAX 195 -> 250 on the demo.
~13:05 titles    first control that "removed the titles" removed V2 with them:
                  cairo then moved every frame by 33 dB and melt skipped a blend
                  whose b-frame never arrived, which is louder than the defect
                  being looked for. Replaced with no_title_text: the same
                  producer, the same track, the same frames, one <filter> left
                  out. Frame 25 went to inf; frames 96/190/258 still read 32-36
                  dB.
~13:20 titles    that residue was the codec, not the text: under H.264 a bright
                  title is carried a little way into the frames after it through
                  inter prediction. check_titles now renders both sides itself at
                  crf=0 (about 8 MB and a few seconds a side); the quiet frames
                  are then bit-identical. The render check's own proof stays
                  lossy at 270 wide.
13:32  titles    demo_title build: all six checks pass -- band 23.3 / 20.0 / 20.6
                  dB against 29.5 / 26.2 / 26.8 dB whole-frame at the first,
                  middle and last frame of title 1, 23.8 / 26.3 / 21.3 against
                  29.9 / 32.4 / 27.5 dB for title 2, and frames 25, 96, 190, 258
                  identical to the control.
13:32  docs      README (six checks, Titles section, the a_track finding, plan
                  schema), REPORT (demo_title section and row), this log.
13:58  titles    cairoblend now defaults a_track to b_track - 1, but the audio
                  `mix` transitions pass a_track=0 explicitly: audio sums into
                  the background frame (Shotcut writes it that way) and only the
                  picture needs the running track as its a-frame. The blanket
                  default had rewritten the A1 mix line too and moved both older
                  demos' hashes for no measured gain; rebuilt at this commit,
                  demo_cuts and demo_fade are byte-identical again. demo_title
                  was rebuilt twice and is byte-identical to itself.
```
