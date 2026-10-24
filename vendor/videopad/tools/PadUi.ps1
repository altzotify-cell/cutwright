<#
.SYNOPSIS
    Minimal UI primitives for driving VideoPad, which exposes no automation.

.DESCRIPTION
    VideoPad's entire UI is custom-drawn: every UI Automation descendant is an
    unnamed Pane, no element implements InvokePattern, and the timeline is a
    bitmap. There is therefore no automation surface to use, and the GUI has to
    be driven with synthetic input verified by screenshots.

    Three hard-won details are centralised here:

    1. DPI. PowerShell is DPI-unaware by default, so GetWindowRect reports
       logical pixels while CopyFromScreen/BitBlt and SetCursorPos work in
       physical pixels. On this 150% display that mismatch crops captures and
       offsets every click, which previously looked like "input is blocked".
       SetProcessDPIAware() is called at load so all three agree.

    2. Window handle. Process.MainWindowHandle intermittently returns 0 for
       VideoPad (while a modal or a floating panel is up), which turns every
       coordinate into a desktop click. The top-level window is instead found by
       enumerating windows owned by the process and taking the largest visible
       one.

    3. Focus. Clicks and keys only reach VideoPad when it is foreground;
       NativeInput.ForceForeground defeats the foreground lock.

    Dot-source this file, then:

        $w = Get-PadWindow
        Invoke-PadClick $w 175 66            # Home tab
        Save-PadCapture -Path out\shot.png -Window $w
#>

if (-not ('PadUiNative' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PadUiNative
{
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
[DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
    [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, System.Text.StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, System.Text.StringBuilder s, int n);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
}
[PadUiNative]::SetProcessDPIAware() | Out-Null

if (-not ('NativeInput' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'NativeInput.cs')
}
Add-Type -AssemblyName System.Drawing

function Get-PadWindows {
    <#
    .SYNOPSIS
        Returns every visible top-level window owned by VideoPad.

    .DESCRIPTION
        VideoPad's dialogs are separate top-level popups *owned* by the main
        window, not child windows. GetParent reports that owner, which makes the
        dialog look like a descendant when it is not: EnumChildWindows(main) will
        never reach the Export dialog's buttons. They have to be found by walking
        the process's top-level windows instead, which is what this does.
    #>
    [CmdletBinding()]
    param([int]$MinArea = 1000)

    $proc = @(Get-Process -Name 'videopad' -ErrorAction SilentlyContinue) | Select-Object -First 1
    if (-not $proc) { throw 'VideoPad is not running.' }

    $pidTarget = $proc.Id
    $script:padWindows = New-Object System.Collections.ArrayList
    $cb = [PadUiNative+EnumProc] {
        param($hWnd, $lParam)
        $owner = 0
        [PadUiNative]::GetWindowThreadProcessId($hWnd, [ref]$owner) | Out-Null
        if ($owner -eq $pidTarget -and [PadUiNative]::IsWindowVisible($hWnd)) {
            $r = New-Object 'PadUiNative+RECT'
            [PadUiNative]::GetWindowRect($hWnd, [ref]$r) | Out-Null
            $w = $r.Right - $r.Left
            $h = $r.Bottom - $r.Top
            if (($w * $h) -gt $MinArea) {
                $cls = New-Object System.Text.StringBuilder 256
                [PadUiNative]::GetClassNameW($hWnd, $cls, 256) | Out-Null
                [void]$script:padWindows.Add([pscustomobject]@{
                        Hwnd   = [int64]$hWnd
                        Left   = $r.Left
                        Top    = $r.Top
                        Width  = $w
                        Height = $h
                        Class  = $cls.ToString()
                    })
            }
        }
        return $true
    }
    [PadUiNative]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null

    if ($script:padWindows.Count -eq 0) { throw 'Could not find any VideoPad window.' }
    return @($script:padWindows)
}

function Get-PadWindow {
    <#
    .SYNOPSIS
        Returns the VideoPad main window as Hwnd/Left/Top/Width/Height.

    .DESCRIPTION
        The largest window of the process is the editor; dialogs are smaller and
        are skipped by the default minimum area.
    #>
    [CmdletBinding()]
    param([int]$MinArea = 200000)

    $best = $null
    foreach ($win in (Get-PadWindows -MinArea $MinArea)) {
        if ($null -eq $best -or ($win.Width * $win.Height) -gt ($best.Width * $best.Height)) {
            $best = $win
        }
    }
    if ($null -eq $best) { throw 'Could not find the VideoPad main window.' }
    return $best
}

function Invoke-PadFocus {
    <#
    .SYNOPSIS
        Forces VideoPad to the foreground. Returns $true if it took.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Window, [int]$SettleMs = 400)

    [NativeInput]::ForceForeground([int64]$Window.Hwnd)
    Start-Sleep -Milliseconds $SettleMs
    return ([NativeInput]::GetForegroundWindow() -eq [IntPtr]$Window.Hwnd)
}

function Invoke-PadClick {
    <#
    .SYNOPSIS
        Clicks a point given in window-relative physical pixels.
    .DESCRIPTION
        Coordinates are relative to the window origin, which is also the origin
        of a Save-PadCapture screenshot, so a pixel measured in a capture can be
        passed straight through.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]$Window,
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [int]$SettleMs = 700
    )

    [NativeInput]::Click($Window.Left + $X, $Window.Top + $Y)
    Start-Sleep -Milliseconds $SettleMs
}

function Save-PadCapture {
    <#
    .SYNOPSIS
        Writes a PNG of the VideoPad window, or of the whole screen.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        $Window,
        [switch]$FullScreen,
        [int]$ScreenWidth = 1920,
        [int]$ScreenHeight = 1080
    )

    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    if ($FullScreen) {
        $x = 0; $y = 0; $w = $ScreenWidth; $h = $ScreenHeight
    } else {
        if ($null -eq $Window) { $Window = Get-PadWindow }
        $x = $Window.Left; $y = $Window.Top; $w = $Window.Width; $h = $Window.Height
    }

    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.CopyFromScreen($x, $y, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $gfx.Dispose()
    $bmp.Dispose()
    return $Path
}

function Find-PadControl {
    <#
    .SYNOPSIS
        Finds a descendant control of a window by window text (and optionally class).

    .DESCRIPTION
        VideoPad's ribbon is custom-drawn, but its dialogs are Win32 windows: the
        Export dialog hosts a DirectUIHWND whose buttons are real HWNDs with
        window text such as 'Create'. Enumerating descendants means a control can
        be addressed by name instead of by pixel, which survives DPI changes,
        window moves and theme differences.
    #>
    [CmdletBinding()]
    param(
        $Window,
        [Parameter(Mandatory = $true)][string]$Text,
        [string]$ClassName,
        [int]$TimeoutSeconds = 0
    )

    if ($Window) {
        $roots = @([IntPtr]$Window.Hwnd)
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        # Re-resolve the roots each pass: a dialog created after the call began
        # only shows up on the next sweep.
        if (-not $Window) {
            $roots = @(Get-PadWindows -MinArea 1000 | ForEach-Object { [IntPtr]$_.Hwnd })
        }

        foreach ($root in $roots) {
            $script:padMatch = $null
            $cb = [PadUiNative+EnumProc] {
                param($hWnd, $lParam)
                $t = New-Object System.Text.StringBuilder 512
                [PadUiNative]::GetWindowTextW($hWnd, $t, 512) | Out-Null
                if ($t.ToString() -eq $Text) {
                    $c = New-Object System.Text.StringBuilder 256
                    [PadUiNative]::GetClassNameW($hWnd, $c, 256) | Out-Null
                    if (-not $ClassName -or $c.ToString() -eq $ClassName) {
                        $script:padMatch = [int64]$hWnd
                        return $false
                    }
                }
                return $true
            }
            [PadUiNative]::EnumChildWindows($root, $cb, [IntPtr]::Zero) | Out-Null
            if ($script:padMatch) { return [IntPtr]$script:padMatch }
        }

        if ((Get-Date) -ge $deadline) { return $null }
        Start-Sleep -Milliseconds 300
    } while ($true)
}

function Invoke-PadControlClick {
    <#
    .SYNOPSIS
        Clicks a Win32 control by HWND using BM_CLICK.

    .DESCRIPTION
        Sending BM_CLICK to the control bypasses mouse positioning, DPI scaling
        and the foreground lock entirely - the message is delivered straight to
        the target button. This is what makes the Export dialog deterministic:
        a synthetic mouse click on 'Create' was ignored, but BM_CLICK is not.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][IntPtr]$Hwnd, [int]$SettleMs = 500)

    $BM_CLICK = 0x00F5
    [PadUiNative]::SendMessage($Hwnd, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds $SettleMs
}

function Set-PadWindowSize {
    <#
    .SYNOPSIS
        Restores a window to an exact size and position.

    .DESCRIPTION
        Ribbon coordinates are calibrated in physical pixels for a specific window
        size, and the ribbon scales with DPI rather than with the window, so a
        maximised window invalidates the calibration instead of scaling it. Pinning
        the window back to the calibrated size is the reliable fix; scaling the
        coordinates by width alone is not, because the vertical offsets do not
        follow the width.
    #>
    [CmdletBinding()]
    param(
        $Window,
        [Parameter(Mandatory = $true)][int]$Width,
        [Parameter(Mandatory = $true)][int]$Height,
        [int]$X = 0,
        [int]$Y = 0,
        [int]$SettleMs = 700
    )

    $SWP_NOZORDER = 0x0004
    $SWP_NOACTIVATE = 0x0010
    [PadUiNative]::SetWindowPos([IntPtr]$Window.Hwnd, [IntPtr]::Zero, $X, $Y, $Width, $Height,
        ($SWP_NOZORDER -bor $SWP_NOACTIVATE)) | Out-Null
    Start-Sleep -Milliseconds $SettleMs
    return (Get-PadWindow)
}

function Get-PadPointWindow {
    <#
    .SYNOPSIS
        Returns the HWND under a screen point, with its class and text.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][int]$X, [Parameter(Mandatory = $true)][int]$Y)

    $pt = New-Object 'PadUiNative+POINT'
    $pt.X = $X
    $pt.Y = $Y
    $hWnd = [PadUiNative]::WindowFromPoint($pt)
    $cls = New-Object System.Text.StringBuilder 256
    [PadUiNative]::GetClassNameW($hWnd, $cls, 256) | Out-Null
    $txt = New-Object System.Text.StringBuilder 512
    [PadUiNative]::GetWindowTextW($hWnd, $txt, 512) | Out-Null
    return [pscustomobject]@{
        Hwnd  = [int64]$hWnd
        Class = $cls.ToString()
        Text  = $txt.ToString()
    }
}
