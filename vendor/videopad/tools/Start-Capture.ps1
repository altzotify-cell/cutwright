<#
.SYNOPSIS
    One command for a manual effect capture: fresh project, wait, read back.

.DESCRIPTION
    Learning an uncatalogued effect needs one manual apply in VideoPad - the app is
    the only place the id and its name appear together. This automates everything
    around that single human action:

      1. rebuilds out\capture.vpj from out\capture.spec.json (one clip, no effects)
      2. opens it in VideoPad
      3. waits for the project to come back changed - either a Ctrl+S (the file
         itself) or the app's ~100 s autosave timer (autosave.vpj)
      4. copies that file aside, then prints Read-EffectChain's table so the id,
         the preset name and every decoded parameter are right there

    So the whole protocol is: run this, click the effect tiles you want, press
    Ctrl+S. The window returns with a table; ids showing '?' are the ones worth
    adding to tools\effects.json.

    Applying several effects before saving is fine: the app appends them to the
    clip's chain, so they arrive as slots 0..N-1 in the order applied.

.PARAMETER WaitSeconds
    How long to wait for the save. Default 300 (5 minutes).

.PARAMETER Spec
    The one-clip spec to rebuild from. Default out\capture.spec.json.

.PARAMETER KeepExisting
    Do not rebuild the project first (capture into whatever is on disk).

.PARAMETER NoOpen
    Do not launch VideoPad. Use when the app is already showing the capture
    project, or when a save arrived by other means - it also makes the wait loop
    testable without touching the app.

.OUTPUTS
    PSCustomObject: Built, Loaded, Source ('save' | 'autosave'), SavedAt,
    Seconds, Slots, UnknownIds, Captured

.EXAMPLE
    .\Start-Capture.ps1
    # then in VideoPad: select the clip, Video Effects > click a tile, Ctrl+S
#>
[CmdletBinding()]
param(
    [int]$WaitSeconds = 300,
    [string]$Spec,
    [switch]$KeepExisting,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $Spec) { $Spec = Join-Path $root 'out\capture.spec.json' }
if (-not (Test-Path -LiteralPath $Spec)) { throw "Capture spec not found: $Spec" }
$Spec = (Resolve-Path -LiteralPath $Spec).Path

$json = Get-Content -LiteralPath $Spec -Raw | ConvertFrom-Json
$project = $json.output
if (-not [IO.Path]::IsPathRooted($project)) {
    $project = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $Spec) $project))
}
$captured = [IO.Path]::ChangeExtension($project, '.captured.vpj')
$autosave = Join-Path $env:APPDATA 'NCH Software\VideoPad\autosave.vpj'
$seqName = $json.sequenceName

if (-not $KeepExisting) {
    $build = & (Join-Path $PSScriptRoot 'New-Project.ps1') -Spec $Spec
    "rebuilt : $project ($($build.DurationMs) ms, $($build.EffectCount) effects)"
} else {
    "keeping : $project"
}

# Both save paths are watched: Ctrl+S rewrites the project, the timer rewrites
# autosave.vpj. Autosave can be *newer* than a save made 90 s earlier, so the
# newest of the two wins rather than whichever fired first.
function Get-Stamp([string]$Path) {
    if ($Path -and (Test-Path -LiteralPath $Path)) { return (Get-Item -LiteralPath $Path).LastWriteTimeUtc }
    return [datetime]::MinValue
}

# A save that carries no effects is not a capture - the app autosaves a project
# it has merely opened, which would otherwise look like success.
function Get-EffectCount([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return 0 }
    $text = [IO.File]::ReadAllText($Path)
    return ([regex]::Matches($text, '&type0=')).Count
}

# autosave.vpj holds whichever project the app has open, so it only counts when it
# is ours - recognised by the sequence name the spec asked for.
function Test-IsCapture([string]$Path) {
    if (-not $seqName) { return $true }
    return ([IO.File]::ReadAllText($Path)).Contains("&name=$seqName&")
}

$projectStamp = Get-Stamp $project
$autosaveStamp = Get-Stamp $autosave

$open = $null
if ($NoOpen) {
    'opened  : skipped (-NoOpen)'
} else {
    $open = & (Join-Path $PSScriptRoot 'Open-Project.ps1') -ProjectPath $project -TimeoutSeconds 45
    "opened  : Loaded=$($open.Loaded) prompts=$($open.PromptCount) in $($open.ElapsedSeconds)s - title '$($open.Title)'"
}
''
'Now, in VideoPad: click the clip on the timeline, open Video Effects, click the'
"tile(s) you want, then press Ctrl+S. Waiting up to $WaitSeconds s ..."

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$hit = $null
while ($sw.Elapsed.TotalSeconds -lt $WaitSeconds) {
    Start-Sleep -Seconds 2
    $seconds = [int]$sw.Elapsed.TotalSeconds
    $candidates = @()

    foreach ($c in @(
        @{ Path = $project;  Source = 'save';     Baseline = $projectStamp },
        @{ Path = $autosave; Source = 'autosave'; Baseline = $autosaveStamp }
    )) {
        $stamp = Get-Stamp $c.Path
        if ($stamp -le $c.Baseline) { continue }

        # Another project's autosave, or a save with nothing applied yet. Both are
        # re-baselined so they are reported once rather than every two seconds.
        if ($c.Source -eq 'autosave' -and -not (Test-IsCapture $c.Path)) {
            "  ($($c.Source) at ${seconds}s belongs to another project - ignored)"
            $autosaveStamp = $stamp
            continue
        }
        if ((Get-EffectCount $c.Path) -eq 0) {
            "  ($($c.Source) at ${seconds}s: no effects yet, still waiting)"
            if ($c.Source -eq 'save') { $projectStamp = $stamp } else { $autosaveStamp = $stamp }
            continue
        }

        $candidates += , @{ Path = $c.Path; Source = $c.Source; Stamp = $stamp }
    }

    if ($candidates.Count -eq 0) { continue }
    $hit = @($candidates | Sort-Object { $_.Stamp } -Descending)[0]
    break
}
$sw.Stop()

if (-not $hit) {
    Write-Warning "Nothing changed in $WaitSeconds s - no capture. (Was the effect applied to a clip that has one?)"
    return
}

# The app writes the file in one go, but give a slow write a moment to finish.
Start-Sleep -Milliseconds 400
Copy-Item -LiteralPath $hit.Path -Destination $captured -Force
"captured: $($hit.Source) after $([int]$sw.Elapsed.TotalSeconds)s -> $captured"
''

$rows = @()
$jsonText = (& (Join-Path $PSScriptRoot 'Read-EffectChain.ps1') -Project $captured -Json) -join "`n"
if ($jsonText.Trim()) {
    # Assign before wrapping: Windows PowerShell's ConvertFrom-Json emits a
    # top-level array as one object, so @($json | ConvertFrom-Json) collapses to
    # a single element. @($parsed) enumerates the array properly.
    $parsed = $jsonText | ConvertFrom-Json
    $rows = @($parsed)
}
$unknown = @($rows | Where-Object { $_.Effect -eq '?' } | ForEach-Object { $_.Id } | Sort-Object -Unique)

# The reader's own table, straight from the captured file.
& (Join-Path $PSScriptRoot 'Read-EffectChain.ps1') -Project $captured

[pscustomobject]@{
    Built      = (-not $KeepExisting)
    Loaded     = $(if ($open) { [bool]$open.Loaded } else { $null })
    Source     = $hit.Source
    SavedAt    = $hit.Stamp
    Seconds    = [int]$sw.Elapsed.TotalSeconds
    Slots      = $rows.Count
    UnknownIds = $unknown
    Captured   = $captured
}
