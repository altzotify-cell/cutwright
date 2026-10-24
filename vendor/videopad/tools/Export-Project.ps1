<#
.SYNOPSIS
    Exports the current VideoPad sequence to a video file, unattended.

.DESCRIPTION
    Renders the sequence VideoPad currently has open and moves the result to
    -OutputPath. This is the last link in the agent pipeline:

        JSON spec -> New-Project.ps1 (.vpj) -> Open-Project.ps1 -> [this] -> .mp4

    How the UI is driven
    --------------------
    VideoPad has no usable automation surface. Its ribbon is custom-drawn with no
    HWNDs and no UI Automation, so the three clicks that open the export dialog
    are synthetic mouse input at calibrated positions. Everything after that is
    addressable properly: the export dialog is a DirectUIHWND (an embedded IE
    control) whose Create/Cancel are real Win32 buttons with window text, so they
    are found by name and activated with BM_CLICK. A synthetic mouse click on
    Create is silently ignored by the DirectUI host; BM_CLICK is not.

    Why the output file is discovered rather than named
    --------------------------------------------------
    The dialog prefills Export File Name with the *sequence* name and the folder
    from the project's own export settings, and its text fields live inside the
    DirectUI tree where they cannot be set programmatically. Rather than drive
    those fields by keyboard, the tool snapshots the export folder and, after the
    encode, picks up the newest .mp4 that appeared. The file is then moved to
    -OutputPath, the only path the caller has to care about.

    Completion is detected by polling: file size must stop changing *and*
    ffprobe must be able to read the duration. Writing the moov atom is the last
    thing VideoPad does, so a readable duration means the file is finished rather
    than a partially muxed stub.

.PARAMETER OutputPath
    Where the finished video should end up. Parent directory is created.

.PARAMETER ProjectPath
    Optional project to open first (delegates to Open-Project.ps1). Omit to
    export whatever is already open.

.PARAMETER ExpectedDurationMs
    Optional. If set, the exported duration is checked against it and a warning
    is emitted when the difference exceeds one frame at 24 fps.

.PARAMETER ExportFolder
    Folder VideoPad writes into before the move. Defaults to the user's Videos
    folder, which is VideoPad's default export location.

.PARAMETER TimeoutSeconds
    Overall budget for the encode. Default 1800.

.OUTPUTS
    PSCustomObject: OutputPath, SizeBytes, DurationSeconds, DurationMs,
    ExpectedDurationMs, DurationDeltaMs, SourceFile, Verified, Message

.NOTES
    Verified against VideoPad Professional 8.91 (32-bit) on a 150% DPI display.
    A 3.5 minute 1080p sequence took roughly 7 minutes to encode.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$ProjectPath,
    [int]$ExpectedDurationMs = 0,
    [string]$ExportFolder,
    [int]$TimeoutSeconds = 1800,
    [switch]$WaitOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PadUi.ps1')

# Calibrated on the Home ribbon with the editor at 1536x817 physical pixels
# (1024 logical at 150% scaling). Scaled by the window's actual width so a
# differently sized window still lands on the same controls.
$refWidth = 1536.0
$refHeight = 817.0
$homeTab = @{ X = 175; Y = 66 }
$exportButton = @{ X = 543; Y = 105 }
$videoFileItem = @{ X = 515; Y = 176 }

function Write-Step {
    param([string]$Text)
    Write-Host ('[{0:HH:mm:ss}] {1}' -f (Get-Date), $Text)
}

function Get-ProbeDuration {
    <#
        Duration in seconds, or $null while the file is still being written.

        ffprobe reports "moov atom not found" on stderr for a file that is still
        encoding, and with $ErrorActionPreference='Stop' PowerShell turns native
        stderr output into a terminating error - which used to kill this poll loop
        mid-encode when stderr was redirected to a file. stderr is therefore
        merged and ignored, and only a parseable number on stdout counts.
    #>
    param([string]$Path)
    if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { return $null }

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        $raw = & ffprobe -v error -show_entries 'format=duration' -of 'csv=p=0' $Path 2>&1
        $code = $LASTEXITCODE
    }
    catch { $raw = @(); $code = -1 }
    finally { $ErrorActionPreference = $previous }

    if ($code -ne 0) { return $null }
    foreach ($line in @($raw)) {
        $text = [string]$line
        $value = 0.0
        if ([double]::TryParse($text.Trim(), [ref]$value)) { return $value }
    }
    return $null
}

if (-not $ExportFolder) { $ExportFolder = Join-Path $env:USERPROFILE 'Videos' }
if (-not (Test-Path -LiteralPath $ExportFolder)) {
    throw "Export folder does not exist: $ExportFolder"
}

$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outDir = Split-Path -Parent $OutputPath
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

# --- 0. Optionally open the project -----------------------------------------
if ($ProjectPath) {
    Write-Step "Opening project $ProjectPath"
    $open = & (Join-Path $PSScriptRoot 'Open-Project.ps1') -ProjectPath $ProjectPath
    if (-not $open.Loaded) { throw "Could not load project: $($open.Message)" }
    Write-Step "Project loaded: $($open.Title)"
    Start-Sleep -Seconds 2
}

$window = Get-PadWindow
Write-Step "Editor window $($window.Hwnd) at $($window.Left),$($window.Top) $($window.Width)x$($window.Height)"

# Pin the window to the calibrated geometry first. The ribbon scales with DPI, not
# with the window, so on a maximised 1942x1030 window a width-scaled click lands
# below the ribbon and the Export dropdown never opens. Resizing makes the
# calibration exact (scale 1.0); scaling coordinates is only a fallback.
if ([Math]::Abs($window.Width - $refWidth) -gt 1 -or [Math]::Abs($window.Height - $refHeight) -gt 1) {
    $pinned = Set-PadWindowSize -Window $window -Width ([int]$refWidth) -Height ([int]$refHeight) -X 0 -Y 0
    if ($pinned) {
        Write-Step "Pinned window to $($pinned.Width)x$($pinned.Height) (calibration size)"
        $window = $pinned
    }
    else {
        Write-Step 'WARNING: could not resize the window; falling back to scaled coordinates'
    }
}

$scale = $window.Width / $refWidth
if ([Math]::Abs($scale - 1.0) -gt 0.01) {
    Write-Step ("Scaling ribbon coordinates by {0:N3}" -f $scale)
}

# --- 1. Snapshot the export folder so the new file can be identified --------
$before = @{}
foreach ($f in @(Get-ChildItem -LiteralPath $ExportFolder -Filter '*.mp4' -File -ErrorAction SilentlyContinue)) {
    $before[$f.FullName] = $f.LastWriteTimeUtc
}
Write-Step "Watching $ExportFolder ($($before.Count) existing .mp4)"

# --- 2/3. Drive the ribbon and the export dialog ----------------------------
# The encode runs inside VideoPad, not in this script, so an interrupted run is
# recoverable: -WaitOnly skips the clicks and adopts the newest export instead.
$source = $null

if ($WaitOnly) {
    $recent = @(Get-ChildItem -LiteralPath $ExportFolder -Filter '*.mp4' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-2) } |
            Sort-Object LastWriteTime -Descending)
    if ($recent.Count -eq 0) { throw "No recent .mp4 in $ExportFolder to wait for." }
    $source = $recent[0]
    Write-Step "Resuming; waiting on $($source.Name)"
} else {
    Invoke-PadFocus $window | Out-Null
    Write-Step 'Ribbon: Home tab'
    Invoke-PadClick $window ([int]($homeTab.X * $scale)) ([int]($homeTab.Y * $scale)) -SettleMs 700

    Write-Step 'Ribbon: Export Video'
    Invoke-PadClick $window ([int]($exportButton.X * $scale)) ([int]($exportButton.Y * $scale)) -SettleMs 1000

    Write-Step 'Ribbon: Video File'
    Invoke-PadClick $window ([int]($videoFileItem.X * $scale)) ([int]($videoFileItem.Y * $scale)) -SettleMs 1500

    Write-Step 'Waiting for the export dialog (Create button)'
    $create = Find-PadControl -Text 'Create' -ClassName 'Button' -TimeoutSeconds 25
    if (-not $create) {
        throw 'The export dialog did not appear. Is a sequence open, and is the ribbon on the Home tab?'
    }
    Write-Step "Export dialog is up; activating Create ($create)"
    Invoke-PadControlClick -Hwnd $create -SettleMs 2500
}

# --- 4. Wait for the encode to finish --------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$lastSize = -1
$stableCount = 0
$duration = $null

while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 4

    if (-not $source) {
        $candidates = @(Get-ChildItem -LiteralPath $ExportFolder -Filter '*.mp4' -File -ErrorAction SilentlyContinue |
                Where-Object {
                    -not $before.ContainsKey($_.FullName) -or $before[$_.FullName] -ne $_.LastWriteTimeUtc
                } |
                Sort-Object LastWriteTimeUtc -Descending)
        if ($candidates.Count -gt 0) {
            $source = $candidates[0]
            Write-Step "Encoding to $($source.Name)"
        }
        continue
    }

    $size = (Get-Item -LiteralPath $source.FullName).Length
    $duration = Get-ProbeDuration -Path $source.FullName

    if ($size -eq $lastSize -and $duration) {
        $stableCount++
        Write-Step ("  {0:N0} bytes, duration {1:N3}s, stable {2}/2" -f $size, $duration, $stableCount)
        if ($stableCount -ge 2) { break }
    } else {
        $stableCount = 0
        Write-Step ("  {0:N0} bytes, duration {1}" -f $size, $(if ($duration) { '{0:N3}s' -f $duration } else { 'not finalised' }))
    }
    $lastSize = $size
}

if (-not $source -or -not $duration) {
    throw "Export did not complete within $TimeoutSeconds s (last size: $lastSize bytes)."
}

# --- 5. Dismiss any completion dialog so the file is no longer held ---------
foreach ($label in 'Close', 'Finish', 'OK', 'Done') {
    $btn = Find-PadControl -Text $label -ClassName 'Button' -TimeoutSeconds 0
    if ($btn) {
        Write-Step "Dismissing completion dialog ($label)"
        Invoke-PadControlClick -Hwnd $btn -SettleMs 800
        break
    }
}

# --- 6. Move into place -----------------------------------------------------
if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
Move-Item -LiteralPath $source.FullName -Destination $OutputPath -Force
$final = Get-Item -LiteralPath $OutputPath
Write-Step ("Moved to {0} ({1:N0} bytes)" -f $OutputPath, $final.Length)

# --- 7. Verify -------------------------------------------------------------
$durationMs = [int][Math]::Round($duration * 1000)
$deltaMs = 0
$verified = $true
$message = 'Exported.'

if ($ExpectedDurationMs -gt 0) {
    $deltaMs = $durationMs - $ExpectedDurationMs
    if ([Math]::Abs($deltaMs) -gt 42) {
        $verified = $false
        $message = "Duration mismatch: expected $ExpectedDurationMs ms, got $durationMs ms (delta ${deltaMs} ms)."
    } else {
        $message = "Exported; duration within one frame of the expected $ExpectedDurationMs ms."
    }
}
Write-Step $message

[pscustomobject]@{
    OutputPath         = $OutputPath
    SizeBytes          = $final.Length
    DurationSeconds    = [Math]::Round($duration, 3)
    DurationMs         = $durationMs
    ExpectedDurationMs = $ExpectedDurationMs
    DurationDeltaMs    = $deltaMs
    SourceFile         = $source.FullName
    Verified           = $verified
    Message            = $message
}
