<#
.SYNOPSIS
    Opens a .vpj project in VideoPad unattended, auto-answering the
    "Damaged File" checksum prompt.

.DESCRIPTION
    VideoPad stores a 64-hex "checksum=" line as the last line of every .vpj
    file. On load it recomputes the hash and, on mismatch, raises a modal
    dialog:

        Damaged File
        "The provided file may be damaged. Do you want to try to load it anyway?"
        [Try Load] [Cancel]

    The file then loads normally, with all edits intact. "Try Load" is the
    default button (IDOK), so the dialog can be answered without stealing
    focus by posting WM_COMMAND/IDOK to the dialog HWND. This means an agent
    can write .vpj files without reproducing NCH's hash function.

    VideoPad is single-instance and silently DROPS the file argument when
    another copy is already running, so any running instance is closed first
    (WM_CLOSE - never force-kill, which leaves a crash-recovery flag that
    suppresses the CLI argument and pops an "Abnormal Termination" dialog).

.PARAMETER ProjectPath
    Full path to the .vpj file to open.

.PARAMETER TimeoutSeconds
    How long to wait for the project title to appear. Default 40.

.PARAMETER NoCloseExisting
    Do not close a running VideoPad instance (fails fast instead).

.OUTPUTS
    PSCustomObject: Loaded, Title, PromptDismissed, PromptCount, Modals,
    ElapsedSeconds, Message

.NOTES
    Verified against VideoPad Professional 8.91 (32-bit), licensed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [int]$TimeoutSeconds = 40,
    [switch]$NoCloseExisting
)

$ErrorActionPreference = 'Stop'

$ExePath = 'C:\Program Files (x86)\NCH Software\VideoPad\videopad.exe'
$WM_COMMAND = 0x0111
$IDOK = [IntPtr]1

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    throw "Project not found: $ProjectPath"
}
$ProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$leaf = Split-Path -Leaf $ProjectPath

if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "VideoPad not found: $ExePath"
}

if (-not ('NativeInput' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'NativeInput.cs')
}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
. (Join-Path $PSScriptRoot 'PadUi.ps1')   # Find-PadControl / Invoke-PadControlClick

$script:Root = [System.Windows.Automation.AutomationElement]::RootElement
$script:ModalLog = New-Object System.Collections.ArrayList


function Get-PadProcess {
    @(Get-Process -Name 'videopad' -ErrorAction SilentlyContinue)
}

function Get-MainWindow {
    param([int]$ProcessId)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ProcessId)
    @($script:Root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)) |
        Where-Object { $_.Current.Name -match 'VideoPad' } |
        Select-Object -First 1
}

function Find-ByName {
    param($Element, [string]$Name)
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty, $Name)
    $Element.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
}

function Get-PadDialogWindows {
    <#
        Every VideoPad top-level window except the largest one (the main window),
        found by Win32 enumeration. UI Automation cannot be used here: the
        "Save changes?" prompt is a real #32770 with real Button children, yet UIA
        reports no such top-level window and no button children at all.
    #>
    param([int]$ProcessId)
    $wins = @(Get-PadWindows -MinArea 1000)
    if ($wins.Count -le 1) { return @() }
    $mainH = ($wins | Sort-Object { $_.Width * $_.Height } -Descending | Select-Object -First 1).Hwnd
    return @($wins | Where-Object { $_.Hwnd -ne $mainH })
}

function Find-PadButton {
    <#
        Returns @{ Dialog; Button } for the first real Win32 Button with the given
        text on any top-level VideoPad window, or $null. Buttons are the only
        reliable anchors in this UI: the ribbon is custom-drawn and unnamed, and a
        prompt that stacks on another can arrive with no window text at all, but
        [Try Load] is still a #32770 child the app knows how to answer.

        The dialog handle comes back too because WM_COMMAND has to be posted to
        the dialog that owns the control - posting it to the button itself is
        accepted silently and changes nothing.
    #>
    param([string]$Text)
    foreach ($win in (Get-PadWindows -MinArea 400)) {
        $h = Find-PadControl -Window $win -Text $Text -ClassName 'Button'
        if ($h) { return [pscustomobject]@{ Dialog = [IntPtr]$win.Hwnd; Button = $h } }
    }
    return $null
}

function Get-PadDescendantTexts {
    param([int64]$Hwnd)
    $items = New-Object System.Collections.ArrayList
    $cb = [PadUiNative+EnumProc] {
        param($h, $l)
        $t = New-Object System.Text.StringBuilder 512
        [PadUiNative]::GetWindowTextW($h, $t, 512) | Out-Null
        if ($t.Length -gt 0) { [void]$items.Add($t.ToString()) }
        return $true
    }
    [PadUiNative]::EnumChildWindows([IntPtr]$Hwnd, $cb, [IntPtr]::Zero) | Out-Null
    return , @($items.ToArray())
}

function Clear-PadModals {
    <#
        Answers every modal that is not the checksum prompt. A stale dialog from an
        earlier session otherwise blocks the whole flow: VideoPad swallows WM_CLOSE
        while a modal is up, and clicking the main window does nothing.

        Seen in practice:
          * "The current project has been changed..." -> [Save] [Discard] [Cancel]
            one per WM_CLOSE that was swallowed, so they stack
          * "New media has been connected to your computer." -> [Add Files] [No]
            raised when files land in a watched folder - e.g. our own export

        Never answers a "damaged file" prompt (its Cancel would abandon the load);
        the caller confirms that one with WM_COMMAND/IDOK instead.
    #>
    param([int]$ProcessId)

    $clicked = @()
    foreach ($win in (Get-PadDialogWindows -ProcessId $ProcessId)) {
        $msg = (Get-PadDescendantTexts -Hwnd $win.Hwnd) -join ' '
        if ($msg -match 'damaged') { continue }
        # The checksum prompt is not always identifiable by text: when a second
        # one stacks on top of the first the new window has no title at all and
        # only its [Try Load] [Cancel] buttons remain. Answering [Cancel] there
        # silently abandons the load, which then looks like a project that
        # "failed to open" while the app sits on an empty sequence. Its button
        # set is the reliable marker, so that is what gets skipped.
        if (Find-PadControl -Window $win -Text 'Try Load' -ClassName 'Button') { continue }

        foreach ($label in @('Discard', "Don't Save", 'No', 'Close', 'Cancel')) {
            $h = Find-PadControl -Window $win -Text $label -ClassName 'Button'
            if ($h) {
                Invoke-PadControlClick -Hwnd $h -SettleMs 500
                $clicked += ('{0} -> [{1}]' -f $win.Class, $label)
                break
            }
        }
    }
    foreach ($c in $clicked) { [void]$script:ModalLog.Add($c) }
    return $clicked
}



# --- 1. Close any running instance (single-instance drops the file argument) ---
$existing = Get-PadProcess
if ($existing) {
    if ($NoCloseExisting) {
        throw "VideoPad is already running (PID $($existing[0].Id)); refusing to continue."
    }
    foreach ($proc in $existing) {
        $main = Get-MainWindow -ProcessId $proc.Id
        if ($null -eq $main) { continue }
        # A modal (checksum prompt, "New media has been connected", "Save changes?")
        # swallows WM_CLOSE, so answer whatever is up and retry a few times.
        for ($attempt = 0; $attempt -lt 4; $attempt++) {
            $dlg = Find-ByName -Element $main -Name 'Damaged File'
            if ($dlg) {
                [NativeInput]::PostMessage([IntPtr][int64]$dlg.Current.NativeWindowHandle, $WM_COMMAND, $IDOK, [IntPtr]::Zero) | Out-Null
                Start-Sleep -Milliseconds 600
            }
            Clear-PadModals -ProcessId $proc.Id  | Out-Null
            [NativeInput]::CloseWindow([int]$main.Current.NativeWindowHandle) | Out-Null
            Start-Sleep -Milliseconds 1200
            if (-not (Get-PadProcess)) { break }
        }
    }

    for ($w = 0; $w -lt 12; $w++) {
        Start-Sleep -Milliseconds 700
        if (-not (Get-PadProcess)) { break }
    }
    if (Get-PadProcess) {
        throw 'Could not close the running VideoPad instance gracefully; aborting rather than force-killing it (that would arm crash recovery).'
    }
}

# --- 2. Launch with the file argument (only a fresh process honours it) ---
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Start-Process -FilePath $ExePath -ArgumentList "`"$ProjectPath`""

# --- 3. Poll: answer the checksum prompt, then wait for the title to flip ---
$promptCount = 0
$loaded = $false
$title = ''
$main = $null

while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    Start-Sleep -Milliseconds 700
    $proc = @(Get-PadProcess) | Select-Object -First 1
    if (-not $proc) { continue }

    # The checksum prompt is found by its [Try Load] button rather than by name:
    # when prompts stack the later window has no name, and missing it here means
    # Clear-PadModals below answers [Cancel] and throws the load away.
    $tryLoad = Find-PadButton -Text 'Try Load'
    if ($tryLoad) {
        Invoke-PadControlClick -Hwnd $tryLoad.Button -SettleMs 700
        $promptCount++
        Start-Sleep -Milliseconds 500
        continue
    }

    # After an unclean exit VideoPad replaces its main window with a crash report
    # ([It Crashed] / [Something Else]) and starts with an empty project, having
    # dropped the file argument on the floor. Report that immediately instead of
    # waiting out the timeout with an unexplained empty title.
    $crash = Find-PadButton -Text 'Something Else'
    if ($crash) {
        $sw.Stop()
        return [pscustomobject]@{
            Loaded          = $false
            Title           = 'Abnormal Termination Detected'
            PromptDismissed = ($promptCount -gt 0)
            PromptCount     = $promptCount
            Modals          = @($script:ModalLog)
            ElapsedSeconds  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            Message         = 'VideoPad is showing its crash report, which consumes the file argument. Answer it with [Something Else], then run this again.'
        }
    }

    if ($null -eq $main -or -not $main.Current.Name) {
        $main = Get-MainWindow -ProcessId $proc.Id
    }
    if ($null -eq $main) { continue }

    $dlg = Find-ByName -Element $main -Name 'Damaged File'
    if ($dlg) {
        $h = [IntPtr][int64]$dlg.Current.NativeWindowHandle
        [NativeInput]::PostMessage($h, $WM_COMMAND, $IDOK, [IntPtr]::Zero) | Out-Null
        $promptCount++
        Start-Sleep -Milliseconds 900
        continue
    }

    # Any other modal keeps the file argument from being processed; answer it and
    # keep polling rather than waiting out the timeout.
    if (@(Clear-PadModals -ProcessId $proc.Id ).Count -gt 0) {
        Start-Sleep -Milliseconds 700
        continue
    }

    $title = $main.Current.Name
    if ($title -like "*$leaf*") { $loaded = $true; break }
    if ($title -match 'Abnormal Termination|Recover') {
        $sw.Stop()
        return [pscustomobject]@{
            Loaded          = $false
            Title           = $title
            PromptDismissed = ($promptCount -gt 0)
            PromptCount     = $promptCount
            Modals          = @($script:ModalLog)
            ElapsedSeconds  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            Message         = 'VideoPad showed a crash-recovery dialog. Close it (choose to discard) and retry.'
        }
    }
}
$sw.Stop()

if ($loaded) {
    $msg = "Loaded '$leaf'."
    if ($promptCount -gt 0) { $msg += " Checksum mismatch was auto-confirmed ($promptCount prompt(s))." }
} else {
    $msg = "Timed out after $TimeoutSeconds s without '$leaf' appearing in the title (last title: '$title')."
}

[pscustomobject]@{
    Loaded          = $loaded
    Title           = $title
    PromptDismissed = ($promptCount -gt 0)
    PromptCount     = $promptCount
    Modals          = @($script:ModalLog)
    ElapsedSeconds  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Message         = $msg
}
