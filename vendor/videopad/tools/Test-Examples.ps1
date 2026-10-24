<#
.SYNOPSIS
    Rebuilds every example spec and checks the result is byte-identical.

.DESCRIPTION
    The writer's central promise is that a spec is deterministic: same template,
    same spec, same bytes - and that adding v2 features did not disturb the
    projects produced earlier (examples/cut1.json still has to reproduce
    out/cut1.vpj exactly).

    This harness hashes each spec's declared output, re-runs New-Project.ps1, and
    compares. It needs no VideoPad, so it is the cheap gate to run before a commit;
    the app-side checks (autosave oracle, export) are the expensive gate, see
    docs/HANDOFF.md sections 8 and 10.

.PARAMETER Examples
    Folder of *.json specs. Defaults to the repo's examples folder.

.PARAMETER Spec
    Run only these spec files (names or paths) instead of all of them.

.OUTPUTS
    PSCustomObject per spec: Spec, Output, DurationMs, SegmentCount, Changed,
    Result

.EXAMPLE
    .\Test-Examples.ps1

.EXAMPLE
    .\Test-Examples.ps1 -Spec cut3-addmedia.json
#>
[CmdletBinding()]
param(
    [string]$Examples,
    [string[]]$Spec
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is not populated yet while a param default is being evaluated,
# so the examples folder is resolved here instead of in the param block.
if (-not $Examples) {
    $Examples = Join-Path (Split-Path -Parent $PSScriptRoot) 'examples'
}
$writer = Join-Path $PSScriptRoot 'New-Project.ps1'

$specs = if ($Spec) {
    foreach ($s in $Spec) {
        if (Test-Path -LiteralPath $s) { Get-Item -LiteralPath $s }
        else { Get-Item -LiteralPath (Join-Path $Examples $s) }
    }
}
else { @(Get-ChildItem -LiteralPath $Examples -Filter '*.json' -File | Sort-Object Name) }

if (@($specs).Count -eq 0) { throw "No specs found in $Examples" }

$failed = 0
$rows = foreach ($file in @($specs)) {
    $json = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json

    # The writer resolves relative paths against the spec's folder; mirror that so
    # the harness knows which artefact to hash.
    $output = $json.output
    if (-not [IO.Path]::IsPathRooted($output)) {
        $output = [IO.Path]::GetFullPath((Join-Path $file.DirectoryName $output))
    }

    $before = $null
    if (Test-Path -LiteralPath $output) { $before = (Get-FileHash -LiteralPath $output).Hash }

    $run = & $writer -Spec $file.FullName

    $after = (Get-FileHash -LiteralPath $output).Hash
    $changed = ($null -eq $before) -or ($before -ne $after)
    if ($changed) { $failed++ }

    [pscustomobject]@{
        Spec         = $file.Name
        Output       = [IO.Path]::GetFileName($output)
        DurationMs   = $run.DurationMs
        SegmentCount = $run.SegmentCount
        Changed      = $changed
        Result       = $(if ($changed) { 'CHANGED (not reproducible)' } else { 'identical' })
    }
}

$rows

if ($failed -gt 0) {
    throw "$failed of $(@($rows).Count) example(s) did not reproduce byte-identically."
}
Write-Host "All $(@($rows).Count) example(s) reproduced byte-identically."
