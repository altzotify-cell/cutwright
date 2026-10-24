<#
.SYNOPSIS
    Opens one .mlt in a throwaway Shotcut, photographs its window, closes it.

.DESCRIPTION
    This is the "does Shotcut agree" half of Cutwright's checks. melt is the
    renderer, but Shotcut is the editor, and the titles once rendered in melt and
    vanished in the GUI: a check that only ever asks melt is asking the wrong
    witness. So this opens the file in Shotcut itself, waits for the project to
    parse, brings the window to the front and copies the pixels into a PNG.
    Python does the measuring.

    Three things here are deliberate:

      * It only ever closes a Shotcut it started. The PIDs running before the
        launch are recorded, and the window is found among *new* processes whose
        title names the file, so a Shotcut the user already had open is never
        focused, clicked or killed.
      * It refuses to photograph a window that is not foreground. CopyFromScreen
        copies whatever is on top; a screenshot of another window measured as
        Shotcut's answer would be worse than no check at all.
      * It relaunches. Shotcut's launcher owns no window -- the window belongs to
        a sibling started in the same second.

.PARAMETER Project
    Absolute path of the .mlt to open.

.PARAMETER Out
    PNG to write.

.PARAMETER TimeoutSeconds
    How long to wait for the project to load before giving up.

.OUTPUTS
    One JSON object on stdout: ok, error, pid, left, top, width, height,
    foreground, seconds.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$TimeoutSeconds = 90,
    [double]$SeekFraction = -1
)

$ErrorActionPreference = 'Continue'   # failures are reported as JSON, not as a stack trace

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class CwShotcutWindow
{
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, uint d, IntPtr e);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    // SetForegroundWindow alone is refused while another process owns the
    // foreground; attaching to that process's input queue is the documented way
    // around it.
    public static bool ForceForeground(IntPtr hwnd)
    {
        for (int i = 0; i < 3; i++)
        {
            IntPtr fg = GetForegroundWindow();
            if (fg == hwnd) return true;
            uint fgThread = GetWindowThreadProcessId(fg, IntPtr.Zero);
            uint me = GetCurrentThreadId();
            if (fgThread != 0) AttachThreadInput(fgThread, me, true);
            BringWindowToTop(hwnd);
            SetForegroundWindow(hwnd);
            if (fgThread != 0) AttachThreadInput(fgThread, me, false);
            System.Threading.Thread.Sleep(250);
            if (GetForegroundWindow() == hwnd) return true;
        }
        return GetForegroundWindow() == hwnd;
    }
}
"@
[CwShotcutWindow]::SetProcessDPIAware() | Out-Null

$WM_CLOSE = 0x0010
$SW_RESTORE = 9
$result = [ordered]@{ ok = $false; error = ''; pid = 0; left = 0; top = 0
    width = 0; height = 0; foreground = $false; seconds = 0.0 }

function Out-Result {
    $result | ConvertTo-Json -Compress
    exit 0
}

$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$exe = Join-Path $root 'shotcut\Shotcut\shotcut.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    $result.error = "shotcut.exe is not installed at $exe"
    Out-Result
}
if (-not (Test-Path -LiteralPath $Project)) {
    $result.error = "no such project: $Project"
    Out-Result
}

$before = @(Get-Process shotcut -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$leaf = [System.IO.Path]::GetFileName($Project)
$started = [System.Diagnostics.Stopwatch]::StartNew()
$owner = $null
$launcher = $null

try {
    $launcher = Start-Process -FilePath $exe -ArgumentList $Project -PassThru
    $deadline = $started.Elapsed.TotalSeconds + $TimeoutSeconds
    while ($started.Elapsed.TotalSeconds -lt $deadline) {
        Start-Sleep -Milliseconds 400
        $owner = @(Get-Process shotcut -ErrorAction SilentlyContinue |
            Where-Object { $before -notcontains $_.Id -and $_.MainWindowHandle -ne 0 -and
                           $_.MainWindowTitle -like "*$leaf*" }) | Select-Object -First 1
        if ($owner) { break }
        if ($launcher.HasExited -and $launcher.ExitCode -ne 0) {
            $result.error = "shotcut exited with $($launcher.ExitCode) before showing a window"
            break
        }
    }
    if (-not $owner) {
        if (-not $result.error) {
            $result.error = "no Shotcut window for $leaf within $TimeoutSeconds s"
        }
        Out-Result
    }

    $result.pid = $owner.Id
    $hwnd = [IntPtr]$owner.MainWindowHandle
    if ([CwShotcutWindow]::IsIconic($hwnd)) {
        [CwShotcutWindow]::ShowWindow($hwnd, $SW_RESTORE) | Out-Null
        Start-Sleep -Milliseconds 800
    }
    # The title bar appears once the project parses; the player still needs a
    # moment to paint its first frame.
    Start-Sleep -Seconds 2

    if (-not [CwShotcutWindow]::ForceForeground($hwnd)) {
        $result.error = 'Shotcut would not come to the front; not photographing another window'
        Out-Result
    }
    $result.foreground = $true

    $rect = New-Object CwShotcutWindow+RECT
    [CwShotcutWindow]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
    # A maximised window hangs a few pixels off the screen; copy only the part
    # that exists.
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $x0 = [Math]::Max($rect.Left, 0)
    $y0 = [Math]::Max($rect.Top, 0)
    $x1 = [Math]::Min($rect.Right, $screen.Right)
    $y1 = [Math]::Min($rect.Bottom, $screen.Bottom)
    $w = $x1 - $x0
    $h = $y1 - $y0
    if ($w -le 0 -or $h -le 0) {
        $result.error = "window rect is degenerate ($w x $h)"
        Out-Result
    }

    $dir = Split-Path -Parent $Out
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    if ($SeekFraction -ge 0) {
        # Click the player's scrub bar at a fraction of the project. The bar runs
        # from 39.2% to 67.6% of the window's width and sits at 48.5% of its
        # height in Shotcut's default layout; a layout the user has re-arranged
        # moves it, which fails the check rather than passing it wrongly.
        $sx = [int]($x0 + $w * (0.392 + 0.284 * $SeekFraction))
        $sy = [int]($y0 + $h * 0.485)
        [CwShotcutWindow]::SetCursorPos($sx, $sy) | Out-Null
        [CwShotcutWindow]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)   # down
        [CwShotcutWindow]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)   # up
        Start-Sleep -Milliseconds 1500
        $result.seek = $SeekFraction
    }
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $gfx.CopyFromScreen($x0, $y0, 0, 0, (New-Object System.Drawing.Size($w, $h)))
    $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
    $gfx.Dispose()
    $bmp.Dispose()

    $result.left = $x0
    $result.top = $y0
    $result.width = $w
    $result.height = $h
    $result.ok = $true
}
catch {
    $result.error = "$($_.Exception.Message)"
}
finally {
    $result.seconds = [Math]::Round($started.Elapsed.TotalSeconds, 1)
    # Close only what this script started.
    if ($owner) {
        $h = [IntPtr]$owner.MainWindowHandle
        [CwShotcutWindow]::PostMessage($h, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        for ($i = 0; $i -lt 24; $i++) {
            Start-Sleep -Milliseconds 250
            $owner.Refresh()
            if ($owner.HasExited) { break }
        }
        $owner.Refresh()
        if (-not $owner.HasExited) { Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue }
    }
    if ($launcher -and -not $launcher.HasExited -and $before -notcontains $launcher.Id) {
        Stop-Process -Id $launcher.Id -Force -ErrorAction SilentlyContinue
    }
}
$result | ConvertTo-Json -Compress
if (-not $result.ok) { exit 1 }
