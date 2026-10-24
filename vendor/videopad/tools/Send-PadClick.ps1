<#
.SYNOPSIS
    Clicks a point inside the VideoPad window and optionally re-captures it.

.DESCRIPTION
    VideoPad exposes no InvokePattern anywhere in its UI Automation tree, so
    every toolbar action has to go through synthetic input. Synthetic mouse
    input only lands on the intended control if:

      1. the coordinates are in the SAME pixel space as the capture, and
      2. VideoPad is actually the foreground window.

    Both are handled here: SetProcessDPIAware() keeps GetWindowRect, SetCursorPos
    and CopyFromScreen in physical pixels (PowerShell is DPI-unaware by default,
    which on a scaled display silently offsets every click), and ForceForeground
    defeats the foreground lock before clicking.

    Coordinates are given relative to the top-left of the window *capture*, so a
    pixel read off a Get-WindowCapture.ps1 PNG can be passed directly.

.PARAMETER X
    Horizontal offset in capture pixels.

.PARAMETER Y
    Vertical offset in capture pixels.

.PARAMETER Capture
    Optional PNG to write after clicking.

.PARAMETER WaitMs
    Settle time after the click before capturing.

.OUTPUTS
    PSCustomObject: ClickedX, ClickedY, Foreground, Path
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [string]$Capture,
    [int]$WaitMs = 1500
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
if (-not ('NativeInput' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'NativeInput.cs') }
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
[WinCapture]::SetProcessDPIAware() | Out-Null

$proc = @(Get-Process -Name 'videopad' -ErrorAction SilentlyContinue) | Select-Object -First 1
if (-not $proc) { throw 'VideoPad is not running.' }
$hwnd = [IntPtr]$proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw 'VideoPad has no main window handle.' }

[NativeInput]::ForceForeground([int64]$hwnd)
Start-Sleep -Milliseconds 400

$rect = New-Object 'WinCapture+RECT'
[WinCapture]::GetWindowRect($hwnd, [ref]$rect) | Out-Null

$screenX = $rect.Left + $X
$screenY = $rect.Top + $Y
[WinCapture]::ShowWindow($hwnd, 9) | Out-Null
[NativeInput]::Click($screenX, $screenY)
Start-Sleep -Milliseconds $WaitMs

$outPath = $null
if ($Capture) {
    $rect2 = New-Object 'WinCapture+RECT'
    [WinCapture]::GetWindowRect($hwnd, [ref]$rect2) | Out-Null
    $w = $rect2.Right - $rect2.Left
    $h = $rect2.Bottom - $rect2.Top
    $dir = Split-Path -Parent $Capture
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.CopyFromScreen($rect2.Left, $rect2.Top, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $bmp.Save($Capture, [System.Drawing.Imaging.ImageFormat]::Png)
    $gfx.Dispose()
    $bmp.Dispose()
    $outPath = $Capture
}

[pscustomobject]@{
    ClickedX   = $screenX
    ClickedY   = $screenY
    Foreground = ([NativeInput]::GetForegroundWindow() -eq $hwnd)
    Path       = $outPath
}
