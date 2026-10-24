<#
.SYNOPSIS
    Dumps the control map of VideoPad's Export dialog.

.DESCRIPTION
    The Export dialog is NOT a child of the main window, so it cannot be found
    with EnumChildWindows(main) and - because VideoPad exposes no UI Automation
    tree - it does not appear in UIA either. It is, however, a real Win32 window
    whose controls are ordinary Buttons/Edits/ComboBoxes with window text.

    The reliable way in is WindowFromPoint: the Create button sits at a known
    screen position while the dialog is open, and walking up from that hwnd
    reaches the dialog itself.

.PARAMETER ProbeX
    Screen X of a point inside the dialog (default: centre of Create).

.PARAMETER ProbeY
    Screen Y of a point inside the dialog (default: the button row).
#>
[CmdletBinding()]
param([int]$ProbeX = 1230, [int]$ProbeY = 880)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PadUi.ps1')

if (-not ('DlgProbe' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class DlgProbe
{
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
    [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
}

function Get-PadText {
    param([IntPtr]$Hwnd)
    $sb = New-Object System.Text.StringBuilder 512
    [DlgProbe]::GetWindowTextW($Hwnd, $sb, 512) | Out-Null
    return $sb.ToString()
}

function Get-PadClass {
    param([IntPtr]$Hwnd)
    $sb = New-Object System.Text.StringBuilder 256
    [DlgProbe]::GetClassNameW($Hwnd, $sb, 256) | Out-Null
    return $sb.ToString()
}

$pt = New-Object 'DlgProbe+POINT'
$pt.X = $ProbeX
$pt.Y = $ProbeY
$hit = [DlgProbe]::WindowFromPoint($pt)

if ($hit -eq [IntPtr]::Zero) { throw 'No window at the probe point.' }

"hit: class='$(Get-PadClass $hit)' text='$(Get-PadText $hit)' hwnd=$hit"

# Walk up to the dialog root.
$chain = @()
$cur = $hit
for ($i = 0; $i -lt 6 -and $cur -ne [IntPtr]::Zero; $i++) {
    $pidOwner = 0
    [DlgProbe]::GetWindowThreadProcessId($cur, [ref]$pidOwner) | Out-Null
    $r = New-Object 'DlgProbe+RECT'
    [DlgProbe]::GetWindowRect($cur, [ref]$r) | Out-Null
    $chain += ('level {0}: hwnd={1} class={2} text=[{3}] {4},{5} {6}x{7}' -f $i, $cur,
        (Get-PadClass $cur), (Get-PadText $cur), $r.Left, $r.Top,
        ($r.Right - $r.Left), ($r.Bottom - $r.Top))
    $cur = [DlgProbe]::GetParent($cur)
}
$chain | ForEach-Object { $_ }

$dialog = [DlgProbe]::GetParent($hit)
if ($dialog -eq [IntPtr]::Zero) { $dialog = $hit }

"--- children of dialog $dialog ---"
$script:rows = New-Object System.Collections.ArrayList
$cb = [DlgProbe+EnumProc] {
    param($hWnd, $lParam)
    $r = New-Object 'DlgProbe+RECT'
    [DlgProbe]::GetWindowRect($hWnd, [ref]$r) | Out-Null
    $vis = [DlgProbe]::IsWindowVisible($hWnd)
    [void]$script:rows.Add(('{0,-12} | [{1}] | {2},{3} {4}x{5} | vis={6} | hwnd={7}' -f
            (Get-PadClass $hWnd), (Get-PadText $hWnd), $r.Left, $r.Top,
            ($r.Right - $r.Left), ($r.Bottom - $r.Top), $vis, $hWnd))
    return $true
}
[DlgProbe]::EnumChildWindows($dialog, $cb, [IntPtr]::Zero) | Out-Null
"children: $($script:rows.Count)"
$script:rows | Where-Object { $_ -match 'Button|Edit|ComboBox|Static' } | ForEach-Object { $_ }
