# Handoff

**Updated 2026-10-26. Read this top section first; the 2026-10-24 crossfade handoff
is kept unchanged below it.**

## Status of this update

Nothing in the code was changed. This section is a plan, written before any work
starts, so that it survives running out of free-plan credits. Any agent (Cline,
Claude Code, a chat model) can pick it up from here.

Two limits on how far to trust it:

- The consultant session (Claude, chat, free plan) had **no network and no way to
  clone repos**. Every statement below about `shotcut-mcp`, `cli-anything-shotcut`,
  NarratoAI and RecapStudio comes from the owner's own notes, not
  from reading those repos. Phase 1 exists to fix that.
- Licences were **not checked**. "Apache 2.0, so copying is clean" is the owner's
  note about cli-anything-shotcut and is unverified. Shotcut itself is GPL. Do not
  copy code out of any repo until its LICENSE file has been read (Phase 1).

## What the owner wants (restated from the 2026-10-26 prompt)

1. **Stop hand-building editor controls.** Shotcut's CLI wrappers already implement
   clips, trims, splits, moves, transitions, text overlays and filters, rendered
   through `melt` as a subprocess and emitting native `.mlt` files that open in the
   Shotcut GUI. Copy their approach instead of designing each control in Cutwright.
   Sources named: `NoBanks/shotcut-mcp`, `mltframework/shotcut`, and the
   `cli-anything-shotcut` package.
2. **Integrate RecapStudio fully** (`github.com/altzotify-cell/RecapStudio`) so the
   agent calls its tools directly. Today a human pastes `PASTE_THIS_TO_CLAUDE_*.txt`
   into a chat; the agent should replace that step.
3. **Better perception than NarratoAI.** Today the AI reads transcript/subtitles,
   emits a JSON, a script runs ffmpeg for screenshots where the AI was unsure. Two
   blind spots to close:
   - *Silent stretches*: no dialogue means no signal, so nothing gets tagged.
   - *Confident-but-wrong*: the transcript says "let's go to the beach", the scene
     shows a spaceship, and no uncertainty tag fires.
   Proposed fix: **coverage sheets**. Cutwright already detects shot changes with
   ffmpeg, so drop one contact sheet at every shot boundary that has no overlapping
   dialogue, plus a floor of one per few minutes.
4. **Keep verification.** Every feature added must come with a check. That is what
   distinguishes Cutwright from the tools it borrows from.
5. Reference repo also named: `linyqh/NarratoAI`.

## Borrow list (from the owner's notes; effort estimates are theirs)

From `cli-anything-shotcut`:

| Borrow | Gives Cutwright | Effort |
|---|---|---|
| Ducking + volume envelopes | Music under voice, the biggest gap | Low: copy the MLT XML shape, wrap in dB checks |
| Transitions (add/remove/set; luma/mix/composite) | Crossfades, dissolves | Low-med |
| Blend modes / opacity / PIP | Overlays, watermarks, insets | Low |
| Preview bundles, live preview, trajectory | Agent can see the rough cut | Medium |
| SKILL.md format + `npx skills install` | One-command adoption by any agent | Low |
| `--json` on everything | Machine-readable output | Low |
| Undo/redo session model | Try, check, undo, retry | Medium, or skip |

From NarratoAI:

| Borrow | Gives Cutwright | Effort |
|---|---|---|
| Sonilo BGM/SFX API | Royalty-free music and effects | Low-med |
| Tavily plot-search pre-step | More accurate scripts | Low |
| Subtitle mask (percent-positioned blur) | Recaps over hardsubbed footage | Medium |
| Keyframe batching (interval/batch/concurrency) | Coverage sheets at scale | Low |
| TwelveLabs Pegasus option | Motion-aware understanding (fights) | Low, needs key |
| Gemini Flash Lite / SiliconFlow Qwen-VL | Cheap hosted captioning | Config only |

## Consultant's adjustments to that list

- **Do not borrow transitions or envelopes before the crossfade edit lands.** The
  2026-10-24 work found that Shotcut sets `disable=1` on V1's `frei0r.cairoblend`
  on every Ctrl+S, silently killing any flat multitrack `luma`/opacity dissolve.
  Borrowed transitions will very likely be exactly that shape. Every borrowed
  transition, blend or envelope must survive a real Ctrl+S and pass `gui_xfade`
  or an equivalent, or it is not borrowed, only imported.
- **Skip undo/redo.** A plan is JSON and `build` regenerates the project; that is
  already a clean retry loop.
- **Network-dependent borrows (Sonilo, Tavily, TwelveLabs, hosted captioners) are
  optional and default off.** The README says Cutwright is standard library only,
  and the owner is credit-sensitive. Put them behind a config flag and a separate
  module so the core stays dependency-free.
- **Confident-but-wrong needs one more mechanism than silent coverage.** Coverage
  sheets at shot boundaries catch silence. To catch the beach/spaceship case, also
  sample a small, fixed fraction of dialogue beats that were *not* flagged and
  attach a sheet to them. This is the consultant's suggestion, not the owner's;
  keep it only if it proves cheap.
- **Define "integrate fully" before building it.** Cheapest version: RecapStudio's
  numbered steps become Cutwright subcommands with `--json`, and the agent calls the
  CLI. An MCP server can wrap that later. Do not start with the MCP server.

## Ground rules for every step

1. Each step is independently shippable. Finish, run checks, commit, then stop or go on.
2. Every write goes through `cutwright/guard.py`. No exceptions, including RecapStudio
   integration code.
3. A borrowed feature gets a Cutwright check before it counts as done.
4. Read the LICENSE of a source repo before copying from it. If unclear, copy the
   MLT XML *shape* (a file format) and write the code fresh.
5. Record every borrowed file, its repo, commit and licence in `PROVENANCE.md`.
6. Gotchas from the old handoff still apply (no BOM, `git commit -F`, small editor
   writes, `not_run` is not `pass`).

## Communication protocol (agent <-> consultant)

Three files, three jobs. Do not merge them.

| file | job | changes |
|---|---|---|
| `HANDOFF.md` | The plan, the rules, and a short **Current status** block. The source of truth for "where are we". | Rarely; the status block after each breakthrough |
| `LOG.md` (exists) | Running log. One dated entry per breakthrough *and* per dead end. | Often, append-only |
| `COMMS.md` (new) | The channel between agent and consultant: questions, blockers, review requests, answers. | Often, append-only |

Why `COMMS.md` is separate from `HANDOFF.md`: a channel grows every time someone
speaks, and the consultant has to re-read whatever file it is given. Mixing them
buries the plan under chatter and makes the one file everyone must read the
longest. Keep the plan short; let the channel be long.

### How messages travel

The consultant (Claude, in a chat) cannot write to GitHub or touch the repo. The
owner is the relay.

- **Agent to consultant:** the agent appends an entry to `COMMS.md`, commits and
  **pushes**. The owner pastes into the consultant chat either the entry text
  (always works) or the raw link to it, on its own line with a space after it.
  Link to a specific commit, not `main`, so the text cannot change or lag.
- **Consultant to agent:** the consultant replies in chat in the same entry
  format. The owner pastes it at the end of `COMMS.md` (or tells the agent to)
  and commits.

Limits to know about (as of 2026-10-26, not all tested):

- The consultant's fetch tool only opens URLs it was given cleanly in a message
  or found by search. A first test on the RecapStudio URL failed: the link was
  stuck to the next word in the message, and a search did not find the repo, so it
  may be private. **A private repo cannot be fetched at all. Paste the text.**
- Raw GitHub content can lag a few minutes after a push.
- Never put API keys or tokens in `COMMS.md`, `LOG.md` or any pushed file.

### Entry format for `COMMS.md`

```
## C-014 | 2026-10-27 | agent -> consultant | BLOCKED | OPEN
Commit: a1b2c3d   Files: cutwright/mlt.py L730-754
Goal: one line.
Tried: numbered, with the exact command or edit each time.
Observed: the real output, trimmed to the lines that matter.
Known / assumed: two short lists, kept apart.
Ask: the one question or decision wanted.
```

Types: `BLOCKED`, `QUESTION`, `REVIEW` (please check this diff or design),
`BREAKTHROUGH` (for the record), `ANSWER`, `INFO`. Status is `OPEN` until the
other side replies, then `ANSWERED`. IDs only go up. Never edit an old entry;
add a new one that refers to it.

### After every breakthrough (agent, always, before anything else)

1. Add a dated entry to `LOG.md`: what changed, what proved it (the check output
   or measurement), what it unblocks.
2. Update the **Current status** block below (phase, last green commit, next step).
3. If a decision or surprise came up, add a `BREAKTHROUGH` entry to `COMMS.md`.
4. Commit with `git commit -F`, then **push**. Nothing was pushed at the
   2026-10-24 pause; unpushed work is invisible to the consultant and lost if the
   session dies.
A step is not finished until its log entry is pushed.

### Current status (agent keeps this block up to date)

```
Phase: 0 (not started)
Last green commit: a87f4bf (2026-10-24, nothing pushed)
Next step: Project.to_xml() crossfade edit, then full build of demo_cross
Open COMMS entries: C-001
```

## Consultant protocol (for when things get hard)

### When the agent must stop and escalate

Write a `BLOCKED` or `QUESTION` entry instead of trying again when any of these is
true:

- The same problem has survived **two** attempts that each changed something.
- A check fails and the cause is not clear from its own output.
- A choice has real trade-offs (licence, dependency, interface shape, whether to
  copy code or reimplement).
- A refactor would touch more than one phase's files.
- A check passed that the agent did not expect to, or failed in a way that does
  not match the theory.
- Credits or context are running low: write the entry *before* stopping.

Stopping early is cheaper than a fifth attempt. When blocked, do these first:
change one variable per attempt, keep the path to the failing artifact, and if the
tree has become confusing, return to the last green commit rather than stack more
edits on it.

### What the consultant does

1. Restates the problem in one line and separates **known** from **assumed**.
2. Gives at most three hypotheses, ranked, each with **one cheap test that
   distinguishes it** (a command, and what output means yes or no).
3. Recommends one next action, the smallest that moves things. Says what not to
   do (for example, "do not re-run the 90-second `luma_window_test.py`").
4. When attempts keep failing, questions the premise: is the goal right, is there a
   simpler shape, is a check measuring the wrong thing?
5. Proposes a stop-loss when a path has cost too much: cut scope, take the
   fallback, or park it with a note.
6. Reviews claims against evidence. "The check passes" needs the check output.
   `not_run` is not a pass.

### What the consultant cannot do

It cannot run melt, Shotcut, git or anything on the owner's machine, and it has no
network inside its sandbox. Every answer is a hypothesis until the agent runs it.
**The agent must post the result back as a new entry**, pass or fail, so the next
reader (the consultant, or a fresh session) is not guessing.

### Style of replies

Short, numbered, the recommended action first. Reasoning after, only as long as it
needs to be.

---

## Work plan

### Phase 0: finish the crossfade (already designed, smallest step)

Do "The edit to make" in the section below. Rebuild `projects/demo_cross`, get
`crossfade` and `gui_xfade` green, record the Ctrl+S copy in `PROVENANCE.md`.
**Why first:** it is fully specified, it unblocks Phase 4, and it leaves the repo
in a state where the existing checks mean something.
Done when: all nine checks pass on `demo_cross`; committed.

### Phase 1: read-only reconnaissance (no code, cheapest, prevents waste)

Clone and read: `shotcut-mcp`, `cli-anything-shotcut`, `NarratoAI`,
`altzotify-cell/RecapStudio`. Also compare RecapStudio with the
copy already in `vendor/recapstudio/` (hashes in `vendor/MANIFEST.sha256`).
Produce one file, `BORROW.md`, with for each repo: licence, the exact files and
functions for each item in the borrow list, and anything the owner's notes got wrong.
Done when: `BORROW.md` exists and every borrow-list row is marked *copy shape*,
*copy code*, *reimplement* or *drop*.

### Phase 2: coverage sheets (highest value, cheap, uses what exists)

- Take shot boundaries from the existing ffmpeg shot detection in `frames.py`.
- Take dialogue spans from the gated transcript (`subs.py` / `moments.py`).
- For each boundary with no overlapping cue, make a contact sheet; add a floor of one
  sheet per N minutes (default 3, configurable).
- Tag these in `moments.json` as a new status (for example `silent_unexplained`) so
  the agent knows they need a look. Optional: the spot-check sample from the
  adjustments above.
- Use an interval/batch/concurrency config in the NarratoAI style so large videos
  do not hammer one process.
- Add a `verify` check: every silent shot with no sheet is an error.
Done when: on a test clip with a known silent stretch, the sheet appears, is tagged,
and the check fails if it is removed.

### Phase 3: RecapStudio integration (replaces the paste step)

- Map RecapStudio's stages to subcommands with `--json`: extract subs, contact
  sheets, index footage, collect footage, generate voice, build video, build
  subtitles, build TikTok cut (see `vendor/.../_template/*.bat`).
- The agent reads the digest and writes `segments.json` / `plan.json` itself;
  retire `PASTE_THIS_TO_CLAUDE_*.txt` as a manual step (keep as reference prompts).
- Everything the integration writes goes through `guard.py`.
- Decide and write down: does Cutwright call RecapStudio's `recap.py`, or port the
  stages? Phase 1 findings decide this.
Done when: an agent, given only a video path and the CLI, can run from subtitles to a
built project with no human paste step.

### Phase 4: borrow from cli-anything-shotcut

In this order:
1. Volume envelopes and ducking (music under voice). Check: render and measure dB at
   voice and no-voice points; also survive Ctrl+S.
2. Blend modes, opacity, PIP. Check: render a frame and measure.
3. `--json` on every subcommand. Check: parses with `json.loads`.
4. A `SKILL.md` describing the CLI for other agents.
5. Preview bundles. Only if steps 1-4 went smoothly.
Skip: undo/redo.

### Phase 5: borrow from NarratoAI (all optional, default off)

Order by value per credit: keyframe batching (done in Phase 2), subtitle mask,
Sonilo BGM/SFX, Tavily plot search, TwelveLabs, hosted captioners. Each is a config
flag plus a separate module; none may become a hard dependency.

### Phase 6: the milestone chain already in the old handoff

Music dipping (now Phase 4 step 1) -> J/L cuts -> per-line captions -> the planner
(bundle plus JSON-schema validation) -> an end-to-end run on a short clip ->
`REPORT.md`.

## Suggested order against a limited budget

| Step | Cost | Stop here and the repo is... |
|---|---|---|
| Phase 0 | small | consistent and green |
| Phase 1 | small, no code | informed; every later step is cheaper |
| Phase 2 | small-medium | better at perception than before |
| Phase 4 steps 1-3 | medium | able to duck music and overlay |
| Phase 3 | medium-large | agent-driven end to end |
| Phase 5 | optional | extended |

## Open questions for the owner

1. Licence of Cutwright itself? (Decides what can be copied in.)
2. Does an agent calling a CLI with `--json` satisfy "fully integrate", or is an MCP
   server required now?
3. Is `altzotify-cell/cutwright` (and RecapStudio) public? If private, the consultant can only see pasted text.
4. Which execution agent will run each phase? (Whichever has desktop access is the
   only one that can run melt and Shotcut for the GUI checks.)

## Session log (what the consultant actually did on 2026-10-26)

- Listed the zip. Read `HANDOFF.md` and the first 120 lines of `README.md`.
- Did **not** read: `LOG.md`, `REPORT.md`, `PROVENANCE.md`, any `.py` file, the
  RecapStudio vendor files, or any GitHub repo.
- Wrote this plan. No code, `.mlt` file or project was changed.
- Added the communication and consultant protocols, and `COMMS.md`. A test fetch of the
  RecapStudio URL failed and a search did not find the repo; fetching from GitHub is
  unverified.
- Removed `dylanler/AI-auto-narrator` at the owner's request: it was listed with no
  stated purpose and is not needed.

## Start here (for whichever agent picks this up)

1. Read this section (including the two protocol sections), then "The edit to make" below.
   Open `COMMS.md` and answer C-001.
2. Run `python -m cutwright doctor` and confirm what is present.
3. Do Phase 0. Commit with `git commit -F`.
4. Do Phase 1 and write `BORROW.md` before touching anything else.
5. After every breakthrough: LOG.md entry, update Current status, commit, push.

---

## Previous handoff (2026-10-24, unchanged)


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

