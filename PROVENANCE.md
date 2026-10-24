# Provenance

Cutwright is a fork. This file records exactly what came from where, so the
originals never have to be trusted or touched again.

## Sources (read only, never modified)

| what | path | role |
|---|---|---|
| RecapStudio v2 | `C:\Users\user\Downloads\RecapStudio_v2_ui_videopad\RecapStudio_v2_ui` | engine + web UI + project template |
| videopad | `C:\Users\user\Downloads\videopad` | VideoPad automation research + tooling |

## What was copied

Code and text only, into `vendor/`. 89 files, 0.68 MB total.

**From RecapStudio** (42 files) -- `RecapStudio\**` filtered to
`.py .bat .json .md .txt .html .js .css .csv .vpj`, excluding `Projects\`
entirely:

* `_template\recap.py` (127 KB) -- the engine whose conventions this fork follows
* `studio.py`, `web\*` -- the local web UI
* every `.bat` step script, `config.json`, `project.json`, `segments.json`
* the `PASTE_THIS_TO_CLAUDE*.txt` prompt files

**From videopad** (47 files) -- `agent\`, `docs\`, `examples\`, `tools\`, root
`*.md`, excluding `.git\`, `out\`, `logs\`:

* `docs\HANDOFF.md`, `docs\vpj-format-findings.md`, `docs\AGENT-RUNBOOK.md`
* `tools\*.ps1`, `tools\NativeInput.cs`, `tools\effects.json`
* `examples\cut*.json` -- the recorded VideoPad command shapes

## What was deliberately NOT copied

* **All media.** 334 `.mp4`, 1 `.mkv`, 301 `.mp3`, 298 `.wav`, 35 `.srt`,
  24 `.ass` -- that is ~5.3 GB of footage, audio and subtitles. Source media is
  referenced by absolute path and read only.
* **`keys.env`** -- API keys. Not copied, not read into this fork.
* **`*.exe`** -- the bundled VideoPad installers (~6 MB).
* **`.git\`** -- history belongs to the original.
* **`Projects\`** -- per-project data, not code.
* **`out\`, `logs\`** -- generated artifacts.

## Manifest

`vendor\MANIFEST.sha256` holds a SHA256 for every vendored file, in
`hash  relative\path` form (relative to `vendor\`).

Verify the vendored tree against the manifest:

```powershell
cd C:\Users\user\Desktop\Cutwright
Get-Content vendor\MANIFEST.sha256 | ForEach-Object {
    $hash, $rel = $_ -split '  ', 2
    $now = (Get-FileHash (Join-Path 'vendor' $rel) -Algorithm SHA256).Hash.ToLower()
    if ($now -ne $hash) { "CHANGED: $rel" }
}
```

Verify the originals still match what was copied (proves nothing was altered in
either direction):

```powershell
$v = 'C:\Users\user\Desktop\Cutwright\vendor'
$m = 0
foreach ($p in @(@('recapstudio','C:\Users\user\Downloads\RecapStudio_v2_ui_videopad\RecapStudio_v2_ui'),
                 @('videopad','C:\Users\user\Downloads\videopad'))) {
  $dir = Join-Path $v $p[0]
  Get-ChildItem $dir -Recurse -File | ForEach-Object {
    $src = Join-Path $p[1] $_.FullName.Substring($dir.Length + 1)
    if ((Test-Path $src) -and
        ((Get-FileHash $_.FullName).Hash -ne (Get-FileHash $src).Hash)) { $m++ }
  }
}
"mismatches: $m"
```

## Binaries and models (installed here; not from the originals)

`vendor\MANIFEST.sha256` covers code and text only. These are executables and
weights, downloaded from their publishers and checked against the publisher's
own digest before first use:

| what | lives in | bytes | sha256 | checked against |
|---|---|---|---|---|
| whisper.cpp 1.9.5, Windows x64 build | `bin\whisper\Release\` (`whisper-cli.exe` + DLLs) | 8,928,640 (the zip, kept at `bin\_dl\whisper-bin-x64.zip`) | `6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb` | GitHub's own `digest` for that release asset |
| `ggml-small.en.bin` (whisper small, English, f16) | `models\ggml-small.en.bin` | 487,614,201 | `c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d` | the file's HuggingFace LFS pointer `oid` |
| Shotcut 26.9.27, Windows x64 portable | `shotcut\Shotcut\` (4633 files, 521.7 MB; `melt.exe`, `shotcut.exe`, `ffmpeg.exe`, MLT plugins) | 213,335,062 (the zip, kept at `bin\_dl\shotcut-win64-26.9.27.zip`) | `1f8c50ce7b125a2f0dcb60777b358e86baf03b8515982612b6adae10a83d93a5` | GitHub's own `digest` for that asset **and** the release's `sha256sums.txt` -- two independent copies agree |

Sources:

```
https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip
https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin
https://github.com/mltframework/shotcut/releases/download/v26.9.27/shotcut-win64-26.9.27.zip
https://github.com/mltframework/shotcut/releases/download/v26.9.27/sha256sums.txt
```

**What the Shotcut bundle actually contains** (checked by running it, not by
reading folder names): `melt.exe` reports `melt.exe 7.41.0`, `-query filters`
lists 674 filters, `-query transitions` lists 59, `-query producers` lists 42
(including `avformat`), and the MLT plugins sit in `shotcut\Shotcut\lib\mlt\`
(26 DLLs) behind `libmlt-7.dll` / `libmlt++-7.dll`. `shotcut.exe` carries
product version **26.9.27** in its own version resource; `melt.exe` has no
version resource at all, so 7.41.0 comes from asking the binary. Reading the
resource is how `build` stamps every project with the Shotcut that will open it
rather than with a constant.
It also bundles its own `ffmpeg.exe`, `ffprobe.exe` and a newer `whisper-cli.exe`
that offloads to Vulkan (`ggml_vulkan: Found 1 Vulkan devices: Intel(R) UHD
Graphics 620`). Cutwright does **not** use that second whisper build: it needs
`--version` to identify itself and this one rejects the flag, and the CPU build
in `bin\whisper` is the one with a recorded hash. It stays a possible speedup for
later.

**The first project this fork wrote** with that build:

| file | bytes | sha256 | note |
|---|---|---|---|
| `projects\demo_cuts\demo_cuts.mlt` | 4,724 | `4234355fdfdb4a6f6f788eec5efb0c502caa9eaec845f89a713039e5b24fe49e` | 3 clips from `testclips\part1_1_60-120.mp4`, 311 frames, Shotcut 26.9.27 / MLT 7.41.0 recorded inside. Two independent builds of the same plan are byte-identical, so the hash is a real fingerprint of the edit |

Re-verify at any time:

```powershell
cd C:\Users\user\Desktop\Cutwright
(Get-FileHash 'models\ggml-small.en.bin' -Algorithm SHA256).Hash.ToLower()
(Get-Item 'models\ggml-small.en.bin').Length          # 487614201
(Get-FileHash 'bin\_dl\whisper-bin-x64.zip' -Algorithm SHA256).Hash.ToLower()
(Get-FileHash 'bin\_dl\shotcut-win64-26.9.27.zip' -Algorithm SHA256).Hash.ToLower()
(Get-Item 'bin\_dl\shotcut-win64-26.9.27.zip').Length # 213335062
& 'shotcut\Shotcut\melt.exe' --version                # melt.exe 7.41.0
```

**Why the b5454 nightly and not the v1.9.5 tag:** the v1.9.5 release ships no
binary assets at all (`assets: []`); its notes point at build `b5454`. That
build's `target_commitish` is `d1be6fde`, the same commit v1.9.5 names, and the
binary reports `whisper.cpp version: 1.9.5` when asked. So this is the official
Windows build of the stable release, not a different version.

Re-verify at any time:

```powershell
cd C:\Users\user\Desktop\Cutwright
(Get-FileHash 'models\ggml-small.en.bin' -Algorithm SHA256).Hash.ToLower()
(Get-Item 'models\ggml-small.en.bin').Length          # 487614201
(Get-FileHash 'bin\_dl\whisper-bin-x64.zip' -Algorithm SHA256).Hash.ToLower()
```

## Fork policy

* One-way. Code flows out of the originals into this fork. Nothing flows back.
* If a vendored file is changed here to fix a bug, note it in this file -- do not
  silently diverge.
* The originals stay on disk untouched so both pipelines keep working while this
  one is proven.
