# videopad — agent-driven video editing

Turns a JSON edit spec into a VideoPad project and renders it to `.mp4`
unattended. VideoPad is the renderer; the agent only writes the project and
supplies the click.

```
examples/cut1.json  →  tools/New-Project.ps1  →  out/cut1.vpj  →  VideoPad  →  out/*.mp4
```

**Can an agent edit in VideoPad?** Yes for cutting, for structural edits that add
or remove timeline clips, for splits plus video effects, for pacing and for
picture and sound treatment: the writer (v9) reuses a source any number of times,
drops clips, adds new media files, mutes segments, splits a clip at arbitrary cut
points, writes per-segment effect chains from `tools/effects.json` — with every
numeric parameter validated against the registry's range — changes
playback speed, fades clips in/out, flips them horizontally or vertically,
attenuates their audio in dB and fades that audio in/out. Cut-only work was
verified end to end to within 6 ms of expected duration and byte-identical across
runs; every later feature was verified twice — against VideoPad's own autosave
re-serialisation, and by measuring a real export (`out/oracle/`): flipped frames
against ffmpeg-flipped source frames, audio level against `volumedetect` windows,
filter parameters against per-frame detail, edge and chroma statistics.
Audio level is attenuation only — the exporter normalises peaks to full scale, so
a boost just clips. Not yet: transitions, titles, pan, and a second audio track
(hence no music bed and no ducking — see [docs/HANDOFF.md](docs/HANDOFF.md) §10).
The style filters `blur` and `noise` are written and characterised (blur is a soft
focus, noise `intensity` is the strong knob, `coverage` is the fraction of pixels
speckled); so is `pixelate`, whose slider is a block size in effect and whose
value 1 is already a mild blur rather than "off"; so are VideoPad's `cartoon`
effect (flat colour bands plus ink lines)
and its `snow` overlay (animated flakes, so a still source moves). Each was pinned
down by exporting one parameter at a time and measuring the frames — see
[docs/HANDOFF.md](docs/HANDOFF.md) §8 v9. The rest of the app's effect catalogue
still has no captured ids. The colour sliders are measured as well — see
[docs/HANDOFF.md](docs/HANDOFF.md) §8 v11: 0 is the identity for `saturation`,
`hue` and `temperature`, and two of the three ship **non-neutral defaults**
(`hue` 90 = a quarter turn, `temperature` 64 = already warm), which is why a spec
can ask for `"identity": true` on an effect and get its measured no-op.
`"dropUnusedMedia": true` prunes bin entries nothing refers to (and their effect
chains), so a built project stops dragging the template's own media along —
measured to render byte-identically (§8 v10).

| start here | what it is |
|---|---|
| **[RUN-IT.md](RUN-IT.md)** | **step-by-step, assuming you've never opened PowerShell** — copy, paste, press Enter |
| **[START-HERE.md](START-HERE.md)** | **plain English** — what this does, how to run it, what comes out, what it can't do yet |
| **[docs/HANDOFF.md](docs/HANDOFF.md)** | **read this first** — verdict, environment, commands, UI-automation rules, open work, new-session bootstrap prompt |
| [docs/vpj-format-findings.md](docs/vpj-format-findings.md) | `.vpj` format reference: sections, handles, effect-chain slots, checksum, timeline semantics, export details |
| [tools/effects.json](tools/effects.json) | effect registry: ids, parameter schemas, preset blobs — the vocabulary `effects`/`defaultEffects` use |
| [tools/Get-Effects.ps1](tools/Get-Effects.ps1) | list that vocabulary: `-Name cartoon` for its parameters and ranges, `-Skeleton` for a paste-ready spec fragment |
| [tools/Read-EffectChain.ps1](tools/Read-EffectChain.ps1) | the other direction: read a saved `.vpj` back as `clip / slot / id / name / decoded parameters`, and flag ids the registry doesn't know yet |
| [tools/Start-Capture.ps1](tools/Start-Capture.ps1) | capture a new effect id from the app in one command: fresh one-clip project, open it, wait for your Ctrl+S (or the autosave), print the chain |

Quickstart (VideoPad must not already be running — `Open-Project.ps1` closes it):

```powershell
.\tools\New-Project.ps1 -Spec .\examples\cut1.json
.\tools\Export-Project.ps1 -ProjectPath .\out\cut1.vpj `
    -OutputPath .\out\agent-cut.mp4 -ExpectedDurationMs 210000
```

Fifteen specs to copy from:

| spec | shows |
|---|---|
| [`examples/cut1.json`](examples/cut1.json) | trim + reorder, one segment per source (byte-identical to the v1 writer) |
| [`examples/cut2-reuse.json`](examples/cut2-reuse.json) | one source used 3×, a dropped clip, a muted segment |
| [`examples/cut3-addmedia.json`](examples/cut3-addmedia.json) | added media between two episode segments |
| [`examples/cut4-split-effects.json`](examples/cut4-split-effects.json) | splits at 2 s/4 s and 3 s, saturation on all three episode clips, rotate, mirror + Bright-with-contrast |
| [`examples/cut5-cadence.json`](examples/cut5-cadence.json) | 2× / 1× / 0.5× / 2× speed segments, partial fades in and out, mirror on a sped clip |
| [`examples/cut6-flip.json`](examples/cut6-flip.json) | the same clip flipped `horizontal`, `vertical`, `both` (with a split through it) and `none` |
| [`examples/cut7-audio.json`](examples/cut7-audio.json) | audio at 0 / −6 / −12 dB plus a muted clip, with a split through a gain change |
| [`examples/cut8-audiofade.json`](examples/cut8-audiofade.json) | `audioFadeIn`, `audioFadeOut`, and −6 dB faded in *and* out — one audio slot per clip |
| [`examples/cut9-filters.json`](examples/cut9-filters.json) | the style filters, fine-tuned: `blur` at 25/100/100-stacked, `noise` isolated per parameter (intensity, saturation, coverage), and a blur→noise chain |
| [`examples/cut10-cartoon.json`](examples/cut10-cartoon.json) | `cartoon` isolated per parameter: defaults, `et=0`/`et=100` (edge sensitivity), `cc=2`/`cc=64` (colour levels), `br=0`/`br=20` (outline brightness), and cartoon→noise |
| [`examples/cut11-snow.json`](examples/cut11-snow.json) | the `snow` overlay, one knob per clip: `pf` 5/100, `scale` 0.1/2, `opacity` 0.3, `dv` 1, `lt` 500/8000 |
| [`examples/cut12-probe.json`](examples/cut12-probe.json) | 11 uncatalogued style ids applied raw from their default blobs — the probe that showed a frame cannot name an effect |
| [`examples/cut13-dropmedia.json`](examples/cut13-dropmedia.json) | `dropUnusedMedia`: two clips from one source, the other bin entries (and their chains) removed — `MediaDropped 2`, `clips=3` |
| [`examples/cut14-colour.json`](examples/cut14-colour.json) | the colour sliders measured: `saturation` −100/0/25/100, `hue` 0/90/180, `temperature` 0/−128/64/128 — one clip each against a control frame, then the three `"identity": true` clips |
| [`examples/cut15-pixelate.json`](examples/cut15-pixelate.json) | `pixelate` 1/2/6/20/100 against a control frame — the slider is a block size in effect (run 4.3 px at 6, 213 px at 100) and value 1 is not off |

`.\tools\Test-Examples.ps1` rebuilds every spec in `examples/` and fails unless each
reproduces its committed `.vpj` byte-for-byte — run it after touching the writer.

`cut3`–`cut5` need `bars.mp4` and `cut6`–`cut8` need `asym.mp4`; both are
gitignored, and both are what the oracles re-measure against — the rotate/crop
checks in `out/oracle/cut4-verify.ps1`, the timecode/luma checks in
`out/oracle/cut5-verify.ps1`, the flipped-frame MAE in `cut6-verify.ps1` and the
dB windows in `cut7-verify.ps1`/`cut8-verify.ps1`. `cut9`, `cut10` and `cut11` also
read `bars.mp4` and measure it in their oracle scripts: detail mean, edge peak,
chroma and the fraction of pixels each filter actually moved, which is how the
filter parameters were pinned down (see [docs/HANDOFF.md](docs/HANDOFF.md) §8 v8),
then the same per-parameter frame statistics for `cartoon` and the snow overlay's
flake coverage and frame-to-frame motion (§8 v9):

```powershell
ffmpeg -y -f lavfi -i "testsrc2=size=640x360:rate=25:duration=6" `
       -f lavfi -i "sine=frequency=440:duration=6" `
       -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest out\testmedia\bars.mp4
```

`asym.mp4` is the flip/audio source: 6 s, 640×360, 25 fps, mono 44.1 kHz, a steady
tone, and a picture that is strongly left/right asymmetric — which is the whole
point, since a symmetric clip cannot show whether a flip happened:

```powershell
ffmpeg -y -f lavfi -i "color=c=gray:s=640x360:r=25:d=6" `
       -f lavfi -i "sine=frequency=440:duration=6" `
       -filter_complex "[0:v]drawbox=x=0:y=0:w=240:h=360:color=white:t=fill,drawbox=x=400:y=90:w=240:h=180:color=red:t=fill,drawbox=x=280:y=240:w=120:h=120:color=blue:t=fill[v]" `
       -map "[v]" -map 1:a -c:v libx264 -pix_fmt yuv420p -c:a aac -ac 1 -ar 44100 -shortest out\testmedia\asym.mp4
```

That recipe is a reconstruction, not the exact file the committed numbers were
measured on (which is not in the repo), so a rebuilt clip will reproduce the
*discrimination* — a correct flip measures ~2 MAE against an ffmpeg-flipped frame
while an unflipped one measures ~110 — but not the exact MAE values in
`docs/HANDOFF.md` §8.

Environment: VideoPad Professional 8.91 (32-bit), display at 150% scaling,
`ffmpeg`/`ffprobe` on PATH. Coordinates in `tools/Export-Project.ps1` are
calibrated for a 1536×817 main window, and the window is **resized to that size**
before clicking — the ribbon scales with DPI, not with window width, so scaling
coordinates alone misses it.

## Driving it from an agent

The repo is built to be operated by an agent rather than by hand, and that part is
documented separately:

- [docs/AGENT-RUNBOOK.md](docs/AGENT-RUNBOOK.md) — the loop, measured costs, a
  failure taxonomy, and the invariants that must not be automated away.
- [agent/tools.json](agent/tools.json) — seven functions with JSON-Schema
  arguments, so you can hand a model a tool list instead of a codebase.
- [agent/system-prompt.md](agent/system-prompt.md) — a paste-ready contract:
  rules, loop, budgets, reporting format.
- [tools/Invoke-AgentStep.ps1](tools/Invoke-AgentStep.ps1) — runs one step in a
  child PowerShell and prints `{ok, exitCode, seconds, stdout, stderr}`.
- [agent/Invoke-PadTool.ps1](agent/Invoke-PadTool.ps1) — fills a manifest
  template and runs it, validating every argument first.

```powershell
.\tools\Invoke-AgentStep.ps1 -Step gate -Command '.\tools\Test-Examples.ps1'
.\agent\Invoke-PadTool.ps1 -Name videopad_build -Arguments @{ spec = 'examples\cut5-cadence.json' }
```

## Not in this repo

The rendered exports (`out/agent-cut-v2.mp4`, 170 MB each) exceed GitHub's
per-file limit, so they are gitignored — as are `out/cut4-effects.mp4`,
`out/cut5-cadence.mp4`, `out/cut6-flip.mp4`, `out/cut7-audio.mp4`,
`out/cut8-audiofade.mp4` and `out/cut9-filters.mp4`, the verified exports behind
the later features. Their
SHA256 is in [docs/HANDOFF.md](docs/HANDOFF.md) §8: both v2 runs produced the
identical file
`FDCA15802A463E3E7D0BF63AFF595E2E76013E8B6D7353891E48D31FB13CB16D`. Everything
needed to regenerate and re-measure them is committed
(`out/oracle/cut*verify.ps1`, `tools/Compare-Vpj.ps1`). The flip/audio exports are
only 1–2 MB, so `git add -f out/cut6-flip.mp4` works if you would rather keep them
than re-render; `cut9-filters.mp4` is 43 MB because grain does not compress.

Also absent by design: the VideoPad installers, the registration backup, scratch
frame dumps, and the source media itself — the `.vpj` stores paths, not media.

