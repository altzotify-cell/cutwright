# Start here — what this does, in plain English

Normally you edit a video by hand: open VideoPad, drag clips onto the timeline,
cut, add effects, press Export, wait, get an `.mp4`. That works. It is also slow,
and doing the *same* edit fifty times is unbearable.

This repo does that part for you. You write the edit down as a **short text
recipe**, and scripts do the rest:

```
your recipe (.json)  →  script writes the project file  →  VideoPad opens it  →  VideoPad exports the .mp4
```

Nobody clicks anything. You can go and make coffee.

## 1. What you write

A recipe is a small JSON file. This is `examples/cut1.json`, in full:

```json
{
  "template": "probe.vpj",
  "output": "../out/cut1.vpj",
  "sequenceName": "Agent Cut",
  "segments": [
    { "source": 1, "start": 0,     "end": 90000 },
    { "source": 0, "start": 60000, "end": 180000 }
  ]
}
```

Read it as: *use clip #1 from 0:00 to 1:30, then clip #0 from 1:00 to 3:00, call
the sequence "Agent Cut", save it as `out/cut1.vpj`.* That is 210 seconds of
video made from two pieces of two files — and building it takes about 1.4 s.

Optional per cut, when you want more than a straight cut:

| field | meaning | example |
|---|---|---|
| `speed` | play faster or slower | `2` = double speed, `0.5` = half |
| `flip` | mirror the picture: `horizontal` = left↔right, `vertical` = upside down, `both`, `none` | `"horizontal"` |
| `audioGainDb` | change one clip's volume, in dB (attenuation only) | `-6` = half amplitude; boosts are refused because the exporter already normalises to full scale |
| `audioFadeIn` / `audioFadeOut` | fade this clip's own sound (ms) | `400` — separate from `fadeIn`/`fadeOut`, which fade the picture |
| `fadeIn` / `fadeOut` | fade the picture (ms) | `250` |
| `effects` | video effect with optional fine-tuning, names and parameter keys from `tools/effects.json` | `[{ "name": "noise", "params": { "intensity": 30, "coverage": 60 } }]` — out-of-range values are refused, not clamped |
| `mute` | silence this cut | `true` |

One field sits at the top of the spec instead of on a cut: `"dropUnusedMedia":
true` throws away bin entries (and their effect chains) that no clip uses, so a
built project does not carry the template's own footage around with it. See
`examples/cut13-dropmedia.json`.
| `media` | introduce a new file to cut from | `[{ "id": "bars", "path": "…" }]` |

## 2. The three steps

| step | command | what it does | time | VideoPad open? |
|---|---|---|---|---|
| build | `.\tools\New-Project.ps1 -Spec examples\cut1.json` | writes the project file | 1.4 s | no |
| open | `.\tools\Open-Project.ps1 -ProjectPath out\cut1.vpj` | launches VideoPad and loads it, answering its dialogs | 6–12 s | it starts it |
| export | `.\tools\Export-Project.ps1 -OutputPath out\cut1.mp4 -ExpectedDurationMs 210000` | renders the mp4 | ~2× the video length | yes |

Step 1 is instant and repeatable — that is where you iterate. Steps 2 and 3
actually drive the real application, so they need the desktop and cannot run two
at a time.

## 3. Try it right now (no VideoPad needed, ~3 s)

```powershell
.\tools\New-Project.ps1 -Spec examples\cut1.json
.\tools\Test-Examples.ps1
```

The second command rebuilds every example in `examples/` and compares the output
to the file committed in `out/`. It prints:

```
All 9 example(s) reproduced byte-identically.
```

That sentence is the thing to care about: it means the recipe→project step is
deterministic. Same recipe, same bytes, every time.

## 4. Try it with the real app (~40 s)

```powershell
.\tools\New-Project.ps1 -Spec examples\cut5-cadence.json
.\tools\Open-Project.ps1 -ProjectPath out\cut5-cadence.vpj
.\tools\Export-Project.ps1 -OutputPath out\cut5.mp4 -ProjectPath out\cut5-cadence.vpj -ExpectedDurationMs 13500
```

`cut5` is the show-off example: 4 cuts from one clip, at 2× speed, 0.5× speed,
with fades, and a mirror effect on the last one. It is 13.5 s of video and it
exports in about 26 s to a 2.2 MB mp4.

## 5. What comes out

| file | what it is |
|---|---|
| `out/*.vpj` | the project file — double-click it and VideoPad opens the edit by hand, exactly as the script made it |
| `out/*.mp4` | the rendered video |

Nothing is fake or simulated. `out/cut5-cadence.mp4` is a normal 1080p mp4 that
plays in any player.

## 6. How do you know it got it right?

Three separate questions, three separate checks. This is the part that makes the
whole thing trustworthy:

1. **Is the project file stable?** Build the same recipe twice, compare the bytes.
   Identical means the writer is deterministic — `Test-Examples.ps1` says
   "byte-identically" for all 9 examples.
2. **Did VideoPad understand the file?** Open it in the app, make the app save its
   own copy, then diff the two. Only a handful of fields differ (thumbnail cache
   and the like), which means the app read what was written rather than silently
   repairing it.
3. **Is the video right?** VideoPad writes a duration into the mp4; compare it
   with what the recipe asked for. The real numbers: **6 ms** off for cut1,
   **19 ms** for cut4, **34 ms** for cut5 (13 500 ms requested → 13 534 ms
   produced). For cut3 and cut4 the actual pixels were also compared against the
   source clips.

Measured on this machine, the same recipe rendered twice gives a **byte-identical
mp4** (`64743BD7…2733B66`), so a difference in the picture means the *project*
changed — not that the encoder was having a bad day.

## 7. Words the other docs use

| word | plain meaning |
|---|---|
| **recipe / spec** | the small JSON file you write — the edit you want |
| **`.vpj`** | VideoPad's project file (XML). The thing you'd normally get from "Save Project" |
| **writer** | the script that turns a recipe into a `.vpj` |
| **template** | an existing empty-ish `.vpj` the writer copies and edits, so unknown settings survive |
| **clip / segment** | one piece of video on the timeline |
| **handle** | VideoPad's internal record for "this piece of media, used here" |
| **effect chain** | the list of effects applied to one clip |
| **round-trip** | open in VideoPad → let it save → compare. Proves the app agreed with us |
| **export** | render the timeline to an mp4 |
| **gate** | `Test-Examples.ps1`, the fast offline check (3 s) |
| **oracle** | whatever you trust to decide "is it correct?" — a re-save, a duration, a pixel comparison |
| **MAE** | mean absolute error — average pixel difference between two frames |

## 8. What it cannot do yet

Straight answers, no hedging:

| missing | what that means today |
|---|---|
| **transitions** (crossfades, wipes) | clips butt up against each other; a fade to black is possible, a crossfade is not |
| **titles / text** | the Add Text button is not automated; put text on in your editor afterwards |
| **audio volume / pan** | per-clip volume works in dB (`audioGainDb`, attenuation only) and clips can have their sound faded (`audioFadeIn`/`audioFadeOut`); panning does not, and there is no second audio track for music |
| **silent video** | a source with no audio track is refused, not silently mishandled |
| **more than one video track, or a second sequence** | one video track, one audio track, one sequence |
| **choosing the export preset** | it uses whatever the project says (1080p mp4); no "pick 720p" step |
| **typing the output filename** | handled by moving the file after export instead of typing in the dialog |

## 9. Asking an agent to do it

Paste this, then describe the edit you want in normal words:

> Work in `C:\Users\user\Downloads\videopad`. Read `START-HERE.md`, then
> `docs/AGENT-RUNBOOK.md`. To make an edit: write a recipe in `examples/`, run
> `tools\New-Project.ps1` on it, then `tools\Test-Examples.ps1` (3 s, no app), and
> only then `tools\Open-Project.ps1` + `tools\Export-Project.ps1`. Never hand-edit a
> `.vpj`. Report the duration delta from the export, not "it worked".

The agent will do it the same way I did: recipe → build → check → open → export →
report the measured numbers.

## 10. When it goes wrong

| what you see | what it means | fix |
|---|---|---|
| VideoPad opens but the project is called **"Untitled"** | another VideoPad was already running; it quietly ignored the file | close every VideoPad and run it again |
| a **"Damaged File / Try Load"** question | normal — this pipeline writes a checksum the app does not trust | answer it once; `Open-Project.ps1` does this for you |
| the export never starts, or clicks seem to hit nothing | something is covering the VideoPad window (another app in front) | keep VideoPad on top, or move windows aside |
| the mp4 appears in `C:\Users\user\Videos` instead of `out\` | the render finished but the cleanup step was killed mid-run | copy it out of `Videos`, or re-run the export |

