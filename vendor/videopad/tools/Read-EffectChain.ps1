<#
.SYNOPSIS
    Reads the effect chains out of a .vpj and names every effect id it can.

.DESCRIPTION
    The only reliable way to learn what an uncatalogued effect *is* is to apply it
    in VideoPad once and look at what the app writes. This is the reading half of
    that loop: point it at the saved project and it prints, per clip and per slot,
    the numeric effect id, the name the registry knows that id by, and the
    parameters the app stored, already decoded from the double-encoded blob.

    An id the registry does not contain comes back with Effect '?' - that is a
    capture worth adding. -Unknown shows only those rows.

    Decoding, because the blob is nested twice:
        stored   size=1&type0=41&data0=cc%3Dvalue%253D11.0...
        once     cc=value%3D11.0%26userdata%3D0%26keys%3D0
        twice    cc=11.0  userdata=0  keys=0

.PARAMETER Project
    Path to a .vpj (a hand-saved capture or any project this writer produced).

.PARAMETER Unknown
    Only rows whose id is missing from tools/effects.json.

.PARAMETER Json
    Emit objects instead of a table.

.OUTPUTS
    PSCustomObject per slot: Clip, Slot, Id, Effect, RegistryId, Params, Default

.EXAMPLE
    .\Read-EffectChain.ps1 -Project out\capture.vpj

.EXAMPLE
    .\Read-EffectChain.ps1 -Project out\capture.vpj -Unknown
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Project,
    [switch]$Unknown,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Project)) { throw "Project not found: $Project" }
$Project = (Resolve-Path -LiteralPath $Project).Path

$registryPath = Join-Path $PSScriptRoot 'effects.json'
$registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json

# id -> effect key, so a row can say "cartoon" instead of "41".
$byId = @{}
foreach ($prop in $registry.effects.PSObject.Properties) {
    $byId[[int64]$prop.Value.id] = $prop
}

function ConvertFrom-Percent {
    param([string]$Text)
    if (-not $Text) { return '' }
    return [Uri]::UnescapeDataString($Text)
}

# "cc=value%3D11.0%26userdata%3D0%26keys%3D0&et=..." -> ordered "cc=11.0 et=58.0 ..."
function ConvertFrom-EffectBlob {
    param([string]$Blob)
    $pairs = foreach ($part in ($Blob -split '&')) {
        if (-not $part) { continue }
        $split = $part.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $part.Substring(0, $split)
        $inner = ConvertFrom-Percent $part.Substring($split + 1)
        # inner looks like value=11.000000&userdata=0&keys=0
        $value = ($inner -split '&')[0]
        $eq = $value.IndexOf('=')
        if ($eq -ge 0) { $value = $value.Substring($eq + 1) }
        "$key=$value"
    }
    return (@($pairs) -join ' ')
}

# The chain records are the N lines that follow "effectchains=N"; each is one
# clip's stack, with slots numbered 0..size-1.
$lines = Get-Content -LiteralPath $Project
$rows = New-Object System.Collections.Generic.List[object]
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -notmatch '^effectchains=(\d+)$') { continue }
    $count = [int]$Matches[1]
    for ($r = 1; $r -le $count; $r++) {
        $line = $lines[$i + $r]
        if (-not $line -or $line -notmatch '^size=(\d+)') { continue }
        $fields = @{}
        foreach ($part in ($line -split '&')) {
            $split = $part.IndexOf('=')
            if ($split -gt 0) { $fields[$part.Substring(0, $split)] = $part.Substring($split + 1) }
        }
        if (-not $fields.ContainsKey('size')) { continue }
        $size = [int]$fields['size']
        for ($slot = 0; $slot -lt $size; $slot++) {
            $raw = $fields["type$slot"]
            if (-not $raw) { continue }
            $id = [int64]$raw
            $blob = ConvertFrom-Percent $fields["data$slot"]
            $params = ConvertFrom-EffectBlob $blob
            $known = $byId.ContainsKey($id)
            $rows.Add([pscustomobject][ordered]@{
                Clip       = [string]$fields['hclip']
                Slot       = $slot
                Id         = $id
                Effect     = $(if ($known) { $byId[$id].Name } else { '?' })
                Preset     = ConvertFrom-Percent $fields["preset$slot"]
                Params     = $params
                Default    = $(if ($known) { ($blob -eq [string]$byId[$id].Value.defaults) } else { $false })
                Blob       = $blob
            })
        }
    }
}

if ($Unknown) { $rows = @($rows | Where-Object { $_.Effect -eq '?' }) }

if ($Json) { , $rows | ConvertTo-Json -Depth 6; return }

if ($rows.Count -eq 0) {
    Write-Host 'No effects in this project.'
    return
}

$width = [Math]::Max(6, (($rows | ForEach-Object { $_.Effect.Length }) | Measure-Object -Maximum).Maximum)
$format = '{0,-6} {1,4} {2,4} {3}  {4,-' + $width + '} {5,-16} {6}'
''
$format -f 'clip', 'slot', 'id', 'd', 'effect', 'preset', 'parameters'
$format -f ('-' * 6), '----', '--', '-', ('-' * $width), ('-' * 16), ('-' * 10)
foreach ($row in $rows) {
    # d = the app's shipped defaults ('=') or values edited away from them ('~').
    $flag = if ($row.Default) { '=' } else { '~' }
    $format -f $row.Clip, $row.Slot, $row.Id, $flag, $row.Effect, $row.Preset, $row.Params
}
''
$new = @($rows | Where-Object { $_.Effect -eq '?' })
if ($new.Count -gt 0) {
    # The interesting output: ids that still need a registry entry.
    "$($new.Count) uncatalogued id(s): $(($new | ForEach-Object { $_.Id } | Sort-Object -Unique) -join ', ')"
} else {
    'Every id here is in tools/effects.json.'
}
''
