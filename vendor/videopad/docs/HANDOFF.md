# HANDOFF — agent-driven video editing through VideoPad

> **Read this first if you are a new session.** It is self-contained: goal,
> verdict, environment, exact commands, hard-won gotchas, current state, open
> work. `docs/vpj-format-findings.md` holds the deep format detail; this file
> holds the operational picture and the traps.

## 1. Goal

An agent pipeline that edits video unattended:

```
JSON edit spec  →  .vpj project  →  VideoPad  →  exported .mp4
```

No ffmpeg rendering, no screen recording, no NLE SDK — VideoPad itself is the
renderer, and the agent only supplies a project file plus a click.

## 2. Verdict: can an agent edit in VideoPad?

**Yes, with a precise scope.** Three separate questions hide inside that one:

| question | answer | why |
|---|---|---|
| Can a tool write a `.vpj` VideoPad will open and honour? | **Yes, proven** | `.vpj` is plain-text LF-terminated sectioned querystrings; a stale checksum only raises a "Damaged File" prompt that is auto-answerable |
| Can VideoPad be made to *export* that project unattended? | **Yes, proven** | ribbon coordinate clicks + `BM_CLICK` on the export dialog's `Create` button; output verified frame-by-frame |
| Can an agent perform *arbitrary* edits? | **Partly — v12** | the writer renames, trims, reorders, **reuses a source any number of times**, adds and removes clips, **adds new media files**, mutes segments, **splits a clip at arbitrary cut points**, writes **per-segment video effect chains** registered in `tools/effects.json` — with the **style filters `blur`/`noise`/`pixelate`, the `cartoon` and `snow` effects and the `saturation`/`hue`/`temperature` colour sliders measured and range-checked**, and `"identity": true` for a measured no-op — **changes playback speed, fades clips in/out, flips them, sets per-clip audio gain and audio fades**, and **prunes bin entries nothing refers to** so a project no longer drags the template's foreign media along. Not yet: transitions, titles, audio mixing, and the rest of the effect catalogue (ids not captured). See §10 |

So: **the loop closes today for a cut** *and* for structural edits that only add
or remove timeline clips and bin media, *and* for split + effect chains, *and* for
speed/fade pacing. It does not yet cover transitions, titles or audio mixing.


There is **no scripting API**: VideoPad is a Delphi app with no MSAA/UIA
provider (all ~65 UIA descendants are unnamed `Pane`s). Everything below is
Win32 window enumeration + synthetic input, so it is inherently calibrated to a
window size and DPI. Treat the UI layer as the fragile part and the `.vpj`
writer as the durable part.

## 3. Environment (this machine — re-verify if anything looks off)

| item | value |
|---|---|
| VideoPad | Professional **8.91+**, 32-bit, `C:\Program Files (x86)\NCH Software\VideoPad\videopad.exe` |
| display | **150% scaling** (this is the source of the historical DPI bug, §7) |
| main window | 1536×817 physical px at the calibration used for ribbon coords |
| ffmpeg / ffprobe | `C:\Users\user\scoop\shims\ffmpeg.exe` (on PATH) |
| workspace | `C:\Users\user\Downloads\videopad` |
| template project | `C:\Users\user\Documents\probe.vpj` |
| autosave read-out | `%APPDATA%\NCH Software\VideoPad\autosave.vpj` |
| export presets | `%APPDATA%\NCH Software\VideoPad\ComputerPresets\*.dat` |

Source media in the template (two distinct sources, timeline order):

| index | handle | file |
|---|---|---|
| `source: 0` | media `h=327` | `One_Punch_Man_Season_3_Episode_2_1080p_@Tv_Series_ETY_.Mkv` (1 441 083 ms) |
| `source: 1` | media `h=345` | `One_Punch_Man_Season_3_Episode_3_1080p_@Tv_Series_ETY_.Mkv` (1 441 083 ms) |

The two episodes **share an identical opening**, which matters for verification:
any frame from the first ~90 s matches both sources, so content checks are only
conclusive past the opening (§8).

## 4. Pipeline and file map

| file | role |
|---|---|
| `examples/cut1.json` | the edit spec (template, output, sequence name, segments) |
| `examples/cut2-reuse.json`, `examples/cut3-addmedia.json` | v2 specs: source reuse / dropped clip / mute, and added media |
| `examples/cut4-split-effects.json` | v3 spec: `split`, `defaultEffects`, per-segment `effects` |
| `examples/cut5-cadence.json` | v4 spec: `speed`, `fadeIn`, `fadeOut` (plus a mirror so effects are seen to compose with speed) |
| `tools/effects.json` | **effect registry**: for each effect, its `id` (the value that goes in `typeN`), the blob VideoPad ships (`defaults`), named `presets`, and per-key metadata (number, enum, bool, keyframed). Keys were dumped from the live `HKCU:\…\VideoPad\EffectPresets` |
| `tools/Get-Effects.ps1` | prints the registry as a table (name / id / category), one effect's parameters and ranges with `-Name`, a paste-ready spec fragment with `-Skeleton`, JSON with `-Json` — the answer to "what may I name here?" |
| `tools/Read-EffectChain.ps1` | the inverse: reads `effectchains` back out of any `.vpj` as clip / slot / id / registry name / decoded parameters, and lists the ids that are **not** in the registry — the reading half of every capture |
| `tools/Start-Capture.ps1` | the whole capture loop in one command: rebuilds `out/capture.vpj` from `out/capture.spec.json`, opens it, waits for a save that actually carries an effect **and** belongs to the capture project (project file *or* `autosave.vpj`), then prints the chain — `-KeepExisting`, `-NoOpen`, `-WaitSeconds` |
| `tools/New-Project.ps1` | **spec → .vpj** by editing the template; preserves unknown fields byte-for-byte |
| `tools/Test-Examples.ps1` | rebuilds every spec and asserts the output is **byte-identical** — the gate before a commit (no VideoPad needed) |
| `tools/Open-Project.ps1` | launches VideoPad on a `.vpj`, clears stale modals, auto-answers "Damaged File" via `WM_COMMAND/IDOK`; ~4.5 s |
| `tools/Watch-Autosave.ps1` | load → wait for autosave refresh → report what the parser actually absorbed |
| `tools/Compare-Vpj.ps1` | field-level diff of two `.vpj` files, records matched by handle — the check behind every "round-tripped unchanged" claim |
| `tools/Invoke-AgentStep.ps1` | runs one step in a child PowerShell and prints one JSON verdict `{ok, exitCode, timedOut, seconds, stdout, stderr}` — the agent contract |
| `tools/Export-Project.ps1` | **.vpj → .mp4**: ribbon clicks, `Create`, wait, adopt file, verify duration |
| `tools/PadUi.ps1` | UI primitives: DPI-aware capture/click, top-level window enumeration, control search, `BM_CLICK`, window resizing |
| `tools/NativeInput.cs` | P/Invoke layer (`mouse_event`, `keybd_event`, `SendMessage`, `EnumWindows`, …) |
| `tools/Probe-ExportDialog.ps1` | diagnostic: dumps the control map of whatever dialog is under a point |
| `tools/Get-WindowCapture.ps1`, `tools/Send-PadClick.ps1` | earlier standalone capture / click tools, still useful for calibration |
| `docs/vpj-format-findings.md` | format reference: sections, handles, checksum, timeline semantics, export |
| `docs/AGENT-RUNBOOK.md` | operating manual for driving the pipeline from an agent: loop, costs, failure taxonomy, invariants |
| `agent/tools.json` | the same pipeline as seven functions with JSON-Schema arguments, for a tool-calling loop or an MCP server |
| `agent/system-prompt.md` | paste-ready agent contract: rules, loop, budgets, reporting format |
| `agent/Invoke-PadTool.ps1` | fills one `tools.json` template (applies defaults, derives computed args, refuses shell metacharacters) and runs it through the runner |
| `RUN-IT.md` | copy-paste, press-Enter walkthrough for someone who has never used PowerShell, with the exact output of every step |
| `out/cut1.vpj`, `out/cut2-reuse.vpj`, `out/cut3-addmedia.vpj` | the generated projects (210 000 / 150 000 / 36 000 ms) |
| `out/cut4-split-effects.vpj` | v3 project: 15 000 ms, 6 clips from 3 segments (one split in three, one split in two) + effect chains |
| `out/cut5-cadence.vpj` | v4 project: 13 500 ms, 4 clips (2×, 1×, 0.5×, 2× with a chain), three keyframed fades |
| `out/agent-cut-v2.mp4`, `out/agent-cut-first-export.mp4` | the two verified 210 s exports (identical) |
| `out/cut3-addmedia.mp4`, `out/cut4-effects.mp4`, `out/cut5-cadence.mp4` | the v2, v3 and v4 exports (gitignored) |

| `out/oracle/` | evidence: v2/v3/v4 autosave round-trips, watcher logs, export logs, frame-MAE scripts and results (`cut3-verify.*`, `cut4-verify.*`, `cut5-verify.*`), the `v4-probe/` experiment set, and `compare-projects.ps1` (timelines + chains, human-readable) — pair it with `tools/Compare-Vpj.ps1` for a field-level diff |

End-to-end invocation, in order:

```powershell
cd C:\Users\user\Downloads\videopad

# 0. regression gate (~2 s, no VideoPad): every spec must reproduce its .vpj exactly
.\tools\Test-Examples.ps1

# 1. spec -> project
.\tools\New-Project.ps1 -Spec .\examples\cut1.json

# 2. cheap content check (~5 s, no encode)
.\tools\Watch-Autosave.ps1 -Project .\out\cut1.vpj -LogPath .\logs\autosave-check.log

# 3. render (drives the UI, ~7 min for 3.5 min of 1080p)
.\tools\Export-Project.ps1 -ProjectPath .\out\cut1.vpj `
    -OutputPath .\out\agent-cut.mp4 -ExpectedDurationMs 210000

# 3b. if the click phase already started an encode and you lost the process:
.\tools\Export-Project.ps1 -OutputPath .\out\agent-cut.mp4 `
    -ExpectedDurationMs 210000 -WaitOnly
```

`Export-Project.ps1` parameters:

| param | meaning |
|---|---|
| `-OutputPath` (required) | where the finished mp4 must end up |
| `-ProjectPath` | open this project first (delegates to `Open-Project.ps1`); omit to use whatever is open |
| `-ExpectedDurationMs` | asserts the result within ±42 ms (one frame at 23.976); `0` skips |
| `-ExportFolder` | folder VideoPad writes into. The *dialog* inherits the project's `Computer_FilePath` (usually `%USERPROFILE%\Videos`); the *tool* defaults to `%USERPROFILE%\Videos` if not given |
| `-TimeoutSeconds` | whole-run budget, default 1800 |
| `-WaitOnly` | skip all clicks, adopt the newest export in `-ExportFolder` (recovery path) |

## 5. The `.vpj` format in one screen

Plain text, LF line endings, one record per line, each line a querystring of
`key=value&key=value`. Lines are grouped into named sections; a record's identity
is its handle, **not** its line position.

| `type=` | record | key fields |
|---|---|---|
| 1 / 2 | video / audio track | `h`, `htrack` |
| 3 / 5 | video / audio media (source) | `h`, `name`, `out` (source length, ms) |
| 6 | sequence | `h`, `name`, `duration`, `in`, `out` |
| 7 | trackclip | `h`, `htrack`, `horiginalclip`, `hlinked`, `offset`, `in`, `out` |

Semantics that matter when writing:

- `in`/`out` on a trackclip = trim window **inside the source** (ms); `offset` =
  position **on the timeline** (ms). With `speedchangef≠1` the window is
  *speed-scaled* — source = `(in + t) × speed`, see "Speed and fades" in
  `docs/vpj-format-findings.md`.
- A source's video and audio are **two separate `type=7` records** joined by
  `hlinked` — trim them identically or A/V drifts.
- Sequence `duration`/`out` must equal the **exact sum** of `(out - in)` over its
  trackclips (the sample's 2 × 1 441 083 = 2 882 166 to the millisecond).
- `effectchains` has exactly one line per clip/sequence/media handle, which is why
  adding a handle is not just "add a line".
- The last line is `checksum=…`. **Do not reverse-engineer it** — leave it stale.
  VideoPad then shows "Damaged File / Try Load", which `Open-Project.ps1` answers
  in ~4 s. (This is the single biggest time-saver in the whole project.)
- The file stores **paths, not media**. Missing files resolve offline.

## 6. The writer: spec schema and guard rails

```json
{
  "template": "probe.vpj",
  "output":   "../out/cut4-split-effects.vpj",
  "sequenceName": "Split + Effect Test",
  "media":    [ { "id": "bars", "path": "../out/testmedia/bars.mp4" } ],
  "defaultEffects": [ { "name": "saturation", "preset": "Completely Unsaturated" } ],
  "segments": [
    { "source": 1,      "start": 0,      "end": 6000,   "split": [ 2000, 4000 ] },
    { "source": "bars", "start": 0,      "end": 6000,   "split": [ 3000 ],
      "effects": [ { "name": "rotate", "params": { "z": 90 } } ] },
    { "source": 1,      "start": 900000, "end": 903000,
      "effects": [ { "name": "mirror", "params": { "mirrordirection": "vertical" } },
                   { "name": "colorAdjust", "preset": "Bright", "params": { "contrast": 60 } } ] }
  ]
}
```

- `source` is either an integer index into the template's distinct sources **in
  timeline order**, or the `id` of an entry in `media`. `start`/`end` are ms
  inside that source; `mute` is optional.
- Segment order *is* timeline order, so the list doubles as a reorder, a drop
  (omit a source) and a reuse (repeat one).
- `split` is a list of **absolute ms inside the source** (not offsets into the
  segment) that must lie strictly between `start` and `end`. It expands into
  adjacent segments sharing one media handle and one effect chain, which is
  exactly how VideoPad stores a split (no special "split" record exists).
- `effects` is that segment's video effect chain; `defaultEffects` is inherited by
  every segment that does not define `effects`. An **explicit `[]` means "no
  effects"** and does override `defaultEffects`. Audio is unaffected — an audio
  clip's chain is the empty default, as the app writes it.
- An effect entry is `{ "name": <key in tools/effects.json>, "preset": <name>, "params": { … } }`.
  `preset` fills the blob from the registry, then `params` overrides only the keys
  given; `params` alone starts from the effect's `defaults`. Overriding a
  keyframed parameter group (`keys!=0`) is refused rather than silently discarded.
- `{ "name": …, "identity": true }` writes that effect's **measured no-op** — the
  registry's `identity` object — instead of its shipped default, which is often
  not neutral (`hue` 90, `temperature` 64). Only measured effects have one;
  asking for an unmeasured effect's identity is refused (§8 v11).
- `sequenceName` is optional and URL-encoded into the sequence record.
- `dropUnusedMedia` (bool, default false) removes every bin entry no clip
  refers to, and the `effectchains` line that belongs to it. The template is a
  real project, so its bin carries sources the spec never mentions (and the app
  keeps a source in the bin after its last clip is deleted). With it set, a
  one-clip project has a one-source bin: `out/cut5`-style specs go from
  `clips=5` (sequence + 2 media pairs) to `clips=3`, and **no reference to a file
  outside the repo survives** — which is what makes an exported project portable
  to another machine. Handles are not renumbered, so nothing else shifts, and the
  writer refuses to drop a handle a clip still names. Reported as `MediaDropped`.
- `speed` (number, default 1) changes playback rate: 2 halves the clip's timeline
  length, 0.5 doubles it. **`in`/`out` are written divided by the speed**, because
  the app reads source = position × speed (see
  `docs/vpj-format-findings.md` → "Speed and fades"). A segment that would need
  `out > mediaDuration/speed` is **rejected**, since VideoPad silently clamps
  there and every later clip would shift.
- `fadeIn` / `fadeOut` (ms) ramp the clip from/to black. They are written as a
  keyframed Fade (opacity) slot appended after the segment's own effects; the app
  only ships whole-clip fades, so partial fades need keyframes. Fades that
  overlap each other or exceed the clip are rejected.
- **All paths resolve against the spec's own folder** unless absolute, so a spec
  is portable between checkouts.
- `media` entries are measured with `ffprobe` — supply `"duration"` (ms) to skip
  that. A file without an audio stream is rejected: added media is written as an
  A/V pair and the audio-less variant has not been verified.

What `New-Project.ps1` does:

- trims `in`/`out` on the video **and** linked audio trackclip, rewrites `offset`
  cumulatively from 0, sets sequence `duration`/`out` to the exact sum;
- **reuses** a template trackclip pair when the segment's source still has an
  unused one, so a spec that never repeats a source rewrites the file in place
  (byte-identical to the v1 output — `examples/cut1.json` still reproduces
  `out/cut1.vpj` exactly);
- otherwise **allocates** a fresh `type=7` video/audio handle pair from `hindex`,
  bumps `hindex`, and clones the pair from the template's own prototype line;
- **expands `split`** into consecutive segments before anything else runs, so a
  cut point is just two adjacent clips — VideoPad shows it as a split (same media
  handle, touching offsets) and nothing downstream needs to know;
- **writes effect chains**: resolves each segment's `effects`/`defaultEffects`
  through `tools/effects.json`, then rewrites the `size`/`typeN`/`presetN`/`dataN`
  slots of that clip's `effectchains` record (found by its `hclip`). Everything
  else in the record — fades, speed, `hclip` itself — is preserved field by field;
- **removes** the trackclip *and* `effectchains` records of clips no longer used,
  so nothing is orphaned on the timeline (bin media records are kept by default,
  matching what the app does when a clip is deleted — `dropUnusedMedia` prunes
  them, and their `effectchains`, on request);
- **adds** a `type=5`/`type=3` media pair plus one `effectchains` line per handle
  for every new file; segments of the same added media share that one record;
- **sets speed** on both records of a clip's video/audio pair and lays the
  timeline out from the speed-scaled lengths, so offsets stay contiguous;
- **appends a fade slot** for `fadeIn`/`fadeOut`, with keyframe positions as
  fractions of the clip's own (post-speed) length;
- refuses trims past source length, and **asserts**: every handle unique, exactly
  one `effectchains` record per clip handle, section counts consistent with their
  bodies, and the checksum line untouched — so a format drift fails loudly
  instead of producing a subtly broken project.

It returns one summary object — `Output`, `DurationMs`, `SequenceName`,
`SourceCount`, `SegmentCount` (after split expansion), `DroppedClips`,
`MediaDropped`, `AllocatedHandles`, `MediaAdded`, `EffectCount`, and `Clips` with
each clip's handles and resolved chain — which is what `Test-Examples.ps1` prints
next to its byte comparison.

It works by editing a known-good template and reassembling by section, so every
field nobody understands survives byte-for-byte (including the glued
`Type=2SubtitlesExport=1` quirk and the stray CR).

## 7. UI automation: the rules that took the longest to learn

**R1 — DPI awareness before any coordinate.** PowerShell is DPI-unaware by
default: `GetWindowRect` returns *logical* px while `BitBlt`/`SetCursorPos` use
*physical* px. At 150% every click was displaced by half a screen and every
capture was cropped to the window's top-left ⅔. Call `SetProcessDPIAware()` first
(`PadUi.ps1` does). A long-standing note in this repo claimed "mouse clicks are
blocked by the Windows foreground lock" — **that was wrong**, it was DPI.

**R2 — Dialogs are owned popups, not children.** `GetParent` on a dialog control
returns the *owner*, so a dialog looks like a descendant, but
`EnumChildWindows(main)` never reaches it. Enumerate process **top-level** windows
(`Get-PadWindows`).

**R3 — Ribbon is custom-drawn, dialogs are not.** The ribbon has no HWNDs and no
UIA → coordinate clicks only. The export dialog is a `DirectUIHWND` (embedded IE)
inside a `NativeHWNDHost` popup, but its buttons are **real Win32 `Button`s with
window text** → find by name and `BM_CLICK`. A synthetic *mouse* click on `Create`
is silently swallowed; `BM_CLICK` works; `Enter` also works (default button).

**R4 — The export dropdown is transient.** Home → Export Video → Video File must
be three clicks **inside one process**. A tool round-trip between them lets the
menu auto-close and the next click lands on the ribbon — that failure mode
silently changed the active tab to Sequence, then Effects, and opened a Text
Effects gallery. If the ribbon looks "possessed", this is why.

**R5 — Coordinate frame.** Ribbon coords were calibrated at **1536×817** physical:
Home `(175,66)`, Export Video `(543,105)`, Video File `(515,176)`.
`Export-Project.ps1` now **resizes the window to 1536×817** (`Set-PadWindowSize`)
before clicking. Scaling the coordinates by `window.Width / 1536` alone is not
enough: the ribbon scales with **DPI, not with window width**, so on a maximised
1942×1030 window every width-scaled click lands *below* the ribbon and the Export
dropdown never opens (seen live — the driver waited out its timeout for a dialog
that never appeared). Recalibrate if the DPI changes; capture a screenshot with
`Save-PadCapture` and read coords off the **physical** image.

**R6 — Single instance, and never force-kill.** VideoPad silently **drops the file
argument** if another instance is already running — close first via `WM_CLOSE`.
Force-killing arms crash recovery ("Abnormal Termination"), which then suppresses
the CLI argument on the next start and poisons the next several runs.

**R7 — `WM_CLOSE` is swallowed while a modal is open.** Dismiss the modal first —
and note that each swallowed `WM_CLOSE` spawns *another* prompt, so a naive retry
loop leaves a stack of identical dialogs. `Open-Project.ps1` answers them
(`Clear-PadModals`) before closing. The ones seen in practice:

| modal | buttons | answer |
|---|---|---|
| "The current project has been changed since the last time you saved…" | `Save` `Discard` `Cancel` | **Discard** (one per swallowed close) |
| "New media has been connected to your computer." | `Add Files` `No` | **No** (raised when files land in a watched folder — e.g. our own export) |
| "Damaged File … try to load it anyway?" | `Try Load` `Cancel` | **Try Load** via `WM_COMMAND/IDOK`, never `Cancel` |

These are **real `#32770` windows with real `Button` children, but UI Automation
does not expose them at all** — not the window, not the buttons. `Clear-PadModals`
therefore enumerates with Win32 (`Get-PadWindows` + `EnumChildWindows`) and never
answers anything whose text mentions "damaged".

**R8 — The encode happens inside VideoPad.** The calling script is not the renderer,
so an interrupted script does not lose the render: `-WaitOnly` adopts the newest
export. The mp4 is unreadable until the `moov` atom is written (`ffprobe` says
`moov atom not found` mid-encode); completion = size stopped changing **and**
ffprobe returns a duration.

**R9 — Output naming cannot be set.** The dialog's text fields are inside the
DirectUI tree. VideoPad **never overwrites**: an existing target becomes
`Name 1.mp4`. Hence the tool snapshots the folder, adopts the new/changed file,
moves it to `-OutputPath`, then dismisses the completion dialog (its `Close`
button is found by name).

**R10 — Run the UI-driving scripts in a console you can see, and clear modals
before anything else.** A hidden / detached `Start-Process powershell -File …`
launched from another PowerShell session produced *no window enumeration and no
clicks at all* — the script appeared to run and did nothing. Whatever the cause
(session/desktop or job-object teardown), the reliable patterns are (a) run
`Export-Project.ps1` in the interactive console, or (b) if you must detach, create
the process with `Invoke-CimMethod -ClassName Win32_Process -MethodName Create`
and point its stdout/stderr at a log file, then poll the log — that is how the
`cut4` export was driven. Related: after a killed VideoPad the next start raises
**"Abnormal Termination Detected"** (an "unexpectedly terminated" report dialog)
that swallows clicks on the ribbon until dismissed; treat it like any other modal
(`Get-PadWindows` + `WM_COMMAND`/`IDOK`) instead of force-killing the app again.

**R11 — Find prompts by their buttons, not by their names.** The "Damaged File"
prompt's window text is empty whenever a second prompt stacks on the first, and
`Clear-PadModals` used to answer the leftover one with `[Cancel]` — which
silently throws the load away, leaving an empty "Untitled" sequence that looks
exactly like a corrupt project. `Open-Project.ps1` now looks for a real Win32
`Button` whose text is `Try Load` on any top-level window and activates it with
`BM_CLICK`. Two details cost real time: `WM_COMMAND`/`IDOK` must be posted to the
**dialog**, not to the button (posting to the button is accepted and does
nothing — it produced 26 unanswered prompts), and a prompt whose button set is
`[It Crashed] [Something Else]` means the app is in crash recovery and has
already dropped the file argument, so the only useful answer is to report it.

**R12 — The Video Effects picker scrolls only by scrollbar or wheel.** Reported
from manual use: two-finger trackpad swipes over the tile grid do nothing, while
dragging the scrollbar works. The grid is a plain scrollable Win32 child window,
so a precision touchpad's gesture (delivered as pointer/`WM_GESTURE` messages)
never becomes the `WM_VSCROLL` it listens for. Two consequences: any future
automation of that picker must drive `WM_VSCROLL` or the scrollbar directly —
synthesised two-finger scrolling will silently no-op and look like "the tile was
not there" — and a human capture session should maximise the window, which fits
every tile without scrolling. The user-facing workaround is in `RUN-IT.md` §9.

## 8. Evidence the pipeline is real (not "the export dialog opened")

Two independent oracles, deliberately: one for *what VideoPad parsed*, one for
*what came out the far end*.

**Oracle A — autosave (`tools/Watch-Autosave.ps1`).** VideoPad rewrites
`%APPDATA%\NCH Software\VideoPad\autosave.vpj` ~3 s after a load, as a full
re-serialization of its in-memory model. A project we wrote and the app's own
re-emission differ on **exactly three lines**: `hindex`, one folder `open=` UI
flag, and `checksum`. `thumbpos` was also recomputed (1 440 000 → 100 000), which
proves the app *rebuilt* the timeline from our values instead of echoing the file
back. That is how content fidelity was confirmed cheaply, without rendering.

**Oracle B — exported frames.** `ffmpeg -ss <t> -frames:v 1 -vf scale=32:32,format=gray`
on both the export and the sources, then mean absolute error (0 ≈ identical,
70+ ≈ unrelated).

Spec under test: `source 1` 0–90 000 ms, then `source 0` 60 000–180 000 ms →
expected 210 000 ms.

| check | result |
|---|---|
| duration | **210.005751 s** vs 210.000 requested → 5.8 ms ≈ 0.14 frame |
| streams | 1920×1080 h264 + AAC, 5036 frames @ 23.976 |
| size | 178 212 640 bytes |
| determinism | two runs **byte-identical**, SHA256 `FDCA15802A463E3E7D0BF63AFF595E2E76013E8B6D7353891E48D31FB13CB16D` |
| export@91 s vs Ep2@61 s | **0.23** ← match (91−90 = 1 s into segment 2, in-point 60 s) |
| export@91 s vs Ep3@91 s | 73.67 ← control |
| export@91 s vs Ep2@91 s | 73.64 ← control |
| export@200 s vs Ep2@170 s | **0.18** ← match (200−90 = 110 s + 60 s in-point) |
| export@200 s vs Ep3@170 s | 79.08 ← control |

Read the matches backwards: they pin the **switch at exactly 90 000 ms**, because
the match only holds at `t − 90 000 + source in-point`.

**Honest limitation:** `export@86 s` matches *both* sources (0.23 / 0.26), because
the two episodes share an identical opening. Frames therefore **cannot**
distinguish Ep3 from Ep2 inside the first 90 s. What is provable there is the
segment's 90 s length and that the switch lands at 90 s — not which episode fills
it. Segment 2 is conclusively Ep2.

Reproduce the frame check:

```powershell
$t=91
& ffmpeg -v error -ss $t -i .\out\agent-cut-v2.mp4 -frames:v 1 -vf scale=32:32,format=gray -f rawvideo -y out\a.gray
& ffmpeg -v error -ss 61 -i 'D:\path\to\Episode_2.mkv' -frames:v 1 -vf scale=32:32,format=gray -f rawvideo -y out\b.gray
$A=[IO.File]::ReadAllBytes("$PWD\out\a.gray"); $B=[IO.File]::ReadAllBytes("$PWD\out\b.gray")
$s=0; for($i=0;$i -lt $A.Length;$i++){ $s += [Math]::Abs($A[$i]-$B[$i]) }; 'MAE = ' + [Math]::Round($s/$A.Length,2)
```

### v2 evidence (structure *and* new media)

Both v2 features were checked against both oracles, and the artefacts are in
`out/oracle/`:

| project | what it proves | result |
|---|---|---|
| `out/cut2-reuse.vpj` (5 clips, one source used 3×, 3 allocated pairs, one muted) | source reuse + drop + mute survive the parser | autosave returned all 10 trackclips **byte-identical** (handle, `horiginalclip`, `htrack`, `offset`, `in`, `out`), `clips=5 / trackclips=10 / effectchains=15`, `mute=1` kept. Only deltas: checksum, `hindex`, folder `open=`, recomputed `thumb` |
| `out/cut3-addmedia.vpj` (Ep3 0–15 s, `bars.mp4` 0–6 s, Ep3 900–915 s) | added media + reuse + trim, end to end | autosave: `clips=7 / trackclips=6 / effectchains=13`, all 6 clips identical, and the two synthesised media records identical **down to field order and `creationtime`**. Export: **36.011 s** vs 36.000 expected (Δ 11 ms) |

Frame MAE for the export (`out/oracle/cut3-verify.ps1` → `.txt`):

| comparison | MAE | reading |
|---|---|---|
| `export@18s` vs `bars@3s` | **0.59** | the added media really is on screen, at the right source time |
| `export@18s` vs `Ep3@5s` | 97.41 | …and it is not the episode |
| `export@5s` vs `Ep3@5s` | **0.20** | segment 1 correct (`Ep2@5s` = 1.04: shared opening) |
| `export@30s` vs `Ep3@909s` | **0.42** | segment 3's `in=900000` is exact |
| `export@30s` vs `Ep3@5s` | 121.23 | …and unrelated to the episode's opening |

Regenerate the scratch clip the add-media example points at:

```powershell
ffmpeg -y -f lavfi -i "testsrc2=size=640x360:rate=25:duration=6" `
       -f lavfi -i "sine=frequency=440:duration=6" `
       -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest out\testmedia\bars.mp4
```

### v3 evidence (split + effect chains)

Spec `examples/cut4-split-effects.json` → `out/cut4-split-effects.vpj`: 15 000 ms,
3 spec segments expanding to **6 clips**, `defaultEffects` on every segment,
one segment overriding with its own chain:

| timeline (ms) | source | chain actually written |
|---|---|---|
| 0–2 000 / 2 000–4 000 / 4 000–6 000 | Ep3 (one clip, `split [2000, 4000]`) | `type=24` saturation `value=-100` — inherited `defaultEffects` |
| 6 000–9 000 / 9 000–12 000 | `bars.mp4` (`split [3000]`) | `type=33` rotate `z=90` — explicit `effects`, and the frame stays **colourful**, so it replaced the default rather than appending to it |
| 12 000–15 000 | Ep3 @ 900 000 | `type=36` mirror `mirrordirection=1` **and** `type=6` colour `contrast=60` |

**Oracle A — autosave round-trip** (`out/oracle/cut4-split-effects.roundtrip.vpj`,
differ with `tools/Compare-Vpj.ps1 -A out/cut4-split-effects.vpj -B …`; for a
readable dump of timelines and chains use `out/oracle/compare-projects.ps1`):
all 6 video/audio pairs came back with identical `h`, `hlinked`, `in`, `out`,
`offset` — the split survived as three and two adjacent clips sharing one media
handle, which is exactly how the app itself stores a split. All six chains came
back slot-for-slot identical (`size`, `typeN`, `dataN`).

Two deltas, both benign, both worth knowing:

- **line order**: the app emits all video trackclips, then all audio. Pure
  re-serialisation; the format keys off handles, not line positions.
- **`presetN` is re-derived.** `rotate`/`mirror`/`colour` came back as
  `preset=Custom` instead of `Default Preset`/`Bright`, because our params no
  longer equal the shipped preset. Saturation kept
  `preset=Completely Unsaturated` because `value=-100` *is* that preset. So the
  app validates `dataN` against the preset table and relabels accordingly —
  **diff `dataN`, never `presetN`**, and never expect a preset *name* to round-trip
  once you override a single parameter.

**Oracle B — export** `out/cut4-effects.mp4`: 15.019 s vs 15 000 (Δ 19 ms ≈ 0.5
frame), 7 461 497 bytes, 1920×1080 h264 + AAC. Numbers from
`out/oracle/cut4-verify.ps1` (output in `cut4-verify.txt`):

| claim | measurement | reading |
|---|---|---|
| clips 0–2 are desaturated | mean chroma `0.0` at t = 1 / 3 / 5 s vs **33.4** on Ep3@5 s; frame MAE export@5 vs Ep3@5 = **4.06** | same picture, colour removed — MAE 4 is as close as a deliberate effect gets |
| clips 3–4 are rotated | export@7 vs `bars@1` **transposed ccw = 46.86**, cw = 99.26, as-is = 95.49 | the 90° turn is there and it is the right way round; the residual is the pillarbox crop at 32×32 |
| …and keep their colour | chroma export@7 = **133.1** vs source 226.3 | `effects` overrode `defaultEffects`; had it been inherited the export would have been grey |
| clip 6 is mirrored | export@13 vs **its own L-R mirror = 0.19**, vs its own T-B mirror = 152.91; the unmirrored source scores **35.69** against its own L-R mirror | left-right symmetric, and the source is not — mirror active, axis = vertical. (`effects.json`'s "vertical" means *mirror across the vertical axis*, i.e. a horizontal flip.) |
| …and contrast-boosted | frame is visibly blown out; MAE against the mirror-flipped source is ~64 for both flipped and unflipped, i.e. luma was rescaled too much for MAE to arbitrate | read from the frames, not the metric |

The saturation check is the one that needs care: Ep3's opening 0–4 s is a
pencil-sketch title card that is *already* near-grey (source chroma 2.0 / 1.7), so
t = 1 s and t = 3 s prove nothing on their own. Only t = 5 s, where the source
chroma is 33.4 and the export's is 0.0, separates "effect applied" from "source
was grey".

Sampling times follow from the spec, not from guessing: clip 3 starts at timeline
6 000 with `in=0`, so export@7 s is `bars@1 s`; clip 6 starts at 12 000 with
`in=900000`, so export@13 s is `Ep3@901 s`.

### v4 evidence (speed + fades)

Spec `examples/cut5-cadence.json` → `out/cut5-cadence.vpj`: 13 500 ms, 4 clips.

| timeline (ms) | written as | why |
|---|---|---|
| 0–3 000 | `in=0 out=3000`, `speedchangef=2.000000` on both records, Fade `keys=3` at positions 0 / 0.083333 / 1 | `bars` 0–6 000 at 2× — 6 s of source in a 3 s slot; 250 ms fade-in = 250/3000 of the clip |
| 3 000–6 000 | `in=1000 out=4000`, Fade `keys=3` at 0 / 0.833333 / 1 | 500 ms fade-out, position 1 − 500/3000 |
| 6 000–12 000 | `in=0 out=6000`, `speedchangef=0.500000` | `bars` 0–3 000 at half speed |
| 12 000–13 500 | `in=1500 out=3000`, `speedchangef=2.000000`, Mirror + Fade `keys=4` at 0 / 0.133333 / 0.866667 / 1 | `bars` 3 000–6 000 at 2×, so `in` is 3000/2; 200 ms fades on a 1500 ms clip |

**Oracle A — autosave round-trip** (`out/oracle/cut5-cadence.roundtrip.vpj`): the
only differences are `thumb`/`thumbpos` on the sequence record, which the app
always zeroes. Every `in`/`out`/`offset`, both `speedchangef` values of each pair,
all four keyframe groups and the mirror slot came back untouched — in particular
the app did **not** re-clamp `out`, which is what the writer's guard exists to
prevent.

**Oracle B — export** `out/cut5-cadence.mp4`: 13.534 s vs 13 500 (Δ 34 ms),
2 245 767 bytes. Every number below is reproduced by
`out/oracle/cut5-verify.ps1` (output in `cut5-verify.txt`); source frames are
matched by 32×32 greyscale MAE, the same method `cut4-verify.ps1` uses, so speed
is *measured* rather than inferred from the burnt-in timecode (which was read
visually as a second opinion):

| claim | measurement | reading |
|---|---|---|
| clip 1 plays at 2× | export@2.9 s vs `bars@5.8` = **0.69**; vs `bars@2.9` = 7.48 | 3 s into a 2× clip is source 5.8 s, not 2.9 s |
| clip 3 plays at 0.5× | export@8.5 s vs `bars@1.25` = **2.39**; vs `bars@2.5` = 5.78 | 2.5 s into a half-speed clip is source 1.25 s |
| `in` is speed-scaled | export@12.5 s vs `bars@4.0` = **1.67**; vs `bars@2.0` = 9.05 | clip 4 has `in=1500`; source is (1500+500)×2 = 4.0 s, not 2.0 s |
| clip 4 keeps its effect | export@12.5 vs `bars@4.0` half-mirrored = **1.67**, vs unflipped = 53.99 | the chain still applies while the clip is sped up |

Fades, as mean luma of the 32×32 frame: clip 1 climbs **5.3 → 67.1 → 126.8**
across its 250 ms and holds at 126.8; clip 2 falls **125.0 → 44.3 → 2.4** across
its last 500 ms; clip 4 is dark at 12.05 s (37.9), reaches 144.9 by 12.4 s and is
back to 20.3 at 13.45 s as its 200 ms fade-out finishes.

While measuring clip 4, the mirror's *default* direction turned out not to be a
flip at all: `mirrordirection=0` keeps the left half and reflects it onto the
right (a half mirror), so `bars@4.0` matches it at MAE 1.67 while plain
hflip/vflip/unflipped all sit at 54-58. `mirrordirection=1` — what cut4 used — is
the plain horizontal flip.

**Guard rails, exercised:** a 1000 ms segment with `fadeIn 800`+`fadeOut 800`
fails with *"fades 800+800 ms but the clip is only 1000 ms long"*; `speed: 0`
fails with *"has speed 0; it must be greater than 0"*. Both refuse before a byte
of project is written.

**What the probes ruled out** (all in `out/oracle/v4-probe/`, same recipe in §8):

- `fadeinduration` on the trackclip is **not** a fade length — the app resets it
  to 0 on load, so a fade must be an effect-chain keyframe group instead.
- `voll`/`volr` on a clip's effectchains record round-trip verbatim but change
  nothing in the render: six segments exported at −3.4 dB whether they carried
  `50`, `-6` or `0`.
- Setting `fadepoints=2` makes the app materialise a full fade model
  (`fadetype0/1`, `pos0/1`, `volume0/1`) — a real format, but with zeroed points
  it has no audible effect, and the units are still unverified.
- effect 28 (the `fade` entry in `tools/effects.json`) applied to the **audio**
  chain survives the round-trip and is silently ignored at render time: it is
  video opacity. This is why `fadeIn`/`fadeOut` are documented as picture fades.

### v5 evidence (flip / lateral inversion)

Spec `examples/cut6-flip.json` → `out/cut6-flip.vpj`: 12 000 ms, 5 clips from one
6 s asymmetric source (`out/testmedia/asym.mp4`, 640×360) covering all four values
of the new segment key.

| timeline (ms) | written as | why |
|---|---|---|
| 0–3 000 | `type0=69`, `horzflip=value=1`, `vertflip=value=0` | lateral inversion |
| 3 000–6 000 | `horzflip=value=0`, `vertflip=value=1` | upside down |
| 6 000–9 000 | the `both` slot on **both** halves of `split: [1500]` | the key is inherited like `effects`/`fadeIn` |
| 9 000–12 000 | `flip: "none"` → `size=0` chain | the no-op is expressible, and is the control |

**Oracle — export** `out/cut6-flip.mp4`: 12.010 s vs 12 000 (Δ 10 ms),
2 285 251 bytes, SHA256 `F8C8C0B0…2B903A`. Every number below is reproduced by
`out/oracle/cut6-verify.ps1` (output in `cut6-verify.txt`) — 32×32 greyscale MAE
against `asym` frames flipped with ffmpeg, the same method as `cut4`/`cut5`:

| clip | vs expected flip | vs hflip | vs vflip | vs h+v | vs unflipped |
|---|---|---|---|---|---|
| horizontal | **2.37** | 2.37 | 105.56 | 8.82 | 106.42 |
| vertical | **2.41** | 105.55 | 2.41 | 106.40 | 8.82 |
| both (6.75 s) | **0.67** | 8.56 | 106.22 | 0.67 | 106.22 |
| both (8.25 s) | **3.01** | 9.43 | 105.43 | 3.01 | 105.48 |
| none (10.5 s) | **1.93** | 106.94 | 8.59 | 106.08 | 1.93 |

Reading: the horizontal clip is 2.37 away from its own L-R mirror and 106 from
the unflipped source, so those pixels really are inverted left-right; the vertical
clip is the transpose of that result (2.41 vs its T-B mirror, 106 vs hflip); both
halves of the split pair match h+v, so the key survived the split; and `none`
sits at 1.93 against the unflipped source and 107 against hflip — the control that
says the metric can tell the difference at all.

Caveat worth keeping: `asym.mp4` is strongly L-R asymmetric (≈106 between a frame
and its mirror) but nearly T-B symmetric (≈8.6), so the horizontal claim is the one
this source proves hard; the vertical claim rests on *which* reference it matches
(2.41 vs 105.55), not on its distance from unflipped.

**Guard rail, exercised:** `"flip": "sideways"` fails with *\"Segment 1 for source
'asym' has flip 'sideways'; expected horizontal (left<->right), vertical
(top<->bottom), both, or none.\"* and no project file is written.

**Why a key and not an effect:** effect 69 (`flip`) was already in
`tools/effects.json`, so nothing *new* is possible that wasn't before — the change
is that a spec no longer has to discover that `{ "name": "mirror" }` defaults to
`mirrordirection=0` (a half mirror) and that `mirrordirection=1` is the actual
flip. `flip` says which way the picture ends up, and the two axes are independent,
so `both` (180°/point symmetry) is expressible in one slot.

### v6 evidence (per-clip audio gain)

Spec `examples/cut7-audio.json` → `out/cut7-audio.vpj`: 12 000 ms, 5 clips —
0 dB, −6 dB, −12 dB split in two, then `mute`.

| timeline (ms) | written as | why |
|---|---|---|
| 0–3 000 | audio record `size=1&type0=1001&data0=amplify=value=100.000000` | unity |
| 3 000–6 000 | `…value=87.543` | 100 + 2.0761 × (−6) |
| 6 000–9 000 | `…value=75.087` on **both** halves | −12 dB, inherited by the split |
| 9 000–12 000 | `mute=1`, audio chain `size=0` | the existing off switch |

**The units came first.** VideoPad's Amplify slider is not a percentage, so one
12 s probe export (`out/oracle/v5-probe/audio-ladder`) carried the slider at
0 / 25 / 50 / 75 / 100 / 125 / 150 / 200 and measured each:

| slider | 0 | 25 | 50 | 75 | 100 | 125 | 150 | 200 |
|---|---|---|---|---|---|---|---|---|
| mean dB vs 100 | silent | −36.1 | −24.0 | −12.1 | 0 | +0.1 | 0 | +0.1 |

That is a dB control: **0.4816 dB per unit**, 12.5 units per 6 dB, i.e.
`value = 100 + 2.0761 × dB`. A percentage would have put 50 at −6 dB; it is at
−24. My first cut of this feature wrote percent straight into the slider and was
wrong by 18 dB — the numbers, not the reasoning, caught it.

**Boosts do not exist in this pipeline.** 125, 150 and 200 are indistinguishable
from 100 because the exporter normalises peaks to full scale: a project with *no*
audio effect at all exports at −3.2 dB mean against a source that measures
−21.1 (a +17.9 dB lift), so the peaks already sit on 0 dBFS and more gain only
clips. That is why `audioGainDb` rejects positive values instead of pretending.

**Oracle — export** `out/cut7-audio.mp4`: 12.028 s vs 12 000 (Δ 28 ms),
1 262 526 bytes, SHA256 `DA65EAB6…890CEC`. Reproduced by
`out/oracle/cut7-verify.ps1` (`cut7-verify.txt`), `volumedetect` over 0.6–1 s
windows:

| clip | mean dB | vs control | asked |
|---|---|---|---|
| 0 dB (control) | −3.2 | 0 | 0 |
| −6 dB | −9.3 | **−6.1** | −6 |
| −12 dB | −15.2 | **−12.0** | −12 |
| −12 dB, second half | −16.1 | −12.9 | −12 |
| `mute` | −91 | −87.8 | silence |

The remaining 0.1–0.9 dB is content, not conversion: the two halves of the −12 dB
clip are different 1.5 s of source, and a 32×32-style window mean is not a
loudness meter.

**Guard rails, exercised:** `audioGainDb: 3` → *"only attenuation is meaningful
… slider 125, 150 and 200 are all 0 dB against 100"*; `-99` → *"below the range
this writer accepts"*; `"loud"` → *"not a number of decibels"*; `0` and `-6`
build normally.

### v7 evidence (audio fades)

Spec `examples/cut8-audiofade.json` → `out/cut8-audiofade.vpj`: 12 000 ms, 4
clips of 3 s — no keys, `audioFadeIn 800`, `audioFadeOut 800`, then
`audioGainDb -6` with 500/500 fades.

| timeline (ms) | written as | why |
|---|---|---|
| 0–3 000 | audio chain `size=0` | control |
| 3 000–6 000 | `keys=3`: (0, 0) (0.266667, 100) (1, 100) | 800 ms of a 3 s clip = 0.266667 |
| 6 000–9 000 | `keys=3`: (0, 100) (0.733333, 100) (1, 0) | 1 − 800/3000 |
| 9 000–12 000 | `keys=4`: (0, 0) (0.166667, 87.543) (0.833333, 87.543) (1, 0) | plateau carries −6 dB; one slot, not a gain plus a fade |

**A bare number silences the clip.** The first attempt wrote
`amplify=0.000000&userdata=0&keys=3&…`; every faded clip then exported at
−91 dB at *every* probe, plateau included. A wrapped parameter's value is itself
an escaped keyframe group — the static slot stores
`amplify=value%3D100.000000%26userdata%3D0%26keys%3D0`, and the keyframed one must
be `amplify=` + the escaped group. Caught by measuring a plateau that should have
been loud, not by reading the file.

**Oracle — export** `out/cut8-audiofade.mp4`: 12.028 s vs 12 000 (Δ 28 ms),
1 231 855 bytes, SHA256 `B415FEF2…CD70E1`, `out/oracle/cut8-verify.ps1`
(`cut8-verify.txt`), 0.15 s `volumedetect` windows, dB against the control clip:

| clip | probes (s → dB) | reading |
|---|---|---|
| no keys (control) | 1.50 → −3.1 | reference |
| `audioFadeIn 800` | 3.10 → −14.3, 3.40 → −5.1, 3.70 → −0.9, 3.90 → 0, 4.50 → −0.5 | rises over the ramp and holds at control level |
| `audioFadeOut 800` | 7.50 → 0, 8.30 → −2.0, 8.60 → −7.5, 8.85 → −17.9 | falls over the last 800 ms |
| `-6 dB` + 500/500 | 9.10 → −16.3, 9.40 → −7.2, 9.60 → −6.1, 10.50 → −6.3, 11.60 → −9.6, 11.85 → −19.7 | rises, plateaus at the requested −6 dB, falls |

**Interpolation is linear in amplitude, not in the slider.** Halfway through an
800 ms ramp the slider sits at ~44 and the level measures −5.1 dB, where a ramp
linear in slider units would give −27 and a dB-linear ramp about −24. Each
keyframe value is mapped through the same 0.4816 dB/unit curve as a static value,
and the ramp interpolates the resulting amplitudes (mid-ramp prediction −7.2 dB
before window smear, measured −5.1). That is the usual constant-gain fade; a fade
that is linear in dB, which many editors offer, would need many keyframes.

**Guard rails, exercised:** `audioFadeIn: -1` → *"has a negative audio fade
length"*; 2000+2000 ms on a 3000 ms clip → *"fades audio 2000+2000 ms but the
clip is only 3000 ms long"*.

### v8 evidence (style filters, fine-tuned)

Spec `examples/cut9-filters.json` → `out/cut9-filters.vpj`: 20 000 ms, 10 clips
of 2 s from `bars.mp4`, all starting at **source 0** — so every clip paints the
same frame at the probe point and any difference between clips *is* the effect.

| timeline (ms) | chain | what it isolates |
|---|---|---|
| 0–2 000 | none | control |
| 2–4 000 | `blur 25` | intensity, gentle |
| 4–6 000 | `blur 100` | intensity, maximum single slot |
| 6–8 000 | `blur 100` + `blur 100` | **two slots of the same effect** |
| 8–10 000 | `noise 80` | intensity, with default saturation/coverage |
| 10–12 000 | `noise 80, sat 100` | saturation |
| 12–14 000 | `noise 80, cov 50` | coverage |
| 14–16 000 | `noise 80, cov 10` | coverage |
| 16–18 000 | `noise 20` | intensity, low |
| 18–20 000 | `blur 40` + `noise 30, cov 60` | chain order (blur first) |

**Oracle — export** `out/cut9-filters.mp4`: 20.016 s vs 20 000 (Δ 16 ms),
43 137 643 bytes — 17× the size of `cut8`, which is the grain refusing to
compress. `out/oracle/cut9-verify.ps1` (`cut9-verify.out`) probes 1 s into each
clip, compares against the control clip of the same export (so encode error and
source are held constant) and against the source frame:

| clip | detail mean | edge peak (p99.5) | MAE vs control |
|---|---|---|---|
| control | 1.374 | 49.2 | 0 |
| `blur 25` | 1.324 | 48.5 | 2.20 |
| `blur 100` | 1.312 | 48.5 | 4.81 |
| `blur 100` ×2 slots | 1.272 | 47.2 | 8.06 |
| `noise 80` | 53.889 | 148.2 | 63.70 |
| `noise 80, sat 100` | 39.170 | 119.0 | 55.47 |
| `noise 80, cov 50` | 41.176 | 151.0 | 32.81 |
| `noise 80, cov 10` | 13.056 | 139.2 | 8.01 |
| `noise 20` | 13.146 | 42.8 | 15.70 |
| `blur 40` + `noise 30, cov 60` | 16.910 | 57.2 | 16.40 |

**Blur is a soft focus, not an obscurer.** `intensity` is monotonic (2.20 →
4.81 MAE) and *stackable* — a second identical slot doubles it to 8.06 — but one
slot at 100 leaves mean detail at 1.312 against the control's 1.374 and the
hardest edges untouched (49.2 → 48.5). Both frames look almost identical to the
eye (`out/cut9-control.png` vs `out/cut9-blur100.png`). For anything that needs
detail actually gone, `pixelate` is the tool; blur is for softening.

**Noise intensity is the real knob:** 20 → MAE 15.70, 80 → 63.70, with mean
detail up 39×. It is the only effect here that changes a picture beyond
recognition at mid-range.

**`saturation` is not "how colourful the grain is" — at its default 0 the picture
loses its colour.** Chroma (mean |U−128|, |V−128|) reads 72.4 / 71.3 on the
control, **14.5 / 14.1** at `noise 80` with saturation 0 (i.e. the frame is
nearly monochrome, confirmed by eye: `cut9-noise80.png`), and 16.6 / 16.5 with
saturation 100 — while luma detail *drops* 53.9 → 39.2. The noise budget is
shared: asking for colour grain takes it out of the luminance grain.

**`coverage` is the fraction of pixels speckled, scattered across the whole
frame — not a region.** Fraction of pixels that moved more than 8 luma units:
**0.913 / 0.463 / 0.101** for coverage 100 / 50 / 10, against 0.913 for the
default 100. At coverage 10 the picture is intact and colourful under sparse
white speckle (`cut9-noise80cov10.png`) — which is why a per-tile detail test
misread it as full coverage first time round, and why the oracle counts moved
pixels instead.

**Range validation (new in the writer).** Numeric parameters are now checked
against the schema's `min`/`max` before anything is written: `blur` at
`intensity: 150` fails with *"Effect 'blur' parameter 'intensity' got 150; the
range is 0..100."* Previously the value was written and VideoPad clamped it
silently, which looks identical to a radius that simply does not work.

### v9 evidence (Cartoon and Snow)


Both ids were captured the same way: apply the effect once in the app, let
`Watch-Autosave.ps1` record VideoPad's re-serialisation, copy the id and the
`Value` blob into `tools/effects.json`, then confirm the writer reproduces it
byte for byte. `cartoon` is `41`, `snow` is `84`.

Spec `examples/cut10-cartoon.json` → `out/cut10-cartoon.vpj`: 16 000 ms, 8 clips
of 2 s from `bars.mp4`, all at source 0 — control, then `cartoon` at defaults and
with one knob moved (`cc` 2/64, `et` 0/100, `br` 0/20). Export
`out/cut10-cartoon.mp4` (Δ 10 ms), measured by `out/oracle/cut10-verify.ps1`:

| clip | MAE vs control | luma levels | strong-edge px | edge luma Δ |
|---|---|---|---|---|
| control | 0 | 203 | 3 092 | −15.1 |
| `cartoon` defaults | 39.12 | 189 | 2 835 | −36.6 |
| `cc 2` | 65.34 | 119 | 2 797 | −18.0 |
| `cc 64` | 10.64 | 198 | 2 940 | −45.6 |
| `et 0` | 39.61 | 197 | 1 345 | −65.6 |
| `et 100` | 38.08 | 173 | 8 343 | −34.4 |
| `br 0` | 37.83 | 192 | 7 418 | −49.2 |
| `br 20` | 39.66 | 192 | 1 285 | +0.9 |

**`cc` is the flatness knob** — 119 surviving luma levels at `cc 2` against 198 at
`cc 64`, and the top-ten luma buckets hold 89.6 % of the frame at `cc 2` versus
76.3 % at `cc 64` — and it dominates the re-draw (MAE 65.3 versus 10.6). **`et` is
edge sensitivity**, and it is the one that decides how much of the picture becomes
outline: 1 345 strong-gradient pixels at `et 0`, 2 835 at the default 58, 8 343 at
`et 100`. **`br` is outline brightness, not boldness** — edge pixels sit 49.2 luma
below the frame mean at `br 0`, 36.6 below at the default 5, and 0.9 *above* it at
`br 20`, so the lines stop reading as lines rather than getting thicker
(`out/cut10-defaults.png`, `cut10-et100.png`, `cut10-br20.png`).

Spec `examples/cut11-snow.json` → `out/cut11-snow.vpj`: 20 000 ms, 10 clips of
2 s, one knob per clip (`pf` 5/100, `scale` 0.1/2, `opacity` 0.3, `dv` 1,
`lt` 500/8000). Export `out/cut11-snow.mp4` (Δ 16 ms); the oracle counts flake
pixels and frame-to-frame motion:

| clip | flake % | motion MAE | MAE vs control |
|---|---|---|---|
| control | 0 | 6.33 | 0 |
| `snow` defaults | 0.30 | 7.40 | 1.28 |
| `pf 5` | 0.07 | 6.58 | 1.01 |
| `pf 100` | 1.12 | 10.04 | 2.93 |
| `scale 0.1` | 0.03 | 6.43 | 1.00 |
| `scale 2` | 1.07 | 9.55 | 2.55 |
| `opacity 0.3` | 0 | 6.66 | 1.04 |
| `dv 1` | 0.51 | 7.93 | 1.66 |
| `lt 500` | 0.22 | 7.03 | 1.29 |
| `lt 8000` | 0.26 | 7.18 | 1.35 |

**`pf` is a flake budget and behaves almost linearly** (0.07 / 0.30 / 1.12 % at 5 /
25 / 100); **`scale` is flake size and just as strong** (0.03 % at 0.1, 1.07 % at
2); **`opacity` is flake solidity**, so at 0.3 nothing is bright enough to count as
snow; **`dv` adds sideways drift**; **`lt` is a lifetime in milliseconds** that
barely moves a single sampled frame but governs how long a flake survives. The
control clip already moves (MAE 6.33 — it is a test pattern with a moving clock),
and every snow clip adds on top of that: this is a **time-based overlay**, so
unlike a colour filter it animates a still source.

### v10 evidence (pruned bin)

`dropUnusedMedia` is a spec flag, not new format knowledge: the records it removes
are ones the writer already understood. Two checks, because the risk is not "does
the byte edit work" but "does VideoPad care that a bin entry is gone".

Spec `examples/cut13-dropmedia.json` → `out/cut13-dropmedia.vpj`: two clips from
one template source (4 s, then a muted 4 s), `dropUnusedMedia: true`. Result:
`MediaDropped 2`, `DroppedClips 1`, `clips=3` (sequence + the one surviving
`type=5`/`type=3` pair), `trackclips=4`, `effectchains=7` — exactly the four
timeline handles, the sequence, and the two surviving media handles. Nothing is
left naming a handle that no longer exists, and the surviving handles keep their
numbers (`hindex` untouched).

Render check, on the harsher case: `out/cut5-pruned.vpj` is
`examples/cut5-cadence.json` + `dropUnusedMedia: true`, so its bin loses *all four*
template records (that spec builds its timeline from added `bars.mp4`; `clips=5` →
`clips=3`, zero `.mkv` references left). Exported from the app:

| check | result |
|---|---|
| open (`tools/Open-Project.ps1`) | **Loaded in 5.3 s**, 1 prompt (the usual checksum mismatch), **no modals** — no missing-media complaint |
| export (`tools/Export-Project.ps1`) | `out/cut5-pruned.mp4`, 2 245 767 bytes, 13.534 s |
| vs `out/cut5-cadence.mp4` (same timeline, unpruned bin) | **identical SHA-256** (`64743BD7…33B66`) — no re-encode drift at all |
| `out/oracle/v10-verify.ps1` | frame MAE 0.00 at 0.5 / 3 / 6 / 9 / 12.5 s |

An identical file is the strongest available statement that the app ignores the
absence: same picture, same bytes.

**Regression gate:** with the flag unset the writer is unchanged — all 13 example
specs still reproduce their committed `.vpj` byte-for-byte, so v10 is a strict
superset. `cut13` was added afterwards and the gate covers it as well.

### v11 evidence (the colour sliders, measured)

`saturation` (24), `hue` (25) and `temperature` (26) were already in the registry
from the `EffectPresets` dump — usable, but their summaries were *guesses* read
off preset names. This pass measured them, so the registry now says what each
slider does instead of what NCH called it.

Spec `examples/cut14-colour.json` → `out/cut14-colour.vpj`: 24 000 ms, 12 clips of
2 s from `bars.mp4`, every clip starting at source 0, so all twelve show the same
static frame and any difference is the effect. Exported to
`out/cut14-colour.mp4` (Δ within one frame) and measured by
`out/oracle/cut14-verify.ps1`: mean chroma (max−min over R,G,B, 0 = grey), circular
mean hue over pixels with chroma > 20, mean red minus mean blue, and mean luma.

| clip | chroma | hue° | R−B | luma |
|---|---|---|---|---|
| control | 246.5 | 170 | −3.6 | 125.3 |
| `saturation` −100 | **0.1** | – | 0 | 125.1 |
| `saturation` 0 | 246.5 | 169 | −3.5 | 125.2 |
| `saturation` 25 (default) | 247.9 | 173 | −3.8 | 125.2 |
| `saturation` 100 | 251.3 | 172 | −4.1 | 125.6 |
| `hue` 0 (Normal) | 246.4 | 170 | −3.5 | 125.2 |
| `hue` 90 (**default**) | 183.0 | **273** | −3.9 | 124.3 |
| `hue` 180 | 123.3 | 347 | 2.0 | 124.2 |
| `temperature` 0 (Normal) | 246.6 | 170 | −3.6 | 125.3 |
| `temperature` −128 | 177.1 | 193 | **−120.3** | 116.3 |
| `temperature` 64 (**default**) | 206.6 | 53 | **+56.2** | 120.5 |
| `temperature` 128 | 174.1 | 49 | +116.1 | 116.7 |

What the numbers settle:

- **0 is the identity for all three** — chroma, hue and R−B land on the control
  within measurement noise. So `saturation 0` is "unchanged", not "no colour";
  only −100 is grey (chroma 0.1, luma untouched at 125.1, so it desaturates
  without dimming).
- **Two of the three shipped defaults are not neutral**: `hue` ships 90 (measures
  a quarter turn, 170° → 273°) and `temperature` ships 64 (already warm, R−B
  +56.2, dominant hue 53°). `saturation` ships 25, which is nearly neutral
  (+1.4 chroma). Ask for identity explicitly — preset `Normal`, or value 0.
- **Positive saturation has little headroom on this pattern**: 25 → 247.9 and
  100 → 251.3, about +2 %. The bars are already at chroma 246 of 255, so the
  ceiling, not the slider, is doing the limiting; on ordinary footage +100 is a
  clear push.
- **Rotation costs chroma**: 246 → 183 at 90° → 123 at 180°, because colours
  pushed outside the gamut clip. A hue test that only looks at "colourfulness"
  would misread a hue shift as a desaturation.
- **Cool is darker**: `temperature` −128 drops luma 9 (125.3 → 116.3) as well as
  blue-ing the frame, so a "cool look" also needs a brightness touch-up if it has
  to match exposure.

The same probe closes the loop on the writer: the last three clips ask for
`{ "name": "saturation" | "hue" | "temperature", "identity": true }`, which is
new — it means "write this effect's *measured* no-op", taken from a new
`identity` object in `tools/effects.json` (`{ "value": 0 }` for all three). They
measure chroma 246.5 and R−B −3.6, i.e. the control frame, with a frame MAE of
0.75 / 1.02 / 1.01 against it — the same 0.65–1.0 band the explicit `value: 0`
clips sit in, which is encoder noise between clips, not picture difference. An
effect with no measured identity cannot be asked for this way: the writer refuses
rather than guessing, because a guess is exactly what `hue`'s shipped 90 would
give.

### v12 evidence (pixelate, and why "1" is not "off")

`pixelate` (15) is another registry entry whose summary was an assertion. Spec
`examples/cut15-pixelate.json` → `out/cut15-pixelate.vpj`: 12 000 ms, 6 clips of
2 s from `bars.mp4` at source 0 (control, then `pixelate` 1, 2, 6, 20, 100).
Exported to `out/cut15-pixelate.mp4` (Δ within one frame) and measured by
`out/oracle/cut15-verify.ps1`:

| clip | detail | distinct colours | run px | MAE vs control |
|---|---|---|---|---|
| control | 1.383 | 14 811 | 2.2 | 0 |
| `pixelate` 1 | 0.951 | 17 745 | 2.4 | 2.52 |
| `pixelate` 2 | 0.861 | 17 954 | 2.4 | 4.71 |
| `pixelate` 6 | 0.594 | 6 868 | 4.3 | 9.69 |
| `pixelate` 20 | 0.426 | 800 | 14.5 | 24.37 |
| `pixelate` 100 | 0.018 | 5 | 213.3 | 55.15 |

- **The slider is a size in effect, not literal pixels**: a mean run of 4.3 at
  value 6, 14.5 at 20 and 213.3 at 100 — a third of the 640 px frame, where it
  saturates. Colour count is the clean read-out: 17 954 → 6 868 → 800 → 5.
- **Value 1 is not "off"**: detail 0.951 against the control's 1.383 and MAE
  2.52 — and it *raises* the distinct-colour count (17 745), which is the
  signature of a resampling blur inventing intermediate colours rather than a
  blocky quantiser. So `pixelate` deliberately has **no** `identity` entry: the
  registry only claims a no-op where one was measured, and here there is none.


## 10. What is NOT supported yet (and the shape of the fix)

**Writer — still needs records this writer does not model:**

- **transitions** between clips (`transitions` section — not even inventoried yet),
- **titles** (the `Type=2SubtitlesExport=1` quirk is in every file, but no title
  record has been authored),
- **audio effects / mixing** — per-clip *level* (`audioGainDb`) and *fades*
  (`audioFadeIn`/`audioFadeOut`) are written now, and `mute` predates them, but
  that is all: no pan, no other audio effect (reverb, EQ, compressor are in the
  registry but uncatalogued here), and no second audio track, so no music bed and
  no ducking. `voll`/`volr` and effectchains `fadepoints` stay dead ends (§8 v4).
  The **track** records carry `volume=100&pan=0`, which is where pan would start.
- **the rest of the style-effect and overlay catalogue** — `blur`, `noise`,
  `cartoon` and `snow` are catalogued, characterised and range-checked (§8 v8, v9),
  but VideoPad ships dozens more (Dots, Night Vision, Glow, Vignette, Ripple,
  Oil Painting, Tiles, Balloons, Raindrops, …) whose ids and default blobs are not
  captured. Each needs one manual apply in the app — `tools/Start-Capture.ps1`
  does everything around that click and prints the id, the preset name and every
  stored parameter already decoded (`out/capture.vpj` is a committed one-clip
  project built for exactly this; the tool rebuilds it), after which the effect is
  a `tools/effects.json` entry like any other. Note that most are **identity at
  their defaults** — a probe export of 11 uncatalogued style ids
  (`out/cut12-probe.mp4`, `out/cut12-sheet.png`) showed only five changing the
  picture at all — so a capture has to name the effect explicitly; the frame alone
  cannot identify it,
- **keyframed effect parameters** — the writer now *authors* keyframes for fades,
  but still refuses to merge an override into a group that already has `keys!=0`,
- adding media **without an audio stream** — added media is written as a
  `type=5`/`type=3` pair, so a silent video is currently rejected rather than
  guessed at,
- more than one video/audio track or a second sequence.

Mechanically, everything else is now done: handles above `hindex` with `hindex`
bumped, cloned `type=7` pairs, cloned `effectchains` per handle, consistent
`hlinked`, recomputed `offset`/`duration`, split expansion into adjacent clips,
and removal of the records belonging to dropped clips.

**Other open items:**

- **Every project inherited two foreign media records — fixed in v10.** 
  `examples/probe.vpj` is a real project captured on this machine, so its bin
  still lists two `.mkv` files from
  `C:\Users\user\Downloads\Telegram Desktop\`, and the writer preserved media it
  was not asked about, so they rode along into every output (`SourceCount 2`,
  `DroppedClips 2` on a one-clip spec). `"dropUnusedMedia": true` now removes bin
  entries with no referencing clip, together with their `effectchains` records
  (§8 v10). It is opt-in, so the flag defaults to the app's own behaviour; put it
  in a spec whose output has to be portable to a machine without those files.
  `examples/cut13-dropmedia.json` is the worked example.
- **Presets can't be picked** — the picker is DirectUI. Workaround: author
  `%APPDATA%\NCH Software\VideoPad\ComputerPresets\*.dat`, which are plain
  querystrings (`EditOutput_Width=1280&…&VIDEO_CODEC_MP4=28&Type=4`), or set
  `Computer_Preset` in the project.
- **Output path/filename can't be typed** — see R9.
- **Checksum** — never reversed. Stale checksum + auto-answered prompt is the
  strategy; a real save round-trip could normalise it if a clean file is needed.
- **No concurrency** — single instance, global autosave file, so validation and
  export are serialised.
- **UI layer is calibrated** — different DPI/window size ⇒ recalibrate (§7 R5).
- **Encode speed** — ~7 min per 3.5 min of 1080p, no progress read-out, only size
  stability.

## 11. Current state (as of this handoff)

- `out/cut1.vpj` — v1 regression: 210 000 ms, sequence "Agent Cut", still
  byte-identical when regenerated by the v4 writer.
- `out/cut2-reuse.vpj` — v2 reuse/drop/mute: 150 000 ms, 5 clips from 2 sources,
  round-tripped through the app unchanged.
- `out/cut3-addmedia.vpj` — v2 add-media: 36 000 ms, exported to
  `out/cut3-addmedia.mp4` (16.5 MB, gitignored) and verified by frame MAE.
- `out/cut4-split-effects.vpj` — v3 split + effects: 15 000 ms, 3 spec segments
  → 6 clips, 3 distinct chains (7 effect slots). Round-tripped through the app
  (`out/oracle/cut4-split-effects.roundtrip.vpj`) and exported to
  `out/cut4-effects.mp4` (7.46 MB, Δ 19 ms), verified by chroma + symmetry +
  transpose comparison (§8, `out/oracle/cut4-verify.*`).
- `out/cut5-cadence.vpj` — v4 speed + fades: 13 500 ms, 4 clips (2×, 1×, 0.5×,
  2× with mirror), 4 effect slots including three keyframed fades.
  Round-tripped (`out/oracle/cut5-cadence.roundtrip.vpj`, only the thumbnail
  cache differs) and exported to `out/cut5-cadence.mp4` (2.25 MB, Δ 34 ms),
  verified by burnt-in timecode + luma ramps (§8).
- `out/cut6-flip.vpj` — v5 flip: 12 000 ms, 5 clips (horizontal, vertical, `both`
  split in two, `none` as the control), 4 slots of effect 69. Exported to
  `out/cut6-flip.mp4` (2.29 MB, Δ 10 ms) and verified by frame MAE against
  ffmpeg-flipped source frames (§8, v5 evidence).
- `out/cut7-audio.vpj` — v6 audio gain: 12 000 ms, 5 clips (0, −6, −12 dB with a
  split, then mute), 4 audio slots of effect 1001. Exported to
  `out/cut7-audio.mp4` (1.26 MB, Δ 28 ms) and verified with `volumedetect`
  (§8, v6 evidence).
- `out/cut8-audiofade.vpj` — v7 audio fades: 12 000 ms, 4 clips (control,
  `audioFadeIn 800`, `audioFadeOut 800`, `-6 dB` with 500/500), 3 keyframed audio
  slots. Exported to `out/cut8-audiofade.mp4` (1.23 MB, Δ 28 ms) and verified by
  windowed `volumedetect` (§8, v7 evidence).
- `out/cut9-filters.vpj` — v8 filters: 20 000 ms, 10 clips of 2 s from
  `bars.mp4` (control, blur 25/100/100×2, noise 80 with sat 100 and cov 50/10,
  noise 20, and a blur+noise chain), 11 effect slots. Exported to
  `out/cut9-filters.mp4` (43 MB, Δ 16 ms) and verified by per-parameter frame
  measurements — detail mean, edge peak, chroma and moved-pixel fraction (§8, v8
  evidence, `out/oracle/cut9-verify.*`).
- `out/cut10-cartoon.vpj` — v9 cartoon: 16 000 ms, 8 clips of 2 s from `bars.mp4`
  (control, then `cartoon` at defaults and with `cc`, `et`, `br` moved one at a
  time), 7 effect slots. Exported to `out/cut10-cartoon.mp4` (Δ 10 ms) and
  verified by luma-level count, edge-pixel count and edge luma offset (§8, v9
  evidence, `out/oracle/cut10-verify.*`).
- `out/cut11-snow.vpj` — v9 snow: 20 000 ms, 10 clips of 2 s (control, then `snow`
  with `pf`, `scale`, `opacity`, `dv`, `lt` moved one at a time), 9 effect slots.
  Exported to `out/cut11-snow.mp4` (Δ 16 ms) and verified by flake coverage and
  frame-to-frame motion (§8, v9 evidence, `out/oracle/cut11-verify.*`).
- `out/cut12-probe.vpj` — the id probe that closed the catalogue question: 24 000 ms,
  12 clips (control + 11 uncatalogued style ids applied raw from their default
  blobs), exported to `out/cut12-probe.mp4` and tiled into `out/cut12-sheet.png`.
  Only five of the 11 change the picture at their defaults, which is why effect
  names cannot be read off a frame.
- `out/cut13-dropmedia.vpj` — v10 pruned bin: 8 000 ms, 2 clips from one template
  source, `dropUnusedMedia: true` → `MediaDropped 2`, `clips=3`. The harsher case
  (`out/cut5-pruned.vpj`, all four template media dropped) was opened and exported
  from the app: the `.mp4` is **byte-identical** to the unpruned export (§8, v10
  evidence, `out/oracle/v10-verify.ps1`).
- `out/cut14-colour.vpj` — v11 colour sliders: 30 000 ms, 15 clips of 2 s from
  `bars.mp4` (control, `saturation` −100/0/25/100, `hue` 0/90/180,
  `temperature` 0/−128/64/128, then the three `"identity": true` clips), 14 effect
  slots. Exported to `out/cut14-colour.mp4` (Δ within one frame) and measured for
  chroma, circular mean hue, red-minus-blue, luma and frame MAE against the
  control (§8, v11 evidence, `out/oracle/cut14-verify.ps1`).
- `out/cut15-pixelate.vpj` — v12 pixelate: 12 000 ms, 6 clips of 2 s from
  `bars.mp4` (control, then `pixelate` 1/2/6/20/100), 5 effect slots. Exported to
  `out/cut15-pixelate.mp4` (Δ within one frame) and measured for detail, distinct
  colours, run length and MAE (§8, v12 evidence, `out/oracle/cut15-verify.ps1`).
- `tools/Test-Examples.ps1` reports **all specs byte-identical** (the v12 writer
  still reproduces `cut1`…`cut14` exactly, plus the local-only
  `yourclip-copyright-safe.json`, plus `cut15`), so v12 is a superset.
- All `tools/*.ps1` and the `out/oracle/**/*.ps1` helpers parse clean (AST check).
- VideoPad is **left running**; `Open-Project.ps1` now clears stale modals first,
  so the next run does not get stuck on a "Save changes?" prompt.
- The user's `Videos` folder is clean again — VideoPad writes there by default
  when the project's `Computer_FilePath` points there, and
  `Export-Project.ps1` moves the file out afterwards. If an `out\*.mp4` ever goes
  missing, check `Videos` first (an interrupted run can leave the only copy
  there) and then check for a PowerShell alias collision: a helper function named
  `MV` silently resolves to `Move-Item`, which is how `out/cut6-flip.mp4` was
  once renamed to a stray file called `0.5`. Both copies hashed
  `F8C8C0B0…2B903A`, so two renders of one recipe are byte-identical.

## 12. Bootstrap prompt for a new session

Paste this to continue the work with full context:

> You are continuing an agent video-editing project in
> `C:\Users\user\Downloads\videopad`. Read `docs/HANDOFF.md` first (operational
> picture, verdict, gotchas, commands), then `docs/vpj-format-findings.md` for
> format detail. It is a PowerShell toolchain that turns a JSON edit spec into a
> VideoPad `.vpj` and drives VideoPad's UI (DPI-aware synthetic clicks + `BM_CLICK`
> on the export dialog) to render an `.mp4` unattended. Proven: spec → `.vpj` →
> export, verified to within 19 ms of expected duration, by frame MAE against the
> sources, and byte-identical across runs. The writer is at **v9**: it can reuse a
> source any number of times, add and remove timeline clips, add new media files
> (ffprobe-measured), mute segments, **split a clip at arbitrary cut points
> (`split`)**, write **per-segment video effect chains (`effects`/
> `defaultEffects`, resolved through `tools/effects.json`, every numeric parameter
> range-checked against the registry's schema)**, **change speed (`speed`) and
> fade clips in/out (`fadeIn`/`fadeOut`, written as keyframed opacity slots)**,
> **flip a clip (`flip`), set per-clip audio gain (`audioGainDb`) and audio fades
> (`audioFadeIn`/`audioFadeOut`)** — each proven against VideoPad's own autosave
> re-serialisation and a real export (`out/oracle/`). The `blur` and `noise`
> filters are characterised parameter by parameter in §8 v8 evidence: blur is a
> soft focus (stack slots to strengthen it), noise `intensity` is the strong knob,
> noise `saturation` at its default 0 desaturates the picture, and `coverage` is
> the fraction of pixels speckled. `cartoon` (id 41) and `snow` (id 84) are
> characterised the same way in §8 v9: `cc` sets how flat the posterisation goes,
> `et` how much becomes outline, `br` is outline *brightness* not boldness;
> `snow`'s `pf` and `scale` are the strong knobs and it is a time-based overlay,
> so it animates a still source. Probe `out/cut12-sheet.png` shows the remaining
> style ids are mostly identity at their defaults, so new effects have to be
> captured by name. Not
> yet done: transitions, titles, audio mixing (no pan, no second audio track — see
> §10), the rest of the effect catalogue (ids not captured from the app), merging
> into already-keyframed effect params, silent
> (audio-less) media, presets, and setting the output path in the dialog.
> VideoPad 8.91 32-bit, display at 150% scaling, ffmpeg on PATH. Rules that
> matter: call `SetProcessDPIAware()` before touching coordinates; enumerate
> process top-level windows (dialogs are owned popups, not children); pin the
> editor window to 1536×817 before clicking the ribbon; never force-kill
> VideoPad; answer stale modals *before* `WM_CLOSE` (UIA cannot see them); keep
> the stale checksum and let `Open-Project.ps1` answer the "Damaged File" prompt;
> use `-WaitOnly` to recover an interrupted export; diff `dataN` not `presetN`
> (the app relabels any edited effect as `Custom`).
> [State the specific task here.]



