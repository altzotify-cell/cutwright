<#
.SYNOPSIS
    Runs one pipeline step in a child PowerShell and prints a single JSON verdict.

.DESCRIPTION
    Every tool in tools/ reports success the same way PowerShell always has: it
    emits an object, or it throws. That is fine for a human at a prompt and
    awkward for an agent, which has to decide whether to continue and cannot tell
    a warning from a failure by reading prose on stdout. This wrapper turns any
    step into one machine-readable result:

        { "ok": true, "step": "gate", "exitCode": 0, "timedOut": false,
          "seconds": 2.1, "command": "...", "stdout": "...", "stderr": "" }

    The child runs with -NoProfile -NonInteractive, so a profile cannot change
    behaviour between machines, and with -EncodedCommand, so quoting and
    PowerShell's own parsing cannot mangle the command string. stdout and stderr
    are captured separately and returned verbatim - the wrapper never judges
    their contents, so `ok` means exactly "the step exited 0".

    Why a child process instead of dot-sourcing
    -------------------------------------------
    Several steps poke at global desktop state (synthetic input, window handles,
    the single VideoPad instance). A child gives each step a clean runspace and
    guarantees the exit code survives, which a dot-sourced script does not.

.PARAMETER Command
    The step to run, as a PowerShell command line. It is executed from -WorkDir.

.PARAMETER Step
    Label recorded in the verdict, so a caller can log which step a result
    belongs to ("build", "gate", "export", ...).

.PARAMETER WorkDir
    Directory the command runs in. Defaults to the repo root.

.PARAMETER TimeoutSeconds
    Wall-clock budget. On expiry the child is killed and timedOut is true.
    Default 3600, which covers a long export; pass something small (60) for the
    app-free steps so a hang is caught early.

.OUTPUTS
    One JSON object on stdout: ok, step, exitCode, timedOut, seconds, command,
    workDir, stdout, stderr.

.EXAMPLE
    .\Invoke-AgentStep.ps1 -Step gate -Command '.\tools\Test-Examples.ps1'

.EXAMPLE
    # A failing step: ok=false, exitCode=1, and the reason in stderr.
    .\Invoke-AgentStep.ps1 -Step build -Command '.\tools\New-Project.ps1 -Spec .\examples\missing.json'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$Step = 'step',
    [string]$WorkDir,
    [int]$TimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'

if (-not $WorkDir) { $WorkDir = Split-Path -Parent $PSScriptRoot }
if (-not (Test-Path -LiteralPath $WorkDir)) { throw "WorkDir not found: $WorkDir" }
$WorkDir = (Resolve-Path -LiteralPath $WorkDir).Path

# A redirected PowerShell writes its error stream as CLIXML, so a plain `throw`
# arrives as '<S S="Error">Spec not found...' wrapped in XML noise. Catching the
# error inside the child and writing the message with [Console]::Error keeps
# stderr readable for whoever is parsing it.
function ConvertFrom-ClixmlStderr {
    param([string]$Text)
    if (-not $Text -or $Text -notmatch '^#<\s*CLIXML') { return $Text }
    $msgs = [regex]::Matches($Text, '<S S="Error">(.*?)</S>')
    if ($msgs.Count -eq 0) { return $Text }
    $parts = foreach ($m in $msgs) {
        $s = $m.Groups[1].Value -replace '_x000D__x000A_', "`n" -replace '_x000A_', "`n" -replace '_x000D_', "`n"
        $s -replace '&lt;', '<' -replace '&gt;', '>' -replace '&quot;', '"' -replace '&amp;', '&'
    }
    return ($parts -join '').TrimEnd()
}

# Write-Host goes to the information stream, which a redirected PowerShell also
# serialises to stderr as CLIXML - so a *successful* step would look like it had
# errors. Merging 6>&1 files that chatter with stdout where it belongs, leaving
# stderr for real failures only.
$child = '$ProgressPreference = ''SilentlyContinue''; try { & { ' + $Command +
    ' } 6>&1 } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }'

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $psi.FileName)) { $psi.FileName = 'powershell.exe' }
$psi.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand ' +
    [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($child))
$psi.WorkingDirectory = $WorkDir
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true

$watch = [Diagnostics.Stopwatch]::StartNew()
$proc = [Diagnostics.Process]::Start($psi)

# Read both pipes asynchronously: a step that writes more than the pipe buffer
# (a long export log) would otherwise deadlock against WaitForExit.
$outTask = $proc.StandardOutput.ReadToEndAsync()
$errTask = $proc.StandardError.ReadToEndAsync()
$timedOut = -not $proc.WaitForExit($TimeoutSeconds * 1000)
if ($timedOut) {
    try { $proc.Kill() } catch { }
}
$proc.WaitForExit()
$watch.Stop()

$result = [pscustomobject]@{
    ok        = (-not $timedOut) -and ($proc.ExitCode -eq 0)
    step      = $Step
    exitCode  = $(if ($timedOut) { -1 } else { $proc.ExitCode })
    timedOut  = $timedOut
    seconds   = [math]::Round($watch.Elapsed.TotalSeconds, 2)
    command   = $Command
    workDir   = $WorkDir
    stdout    = $outTask.Result
    stderr    = ConvertFrom-ClixmlStderr $errTask.Result
}

$result | ConvertTo-Json -Depth 4
