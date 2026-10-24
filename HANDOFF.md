# Handoff

State of the crossfade work at the pause on 2026-10-24, what is proven, what is
left, and how to pick it up. `LOG.md` is the running log, `REPORT.md` describes
the finished projects, `README.md` is the reference; this file is the one to
read first.

**The short version: the dissolve is solved and the answer is written down below.
It is not yet in `Project.to_xml()`.** The code emits the second-best shape, one
that Shotcut keeps but melt mis-times, so `projects\demo_cross` currently fails
its `gui_xfade` check. The next session's first job is a single edit to
`to_xml` (see "The edit to make"), then re-running the build.

## What the problem was

A crossfade that renders in melt did not render in Shotcut. `projects\demo_cross`
read magenta -- the outgoing colour alone -- in Shotcut's preview where melt
rendered a pink mix.

Cause, established by diffing what Shotcut writes on a real Ctrl+S: Shotcut sets
`disable=1` on V1's `frei0r.cairoblend` every time it saves. Every flat
multitrack dissolve -- a `luma` with `a_track=0`, an opacity ramp on the incoming
track -- depends on that blend running. So they all die the moment the project
is opened and saved, silently.

Consequence: the dissolve must not depend on any transition outside itself, and
must not be a multitrack transition at all, because a multitrack transition is
exactly the thing Shotcut reconsiders.

## The shape that works -- in both engines

A `.mlt` fragment, measured rather than guessed (`out\scratch\xfade6_probe.py`):

```xml
<producer id="head" in="0" out="14">          <!-- the incoming clip's first 15 -->
  <property name="length">15</property>
  <property name="eof">pause</property>
  <property name="resource">0xffffffff</property>
  <property name="mlt_service">color</property>
  <property name="mlt_image_format">rgba</property>
  <filter id="fade" in="0" out="14">
    <property name="alpha">0=0;14=1</property>       <!-- ramp, keyed to the
                                                          producer's own frames -->
    <property name="mlt_service">brightness</property>
  </filter>
</producer>
<playlist id="tail"><entry producer="producer1" in="34" out="48"/></playlist>
<playlist id="headpl"><entry producer="head" in="0" out="14"/></playlist>
<tractor id="dissolve1" in="0" out="14">
  <property name="shotcut:transition">lumaMix</property>
  <track producer="tail" hide="audio"/>          <!-- track 0: outgoing tail -->
  <track producer="headpl" hide="audio"/>        <!-- track 1: incoming head -->
  <transition id="inner_blend">
    <property name="a_track">0</property><property name="b_track">1</property>
    <property name="mlt_service">frei0r.cairoblend</property>
    <property name="always_active">1</property>
  </transition>
</tractor>
```

and V1 plays it as one entry between the two clip bodies:

```xml
<entry producer="producer1" in="0" out="33"/>    <!-- outgoing, less its tail -->
<entry producer="dissolve1" in="0" out="14"/>    <!-- the dissolve -->
<entry producer="producer2" in="15" out="33"/>   <!-- incoming, less its head -->
```

Three things make this work, and each of them was measured the hard way:

1. **The blend is inside the tractor.** Shotcut disables blends it finds on the
   multitrack, but it does not reach inside a producer it treats as a
   `lumaMix` transition. Nothing outside can turn this one off.
2. **The ramp is `brightness`'s `alpha`, keyed to the head producer's own
   frames**, not a window on the tractor. `luma` inside a nested tractor ramps
   over a length of its own choosing -- a 15-frame tractor with `in="0"
   out="14"`, with `in="34" out="48"`, with a `progressive=1` marker, and with
   both playlists padded to the parent's length all produced the *same* roughly
   ten-frame ramp in the wrong place (measurements in
   `out\scratch\luma_window_test.py`). An alpha ramp is not position-dependent
   at all: it says "frame 0 transparent, frame 14 opaque" and travels with the
   clip.
3. **Nothing depends on the timeline position of the tractor.** The tractor is
   15 frames long and sits wherever V1 puts it.

### The measurements

| where | frame | measured | wanted |
| --- | --- | --- | --- |
| melt (`x6_alpha_nested.mp4`) | 34 | (214, 0, 234) magenta | magenta |
| melt | 40 | (229, 55, 239) | 43% of the way |
| melt | 48 | (252, 255, 252) white | white |
| Shotcut preview, seek 0.25 | ~17 | (255, 0, 254) | magenta |
| Shotcut preview, seek 0.60 | ~40 | (253, 108, 253) | ~43% of the way |
| Shotcut preview, seek 0.85 | ~58 | (255, 255, 255) | white |

Green climbs 0, 1, 5, 27, 55, 79, 103, 128, 151, 178, 203, 228, 255 across the
window in the render: linear, the full 15 frames, no doubling.

After a real Ctrl+S, Shotcut's copy keeps the head producer's `brightness`
filter with its `alpha` keyframes (it adds `start=1`), the inner `cairoblend`
(it adds `version=0.1`), the tractor, and the three V1 entries. That is the
proof this is the shape the editor understands, rather than one it tolerates.

## What is in the tree right now

| file | state |
| --- | --- |
| `cutwright/mlt.py` | +545 lines. `crossfade()`, `dissolves()`, `v1_body()` rewritten around the nested tractor, `_main_tractor()` helper added, per-track and V1 length checks fixed, colour producers grown to cover the borrowed tail, frame-sample window narrowed. **Emits `luma` inside the tractor -- the shape that must be replaced.** |
| `cutwright/gui.py` | +184 lines. Block and picture detectors, `_picture_mean`, `check_crossfade`, `_powershell(save=...)`. |
| `cutwright/tools/shotcut_window.ps1` | `-Save` switch (`keybd_event` Ctrl+S), seek correction `0.3965`. |
| `cutwright/cli.py` | `crossfade` in the `--checks` help and in the build summary. |
| `projects/demo_cross/` | `plan.json`, plus `demo_cross.mlt`, `checks.json`, `digest.txt` **from an earlier `--checks gui_xfade` run against the flat layout**. `demo_cross.mlt` on disk still has the flat `luma`s, so all four want regenerating by a full build. `check\` is gitignored. |

`projects\demo_cross\checks.json` therefore records a failure that says nothing
about the current code: it is the flat layout, judged by the GUI.

## The edit to make

In `Project.to_xml()`, `cutwright/mlt.py` lines 730-754 -- the dissolve loop.
The spans it emits are right; only how the two sides are joined changes.

1. Instead of the incoming producer itself on the head track, emit a **clone** of
   it under `<dissolve>_in` (copy the element, change `id`, and change nothing
   else -- `length`, `eof`, `resource`, `mlt_image_format`, `shotcut:hash`,
   `shotcut:caption` all have to come along) carrying:
   ```xml
   <filter id="<dissolve>_fade" in="0" out="<frames-1>">
     <property name="alpha">0=0;<frames-1>=1</property>
     <property name="mlt_service">brightness</property>
   </filter>
   ```
   It has to be a clone: a filter on the producer would ramp the clip's own body
   on V1 as well. The side playlist for the head then points at the clone.
2. Replace the `luma` transition with `frei0r.cairoblend`, `a_track=0`,
   `b_track=1`, `always_active=1`, id `<dissolve>_blend`.
3. `check_xml()` (lines ~1124-1185) asserts "exactly one `luma` between tracks 0
   and 1". Change that to assert the inner blend between 0 and 1 *and* the
   `brightness` `alpha` filter on the head, since those are now what the shape
   means. A dissolve missing its ramp would otherwise pass.
4. `crossfade()`'s docstring (lines 443-479) describes the `luma` shape and the
   measurements behind it. Rewrite it -- it is the only prose in the code that
   says why, and it is now wrong.

Then regenerate and rebuild:

```
python -m cutwright build projects\demo_cross\plan.json
```

Expect `crossfade` (melt) and `gui_xfade` (Shotcut's preview) to pass, with the
picture going magenta -> pink -> white across the 15 frames and measuring
roughly 43% at frame 40 of 68. The rest of the checks should be unaffected by
the change; if `lengths` or `xml` complains, the clone or the V1 entries are
wrong.

## Tools for the next session

Everything below is in `out\scratch\` (gitignored, but cheap to rewrite from
this description):

- `xfade6_probe.py` -- builds the proven shape from scratch and prints frame
  colours. The reference; copy from it when editing `to_xml`.
- `luma_window_test.py` -- takes the failing file and rewrites the tractor in
  ten ways (`as_written`, `windowed`, `progressive`, `windowed_progressive`,
  `tractor_progressive`, `sides_progressive`, `timecode_window`,
  `double_window`, `absolute`, `absolute_padded`), printing the ramp for each.
  It is the evidence that `luma` cannot be positioned inside a nested tractor.
  Slow -- about 90 s for all variants -- so start it with `Start-Process ...
  -RedirectStandardOutput` and poll; do not run it in the foreground.
- `shoot.py <project> <fraction>...` -- opens a `.mlt` in Shotcut at a seek
  fraction and prints the mean of the picture block. This is how the GUI was
  measured.
- `rewrite_probe.py <project> <fraction>` -- opens, Ctrl+S, screenshots, then
  dumps what Shotcut wrote back. **Its save runs before the screenshot**, so the
  "Saved" toast covers the frame and the preview reads frame 0; use `shoot.py`
  to photograph and `rewrite_probe.py` only to inspect the rewrite.
- `seek_cal.py` -- the calibration behind `0.3965`: seeks of 0.25 / 0.50 / 0.75
  land on 0.233 / 0.484 / 0.736 of the timeline.

## Gotchas worth keeping

- **Shotcut's seek is about 0.016 short**, measured over three fractions. The
  correction lives in `shotcut_window.ps1`; do not re-derive it per test.
- **Do not write a file with `Set-Content` or `Out-File`** -- a BOM got into
  `mlt.py` that way once and made a clean diff look dirty. Use
  `[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false)))`.
- **`git commit -m` from PowerShell mangles long messages.** Write the message
  to a file the same way and use `git commit -F`, then confirm with
  `git log -1 --format=%B`.
- **Editor writes over ~6000 characters time out.** Split into chunks of three
  thousand or fewer.
- **`gui_xfade` and `gui` report `not_run`, never pass**, when there is no
  interactive desktop. That is deliberate: a check that cannot be made must not
  look like one that was.
- **A `luma` with no window ramps as if it holds the whole timeline**; that is
  why the first nested attempt looked like an 8-frame-early 2x-speed ramp. It is
  not worth more time -- the alpha ramp sidesteps the question.

## Order of work from here

1. The edit above, then a full build of `projects\demo_cross`, all checks green.
2. A real Ctrl+S of `demo_cross.mlt` and a `shoot.py` either side of the middle,
   recorded in `PROVENANCE.md` beside the other Shotcut-saved copies.
3. `REPORT.md` section for the project, `README.md` check table (nine checks
   now), `LOG.md` entries, `PROVENANCE.md` hashes.
4. Commit and push; tag with a name the user approves (`v0.3.3-xfade` was the
   suggestion, and nothing has been tagged since `v0.3.2`).
5. Then the milestone chain the summary lays out: music dipping under voice ->
   J/L cuts -> per-line captions -> the planner (bundle plus JSON-schema
   validation) -> an end-to-end run on a short clip -> `REPORT.md`.

## Repo state at the pause

Branch `main`, remote `origin https://github.com/altzotify-cell/cutwright.git`.
Last commit before this handoff: `a87f4bf An eighth check, which looks at
Shotcut's own preview`. Nothing pushed, nothing tagged. `shotcut\`, `models\`,
`bin\`, `testclips\`, `out\` and every `projects\*\check\` are gitignored: the
first four are 1.2 GB of other people's binaries and footage, described in
`PROVENANCE.md`.

