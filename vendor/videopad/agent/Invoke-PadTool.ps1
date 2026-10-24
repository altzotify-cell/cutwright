<#
.SYNOPSIS
    Fills one agent/tools.json tool template and runs it, returning the JSON verdict.

.DESCRIPTION
    This is the glue between the manifest and tools/Invoke-AgentStep.ps1: it
    resolves a tool by name, applies each parameter's default, derives the
    arguments that are computed rather than supplied (videopad_gate's specArgs,
    videopad_roundtrip's capture path), refuses arguments that could break out of
    the command string, fills the template and hands it to the runner.

    The validation is deliberately blunt: no `;`, `|`, backtick, quote, `$` or
    newline, and no `..`. Every path this pipeline takes is a plain repo-relative
    name, so a stricter rule costs nothing and removes the injection question.

    Set VIDEO_PAD_AGENT=dry to print the filled command without running it.

.PARAMETER Name
    Tool name from agent/tools.json, e.g. videopad_gate.

.PARAMETER Arguments
    Hashtable of arguments, e.g. @{ spec = 'examples\cut5-cadence.json' }.

.PARAMETER TimeoutSeconds
    Runner timeout. Defaults to the tool's own timeoutSeconds, else 3600.

.OUTPUTS
    The runner's envelope as an object: ok, step, exitCode, timedOut, seconds,
    command, workDir, stdout, stderr.

.EXAMPLE
    .\Invoke-PadTool.ps1 -Name videopad_build -Arguments @{ spec = 'examples\cut5-cadence.json' }

.EXAMPLE
    .\Invoke-PadTool.ps1 -Name videopad_gate
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [hashtable]$Arguments = @{},
    [int]$TimeoutSeconds = 0
)

$ErrorActionPreference = 'Stop'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tools.json') -Raw | ConvertFrom-Json
$tool = $manifest.tools | Where-Object { $_.name -eq $Name }
if (-not $tool) {
    throw ("Unknown tool '$Name'. Known: " + (($manifest.tools | ForEach-Object { $_.name }) -join ', '))
}

function Assert-Safe([string]$Key, $Value) {
    if ($Value -is [array]) { foreach ($v in $Value) { Assert-Safe $Key $v }; return }
    $s = [string]$Value
    if ($s -match '[;&|`"''$()<>]' -or $s -match "`n" -or $s -match '\.\.') {
        throw "Argument '$Key' contains characters this pipeline never needs: '$s'"
    }
}

# Defaults, then the derived values the descriptions promise.
$fill = @{}
foreach ($p in $tool.parameters.properties.PSObject.Properties) {
    if ($p.Name -eq 'specArgs' -or $p.Name -eq 'capture') { continue }
    $v = $Arguments[$p.Name]
    if ($null -eq $v -and $p.Value.default) { $v = $p.Value.default }
    if ($null -eq $v) { $v = '' }
    Assert-Safe $p.Name $v
    $fill[$p.Name] = $v
}
$required = @($tool.parameters.required | Where-Object { $_ })
foreach ($r in $required) {
    if (-not $Arguments.ContainsKey($r) -and -not $fill[$r]) { throw "Tool '$Name' needs argument '$r'." }
}

if ($Name -eq 'videopad_gate') {
    $specs = @($Arguments['specs'] | Where-Object { $_ })
    $fill['specArgs'] = $(if ($specs.Count) { ' -Spec ' + ($specs -join ',') } else { '' })
}
if ($Name -eq 'videopad_roundtrip') {
    $fill['capture'] = [IO.Path]::ChangeExtension([string]$fill['logPath'], '.roundtrip.vpj')
}

$command = [string]$tool.command
foreach ($k in $fill.Keys) { $command = $command.Replace('{' + $k + '}', [string]$fill[$k]) }
if ($command -match '\{[A-Za-z]+\}') { throw "Tool '$Name' left a placeholder unfilled: $command" }

if ($env:VIDEO_PAD_AGENT -eq 'dry') { return $command }
if ($TimeoutSeconds -le 0) {
    $TimeoutSeconds = $(if ($fill['timeoutSeconds']) { [int]$fill['timeoutSeconds'] } else { 3600 })
}

& (Join-Path $PSScriptRoot '..\tools\Invoke-AgentStep.ps1') -Step $Name -Command $command -TimeoutSeconds $TimeoutSeconds |
    ConvertFrom-Json
