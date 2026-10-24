# Running the pipeline from an agent

This is the operating manual for driving the repo with an autonomous agent,
rather than by hand. It is the same loop this project was built with: v2, v3 and
v4 were each produced by an agent that wrote a spec, compiled it, and then proved
the result against the app.

## 1. What an agent actually needs

Five things, and only the first one is obvious:

1. **A non-interactive entry point.** Every tool is `param()`-based and never
   prompts. `Open-Project.ps1` answers VideoPad's "Damaged File" dialog itself.
2. **A verdict it can branch on.** An object on stdout is not a verdict. Exit 0
   is: failures are `throw`, so they arrive as exit code 1 with a one-line
   reason.
3. **A cheap oracle.** `Test-Examples.ps1` decides most questions in seconds
   with no app running. Without it an agent burns minutes per question and
   learns less.
4. **A map from failure text to action.** VideoPad's failure modes are indirect
   (a dropped file argument, a modal nobody answered). §5 tabulates them, because
   an agent that guesses here loops.
5. **An honest cost model.** The app steps are 10 s to 2 min. An agent that
   knows the price asks fewer, better questions.

## 2. The loop

Run from the repo root. Steps 0, 1 and 5 need no VideoPad at all.

| # | step | command | needs app | measured |
|---|---|---|---|---|
| 0 | **gate** | `.\tools\Test-Examples.ps1` | no | 3 s (13 specs) |
| 1 | **build** | `.\tools\New-Project.ps1 -Spec examples\cut5-cadence.json` | no | 1.4 s |
| 2 | **load** | `.\tools\Open-Project.ps1 -ProjectPath out\cut5-cadence.vpj` | yes | 5.6 s inside, 11.8 s wall |
| 3 | **round-trip** | `.\tools\Watch-Autosave.ps1 -Project out\cut5-cadence.vpj -LogPath out\oracle\cut5-cadence.log` then `.\tools\Compare-Vpj.ps1 -A out\cut5-cadence.vpj -B out\oracle\cut5-cadence.roundtrip.vpj` | yes | ~110 s (waits for the ~100 s autosave timer) |
| 4 | **export** | `.\tools\Export-Project.ps1 -OutputPath out\cut5-cadence.mp4 -ExpectedDurationMs 13500` | yes | 25.8 s for a 13.5 s sequence |
| 5 | **diff** | `.\tools\Compare-Vpj.ps1 -A <spec output> -B <other>` | no | <1 s |

Step 3 is only worth running when a field's *meaning* is in doubt; it is the only
oracle that says "the app's parser kept what I wrote". The gate covers
determinism, the round-trip covers comprehension, the export covers rendering.

Before writing any `effects` entry, ask the registry what is legal — it also lists
each parameter's allowed range, which is what the writer enforces:

```powershell
.\tools\Get-Effects.ps1                       # every name, id, category
.\tools\Get-Effects.ps1 -Name cartoon         # parameters, defaults, ranges
.\tools\Get-Effects.ps1 -Name snow -Skeleton  # paste-ready spec fragment
```

### Adding an effect the registry has not seen

The exe has no id→name table to read, and an id applied at its defaults is often
indistinguishable from no effect at all (only 5 of the 11 uncatalogued ids probed
in `out/cut12-probe` changed the picture), so an id alone proves nothing. The one
authoritative source is the app's own serialisation, which means one manual apply
per effect:

```powershell
.\tools\Start-Capture.ps1
#  it returns once you have applied something and saved; you do two things:
#  click the clip, Video Effects > click the tile, then Ctrl+S
```

`Start-Capture.ps1` rebuilds `out/capture.vpj` from `out/capture.spec.json` (one
4 s clip, no effects), opens it, then watches **both** save paths for up to 5
minutes: a Ctrl+S rewrites the project file, and the app's ~100 s timer rewrites
`%APPDATA%\NCH Software\VideoPad\autosave.vpj`, so pressing Ctrl+S is a
convenience rather than a requirement. Two writes are refused and re-baselined
instead of taken: a save that carries no effects (the app autosaves a project it
has only opened), and an autosave whose sequence is not the capture project's own
(the app autosaves whichever project is open). Of the writes that survive, the
newest wins. On a hit it copies the file aside as `out/capture.captured.vpj`,
prints the `Read-EffectChain` table and returns `Slots` plus `UnknownIds` for a
script to act on. `-KeepExisting` keeps the project as it is, `-NoOpen` skips
launching the app, `-WaitSeconds` changes the timeout.

The table has `clip / slot / id / effect / preset / parameters`, with `?` in the
effect column for an id the registry lacks, and every parameter already decoded
(`w=0.1 r=50 g=100 b=255 s=1`). Three things follow from one row: the id for
`typeN`, the shipped values for `defaults`, and the key names for `params`.

To read a project captured by other means, the reader stands alone:

```powershell
.\tools\Read-EffectChain.ps1 -Project out\capture.vpj -Unknown
```

Applying several effects in one session works too — the app appends to the end of
the clip's chain, so slots `0..N-1` come back in the order applied and
`Read-EffectChain` shows that order, which means five effects cost one save and one
reading. Then, per effect: add the entry, build a probe spec that varies each
parameter, export it, measure the frames, and write the measurements into the
entry's `summary` — that is the standard the `cartoon` and `snow` entries set.

A measured end-to-end run of cut5 (`examples/cut5-cadence.json`, 13 500 ms):

```
build    ok=True s=1.4    DurationMs=13500
load     ok=True s=11.76  Loaded=true  PromptCount=1  ElapsedSeconds=5.6
export   ok=True s=25.82  Verified=true  DurationMs=13534  DurationDeltaMs=34  SizeBytes=2245767
```

Re-exporting that project to a second path produced a **byte-identical** file
(SHA256 `64743BD7…2733B66` both times), so the renderer is deterministic too: a
frame difference means the project differs, not that the encoder wobbled.

## 3. One call, one JSON verdict

`tools/Invoke-AgentStep.ps1` wraps any step so the caller gets a single object
instead of having to read prose:

```powershell
.\tools\Invoke-AgentStep.ps1 -Step gate -Command '.\tools\Test-Examples.ps1'
```

```json
{
  "ok": true, "step": "gate", "exitCode": 0, "timedOut": false, "seconds": 3.13,
  "command": ".\\tools\\Test-Examples.ps1",
  "workDir": "C:\\Users\\user\\Downloads\\videopad",
  "stdout": "All 9 example(s) reproduced byte-identically.\n...",
  "stderr": ""
}
A step that fails looks like this - no prose to parse, one reason line:

```
ok       : False
exitCode : 1
seconds  : 2.37
stderr   : Spec not found: .\examples\missing.json
```

Four details make it usable rather than decorative:

- **Encoded command.** The step travels to the child as a base64
  `-EncodedCommand`, so quotes and `|` cannot be mangled on the way.
- **Clean streams.** A redirected PowerShell normally serialises its whole error
  *and information* streams as CLIXML, which makes a successful step look like a
  failure. The wrapper routes `6>&1` and writes caught errors with
  `[Console]::Error`, so stderr carries only the failure message.
- **`ok` means exit 0** - nothing else. The wrapper never reads stdout to decide.
- **Timeout kills the child** and returns `ok=false, timedOut=true, exitCode=-1`.

Compose it with `ConvertTo-Json` when you want structured data instead of text:

```powershell
.\tools\Invoke-AgentStep.ps1 -Step build -Command '.\tools\New-Project.ps1 -Spec .\examples\cut5-cadence.json | ConvertTo-Json -Depth 5 -Compress'
```

## 4. Hand the model a schema, not a repo

`agent/tools.json` is a function manifest: seven tools, each with the command
template, a JSON-Schema argument list, whether it needs the app, what it costs,
what `ok` means, and what it returns. Two ways to use it:

**Tool-calling loop (OpenAI/Anthropic style).** Map each entry to one function
whose body is `Invoke-AgentStep -Step <name> -Command "<command with {placeholders} filled>"`.
Ship `name`, `description`, `parameters`; keep `command`, `cost`, `needsApp` on
your side.

**MCP server.** One `tools/call` handler that fills the same template and returns
the envelope as JSON text. There is no state to carry between calls: the repo is
the state.

**A filler is included.** `agent/Invoke-PadTool.ps1` does all of the above:

```powershell
.\agent\Invoke-PadTool.ps1 -Name videopad_gate
.\agent\Invoke-PadTool.ps1 -Name videopad_build -Arguments @{ spec = 'examples\cut5-cadence.json' }
.\agent\Invoke-PadTool.ps1 -Name videopad_export -Arguments @{ outputPath = 'out\cut6.mp4'; project = 'out\cut6.vpj'; expectedDurationMs = 9000 }
```

It applies each parameter's `default`, derives the computed arguments
(`videopad_gate`'s `specArgs` from `specs`, `videopad_roundtrip`'s `capture` from
`logPath`), refuses to leave a `{placeholder}` unfilled, and returns the runner's
envelope as an object. `$env:VIDEO_PAD_AGENT='dry'` prints the filled command
instead of running it, which is the cheapest way to debug a template.

**The injection caveat, and what is done about it.** A command template with
model-supplied arguments is a shell string, so `x"; Remove-Item -Recurse /` is a
real risk. The filler refuses any argument containing `;`, `|`, a backtick, a
single or double quote, `$`, parentheses, angle brackets, a newline, or `..` -
every path this pipeline takes is a plain repo-relative name, so a blunt rule
costs nothing:

```powershell
PS> .\agent\Invoke-PadTool.ps1 -Name videopad_build -Arguments @{ spec = 'x"; Remove-Item -Recurse / ;"' }
Argument 'spec' contains characters this pipeline never needs: 'x"; Remove-Item -Recurse / ;"'
```

`videopad_step` is the exception: it interpolates a whole command, so if you
expose it, gate it behind human approval rather than trying to sanitise it.

## 5. Failure taxonomy

Every entry here is a failure this project actually hit. Most of them look like
something else.

| symptom | real cause | what the agent should do |
|---|---|---|
| `Damaged File / Try Load` dialog | the `checksum=` line is stale, by design | nothing - `Open-Project.ps1` answers it. `PromptCount=1` is the healthy value |
| the same dialog reappears dozens of times | the answer was posted to the wrong window (a stacked prompt has no name) | fixed in v4; if you see it, the loader is stale - do not "fix" it with more clicks |
| `Abnormal Termination` / crash-recovery dialog | a previous instance was force-killed | a human dismisses it once. Never kill `videopad.exe` again |
| project opens as "Untitled" | VideoPad is single-instance and silently drops the file argument | close every instance, reload |
| `Loaded=false` with `ElapsedSeconds` ≈ the timeout | a modal is waiting that nobody recognises | check `Modals` in the result before retrying |
| `Export dialog did not appear` | no sequence open, or the ribbon is not on Home | load a project first; the ribbon must be on Home |
| `Export dialog did not appear`, but a sequence *is* open | another window is covering the editor, so the synthetic clicks land on it | keep VideoPad on top while the clicks run (`SetWindowPos … HWND_TOPMOST`), or clear the desk |
| a detached driver wrote no verdict and the mp4 appeared in `Videos` | the caller's timeout killed the process tree, taking the move-and-verify step with it | poll from a separate short call; never sleep past the harness cap in the command that launched the driver |
| export produced nothing, timeout hit | still encoding, or the encode failed on a missing media file | check the media paths resolve (the `.vpj` stores paths, not media) |
| writer: `cannot open output ... file locked` | the target `.vpj` is open in the editor or held by a `.vbk` backup | close the lock, or write to a new path |
| writer: `out ... beyond the media at speed` | the spec asked for more source than exists | shorten or split the segment; the app would have silently clamped and desynced the rest |
| writer: `unknown effect` | typo or invented name | read `tools/effects.json` |
| writer: `ffprobe is not on PATH` | adding media needs a duration | put `"duration"` (ms) on the media entry |
| writer: `media ... has no audio stream` | added media is always an A/V pair | use a file with audio |
| gate: `changed` | the writer or a committed `.vpj` moved | stop: investigate before anything else |

## 6. What must never be automated away

These are the invariants that make the results mean anything:

- **Never hand-edit a `.vpj`.** Unknown fields survive only because the writer
  edits the template in place. A regex agent will delete the future.
- **Never repair the checksum.** "Damaged File / Try Load" is the cheap path that
  made this whole project possible; reproducing NCH's hash is a rabbit hole.
- **Never force-kill VideoPad.** A killed instance arms crash recovery, which
  drops the next file argument - the failure then looks like a corrupt project.
- **Never edit an example or a `.vpj` to make a check pass.** They are evidence.
- **Never claim verification without naming the oracle.** "It built" means the
  bytes were written. Only the round-trip says the app understood them, and only
  frame MAE says the pixels match.
- **Never run two app steps at once.** One desktop, one instance, one stream of
  synthetic input.

## 7. The system prompt

`agent/system-prompt.md` is a ready-to-paste contract: the seven tools, the loop,
the budgets, the failure mapping, and the reporting format (verdict first, then
the evidence, then what is unverified). It also has two variations:

- **Writer development** - gate + diff only, no app. That is how v2→v4 were
  built; the app was consulted only for genuinely unknown field semantics.
- **Discovery mode** - when a field's meaning is unknown, write a probe the way
  `out/oracle/v4-probe/` does: one variant per candidate value, one round-trip,
  one export. Record the dead ends; three of v4's four audio candidates were
  inert, and that negative result is the most useful part of the finding.

## 8. Adding a tool

Three places, in order, and the third is what makes it real:

1. The script in `tools/` with comment-based help and `$ErrorActionPreference='Stop'`.
2. `agent/tools.json`: `name`, `description` (say what `ok` means), `command`
   template, `parameters`, `cost`, `needsApp`.
3. A line in `docs/HANDOFF.md` §4 and a `Test-Examples`-style check if it can be
   exercised without the app. A tool nobody can cheaply re-run is a rumour.
