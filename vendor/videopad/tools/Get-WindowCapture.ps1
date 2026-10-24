<#
.SYNOPSIS
    Captures the VideoPad main window to a PNG, optionally restoring and
    focusing it first.

.DESCRIPTION
    VideoPad's UI is entirely custom-drawn: every UI Automation descendant is an
    unnamed Pane with no InvokePattern, and a minimised window reports negative
    coordinates. Without a picture there is no reliable way to locate toolbar
    buttons such as Export, so this script grabs the window bitmap and reports
    the geometry needed to aim synthetic input.

    Use -Restore to bring a minimised window back on screen before capturing,
    and -Focus to defeat the foreground lock (AttachThreadInput +
    SetForegroundWindow) and report whether it actually took.

.PARAMETER OutPath
    PNG file to write.

.PARAMETER Restore
    ShowWindow(SW_RESTORE) before capturing.

.PARAMETER Focus
    Force the window to the foreground and report whether it became foreground.

.OUTPUTS
    PSCustomObject: Path, Left, Top, Width, Height, WasMinimised, Foreground,
    ForegroundMatches, DpiAware
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutPath,
    [switch]$Restore,
    [switch]$Focus
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
if (-not ('NativeInput' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'NativeInput.cs')
}

if (-not ('WinCapture' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class WinCapture
{
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
}

# Must run before any coordinate is read: PowerShell is DPI-unaware by default,
# so GetWindowRect returns logical pixels while BitBlt/CopyFromScreen and
# SetCursorPos work in physical pixels. On a scaled display that mismatch crops
# the capture and makes every screenshot coordinate useless as a click target.
[WinCapture]::SetProcessDPIAware() | Out-Null

$SW_RESTORE = 9

$proc = @(Get-Process -Name 'videopad' -ErrorAction SilentlyContinue) | Select-Object -First 1
if (-not $proc) { throw 'VideoPad is not running.' }

$hwnd = [IntPtr]$proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
    $el = @([System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children, $cond)) |
        Where-Object { $_.Current.Name -match 'VideoPad' } | Select-Object -First 1
    if ($el) { $hwnd = [IntPtr][int64]$el.Current.NativeWindowHandle }
}
if ($hwnd -eq [IntPtr]::Zero) { throw 'Could not find the VideoPad main window.' }

$wasMinimised = [WinCapture]::IsIconic($hwnd)
if ($Restore) {
    [WinCapture]::ShowWindow($hwnd, $SW_RESTORE) | Out-Null
    Start-Sleep -Milliseconds 900
}

$isForeground = $false
if ($Focus) {
    [NativeInput]::ForceForeground([int64]$hwnd)
    Start-Sleep -Milliseconds 500
    $isForeground = ([NativeInput]::GetForegroundWindow() -eq $hwnd)
}

$rect = New-Object 'WinCapture+RECT'
[WinCapture]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) { throw "Window rect is degenerate ($width x $height)." }

$outDir = Split-Path -Parent $OutPath
if ($outDir -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$bmp = New-Object System.Drawing.Bitmap($width, $height)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($width, $height)))
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose()
$bmp.Dispose()

[pscustomobject]@{
    Path              = $OutPath
    Left              = $rect.Left
    Top               = $rect.Top
    Width             = $width
    Height            = $height
    WasMinimised      = $wasMinimised
    Foreground        = $isForeground
    ForegroundMatches = ([NativeInput]::GetForegroundWindow() -eq $hwnd)
    Title             = $proc.MainWindowTitle
}
