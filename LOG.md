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
```
