# Run it, step by step

Written for someone who has never opened PowerShell. Every step is: **copy the
grey box, paste it, press Enter, wait.** The computer prints something back — the
step tells you what it should say.

Three rules for the whole page:

1. **Don't touch the mouse or keyboard while a step is running.** Some steps move
   a fake mouse around VideoPad. If you click into another window, VideoPad hides
   behind it and the fake clicks hit the wrong thing.
2. **Don't open VideoPad yourself.** The scripts start it and close it as needed.
3. **If you see red text, stop** and read the "when it goes wrong" table at the
   bottom. Don't re-run things at random.

---

## Step 0 — open a terminal

Press the **Windows key**, type `powershell`, press **Enter**. A blue-ish window
appears with a `PS C:\Users\user>` prompt. That's it. You type here.

## Step 1 — go to the project folder

```powershell
cd C:\Users\user\Downloads\videopad
```

The prompt changes to `PS C:\Users\user\Downloads\videopad>`. If it says *"Cannot
find path"*, the folder isn't there — stop and ask where it went.

From now on, **every command starts with `.\`** (dot backslash). That means "run
the thing in this folder". Forget the dot and PowerShell says it doesn't recognise
the command.

## Step 2 — check the tools work (3 seconds, no video app)

```powershell
.\tools\Test-Examples.ps1
```

You will see thirteen little blocks like `Spec : cut1.json ... Result : identical`,
and then, as the last line:

```
All 9 example(s) reproduced byte-identically.
```

(The count follows whatever is in `examples/` — add your own spec and it becomes
`All 10 example(s)…`.)

**That is the whole health check.** If that line appears, the editing engine works
and you can trust everything after it. If you get red text instead, stop.

## Step 3 — build a project file (2 seconds)

```powershell
.\tools\New-Project.ps1 -Spec examples\cut5-cadence.json
```

You should see:

```
Output       : C:\Users\user\Downloads\videopad\out\cut5-cadence.vpj
DurationMs   : 13500
SegmentCount : 4
```

You just created `out\cut5-cadence.vpj` — a real VideoPad project, made from a
13-line text file. You can double-click it in File Explorer and VideoPad will open
the edit. Nothing has been rendered yet.

## Step 4 — let the computer open it in VideoPad (15 seconds)

```powershell
.\tools\Open-Project.ps1 -ProjectPath out\cut5-cadence.vpj
```

VideoPad opens by itself. A small box may ask *"Damaged File / Try Load"* — the
script answers it, so don't touch anything. Then you should see:

```
Loaded         : True
PromptCount    : 1
ElapsedSeconds : 5.6
```

`Loaded : True` means the project is really open in the app, with 4 clips on the
timeline.

> If VideoPad was already open, this step closes it politely first and then
> reopens it. That is normal — you'll see the window disappear and come back.
>
> If the title bar ends in **`Untitled.vpj`** instead of `cut5-cadence.vpj`, the
> app dropped the file name while it was starting up. Nothing is broken — run the
> same command again and it will load.


## Step 5 — make the video (about 30 seconds)

```powershell
.\tools\Export-Project.ps1 -OutputPath out\my-first.mp4 -ProjectPath out\cut5-cadence.vpj -ExpectedDurationMs 13500
```

VideoPad presses its own Export buttons, encodes, and when it is done you see:

```
OutputPath         : C:\Users\user\Downloads\videopad\out\my-first.mp4
SizeBytes          : 2245767
DurationSeconds    : 13.534
DurationMs         : 13534
ExpectedDurationMs : 13500
DurationDeltaMs    : 34
SourceFile         : C:\Users\user\Videos\Cadence Test.mp4
Verified           : True
Message            : Exported; duration within one frame of the expected 13500 ms.
```

Three things to look at:

- **`Verified : True`** — the video that came out is the length you asked for
  (34 thousandths of a second off, which is one frame).
- **`out\my-first.mp4` exists** — that's your video. Double-click it and it plays.
- **`SourceFile` in `C:\Users\user\Videos`** — VideoPad always renders there first;
  the script moves it to where you asked and cleans up. If you ever interrupt an
  export, that folder is where the half-finished file will be.

A 4-minute video takes about 8 minutes to encode; the number on the right of your
screen doesn't move, so just wait. It is working.

## Step 6 — check it yourself, without trusting me

```powershell
ffprobe -v error -show_entries format=duration -of default=nw=1 out\my-first.mp4
```

```
duration=13.534334
```

13.5 seconds. That's the number the recipe asked for.

## Step 7 — the everyday version

Nine times out of ten you only need these two, and they take 4 seconds total:

```powershell
.\tools\New-Project.ps1 -Spec examples\cut1.json
.\tools\Test-Examples.ps1
```

Build the project, confirm nothing broke. Open and export only when you actually
want a video file.

## Step 8 — make *your* edit instead

1. Copy a recipe and rename it:

```powershell
Copy-Item examples\cut3-addmedia.json examples\my-edit.json
```

2. Open it in Notepad:

```powershell
notepad examples\my-edit.json
```

3. Change three things: `"output"` (where the project file goes), `"sequenceName"`
   (the name you'll see in VideoPad), and the numbers in `"segments"` — `start` and
   `end` are milliseconds from the start of that clip, so `0` to `6000` is the
   first 6 seconds.

4. To use your own footage, put the file here first:

```powershell
Copy-Item "C:\path\to\your\clip.mp4" out\testmedia\yourclip.mp4
```

   then in the recipe's `"media"` block use:

```json
{ "id": "mine", "path": "../out/testmedia/yourclip.mp4" }
```

   and in `"segments"` use `"source": "mine"`. The clip **must have sound** — a
   silent video is refused on purpose rather than guessed at.

5. Save, close Notepad, and build it:

```powershell
.\tools\New-Project.ps1 -Spec examples\my-edit.json
```

If it prints `Output ... DurationMs ...` you're good: open it and export it with
the two commands from steps 4 and 5, using your own file names.

## Step 9 — when it goes wrong

| you see | what it means | do this |
|---|---|---|
| `cannot be loaded because running scripts is disabled` | Windows is blocking scripts | run `powershell -ExecutionPolicy Bypass -File .\tools\Test-Examples.ps1` instead |
| VideoPad opens but the title says **Untitled** | another VideoPad beat it to the file | close all VideoPad windows, run step 4 again |
| `Export dialog did not appear` | something is covering VideoPad, so the fake clicks missed | bring VideoPad to the front, then run step 5 again |
| VideoPad asks **"Did VideoPad hang or crash when last run?"** | something force-killed the app (an editor timeout counts) | click **Something Else** — it was not a real crash — then run the step again |
| red text mentioning `Spec not found` | typo in the file name you passed | check the path after `-Spec` |
| nothing seems to happen for minutes | it's encoding a long video | wait; check `out\` for a growing mp4 |
| the Video Effects list won't scroll with two-finger swipe on a trackpad | VideoPad's effect grid only honours a real wheel or its scrollbar; a precision touchpad's gesture never reaches it | drag the scrollbar, or use a mouse wheel, or click once in the grid and press **Page Down** — maximising the window also fits every tile without scrolling |

## Step 10 — what to say to an AI agent next time

> Work in `C:\Users\user\Downloads\videopad`. Read `RUN-IT.md`, then
> `docs/AGENT-RUNBOOK.md`. Write my edit as a recipe in `examples\`, build it with
> `tools\New-Project.ps1`, run `tools\Test-Examples.ps1`, then open and export.
> Tell me the `DurationDeltaMs` and whether `Verified` is true.

Then describe the edit in normal words ("cut the first 20 seconds, speed the middle
part up, fade out at the end").

