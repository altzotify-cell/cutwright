<#
.SYNOPSIS
    Opens a project, then waits for VideoPad to rewrite its autosave file and
    reports what the app's own serializer emitted.

.DESCRIPTION
    VideoPad re-serializes its in-memory project model to
    %APPDATA%\NCH Software\VideoPad\autosave.vpj on a periodic timer (~100 s).
    That file is an independent dump of what the parser actually absorbed, so
    it is the cheapest ground truth available: no Export, no UI Automation
    (all VideoPad controls are unnamed Panes with no InvokePattern).

    Writes a line-oriented log and copies the captured autosave next to it.

.PARAMETER Project
    .vpj to open.

.PARAMETER LogPath
    Log file to write. The captured autosave is saved alongside as
    '<LogBaseName>.roundtrip.vpj'.

.PARAMETER TimeoutSeconds
    How long to wait for the autosave to refresh.
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = 'Stop'
$Autosave = Join-Path $env:APPDATA 'NCH Software\VideoPad\autosave.vpj'
$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log([string]$m) {
    Add-Content -LiteralPath $LogPath -Value ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m)
}

Set-Content -LiteralPath $LogPath -Value '=== autosave watcher ==='

$before = [datetime]::MinValue
if (Test-Path -LiteralPath $Autosave) { $before = (Get-Item -LiteralPath $Autosave).LastWriteTime }
Write-Log ("target      : $Project")
Write-Log ("autosave pre: {0:HH:mm:ss}" -f $before)

$r = & (Join-Path $PSScriptRoot 'Open-Project.ps1') -ProjectPath $Project -TimeoutSeconds 45
Write-Log ("open        : Loaded={0} prompts={1} in {2}s" -f $r.Loaded, $r.PromptCount, $r.ElapsedSeconds)
if (@($r.Modals).Count -gt 0) { Write-Log ("modals      : {0}" -f (@($r.Modals) -join '; ')) }
Write-Log ("title       : {0}" -f $r.Title)

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$refreshed = $false
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    Start-Sleep -Seconds 3
    if (-not (Test-Path -LiteralPath $Autosave)) { continue }
    $now = (Get-Item -LiteralPath $Autosave).LastWriteTime
    if ($now -gt $before) {
        $refreshed = $true
        Write-Log ("autosave new: {0:HH:mm:ss} (after {1}s)" -f $now, [int]$sw.Elapsed.TotalSeconds)
        break
    }
}
$sw.Stop()

if (-not $refreshed) {
    Write-Log 'RESULT      : TIMEOUT - autosave never refreshed'
    Add-Content -LiteralPath $LogPath -Value '=== done ==='
    return
}

$capture = Join-Path $logDir (([IO.Path]::GetFileNameWithoutExtension($LogPath)) + '.roundtrip.vpj')
Copy-Item -LiteralPath $Autosave -Destination $capture -Force
$text = [IO.File]::ReadAllText($Autosave)

$seqName = [regex]::Match($text, '(?m)^h=\d+&type=6&[^\r\n]*?&name=([^&\r\n]*)')
Write-Log ("sequence    : {0}" -f $seqName.Groups[1].Value)
Write-Log ("status      : {0}" -f $(if ($seqName.Groups[1].Value) { 'parsed a sequence name' } else { 'no sequence name found' }))
Write-Log ("checksum    : {0}" -f ([regex]::Match($text, '(?m)^checksum=([0-9a-f]{64})').Groups[1].Value))
Write-Log ("hindex      : {0}" -f ([regex]::Match($text, '(?m)^hindex=(\d+)').Groups[1].Value))
Write-Log ("capture     : $capture")
Add-Content -LiteralPath $LogPath -Value '=== done ==='
