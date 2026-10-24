<#
.SYNOPSIS
    Lists the effects a spec may name, with their ids and parameter ranges.

.DESCRIPTION
    tools/effects.json is the vocabulary a spec writes in "effects" /
    "defaultEffects", but it is a data file full of percent-encoded VideoPad blobs,
    so reading it is a poor way to answer the two questions that come up while
    writing a spec: which names are legal, and what may each parameter be set to.

    This prints that. It needs no VideoPad and it never writes anything, so it is
    safe to run any time.

.OUTPUTS
    Without -Json: text. A table of Name / Id / Category / Params / Presets, or a
    detail block when -Name is given. With -Json: the same selection as JSON.

.PARAMETER Name
    Show one effect in full: id, category, summary, every parameter with its type,
    default and allowed range (or enum values), and the app's preset names.

.PARAMETER Category
    Only effects in this category - audio, geometry, colour, style, overlay...

.PARAMETER Skeleton
    With -Name: print a spec fragment for that effect with every parameter at its
    default, ready to trim down and paste into an "effects" array.

.PARAMETER Json
    Emit machine-readable JSON instead of text.

.EXAMPLE
    .\Get-Effects.ps1

.EXAMPLE
    .\Get-Effects.ps1 -Name cartoon

.EXAMPLE
    .\Get-Effects.ps1 -Name snow -Skeleton
#>
[CmdletBinding()]
param(
    [string]$Name,
    [string]$Category,
    [switch]$Skeleton,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

$path = Join-Path $PSScriptRoot 'effects.json'
if (-not (Test-Path -LiteralPath $path)) { throw "Effect registry not found: $path" }
$registry = (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json).effects

# Name order is kept from the registry file rather than sorted: it groups effects
# by the order they were captured, which is roughly by family.
$all = @(foreach ($p in $registry.PSObject.Properties) {
    [pscustomobject]@{ Name = $p.Name; Def = $p.Value }
})

if ($all.Count -eq 0) { throw "Effect registry is empty: $path" }

if ($Name) {
    $wanted = @($all | Where-Object { $_.Name -eq $Name })
    if ($wanted.Count -eq 0) {
        $known = ($all | ForEach-Object { $_.Name }) -join ', '
        throw "Unknown effect '$Name'. Known effects: $known"
    }
    $all = $wanted
}

if ($Category) {
    $filtered = @($all | Where-Object { [string]$_.Def.category -eq $Category })
    if ($filtered.Count -eq 0) {
        $cats = (@($all | ForEach-Object { [string]$_.Def.category } | Sort-Object -Unique)) -join ', '
        throw "No effect in category '$Category'. Categories: $cats"
    }
    $all = $filtered
}

if ($Skeleton -and -not $Name) { throw '-Skeleton needs -Name, so it knows which effect to describe.' }

# The shape other tools consume: no blobs, no wrap flags, just what a caller sets.
function New-EffectRow {
    param($Entry)
    $def = $Entry.Def
    $params = @(foreach ($p in @($def.params)) {
        $row = [ordered]@{
            key     = [string]$p.key
            type    = [string]$p.type
            default = $p.default
        }
        if ($null -ne $p.min) { $row.min = $p.min }
        if ($null -ne $p.max) { $row.max = $p.max }
        if ($p.PSObject.Properties.Name -contains 'values') {
            $row.values = (@($p.values.PSObject.Properties |
                ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' ')
        }
        [pscustomobject]$row
    })
    [pscustomobject][ordered]@{
        name     = $Entry.Name
        id       = [int64]$def.id
        label    = [string]$def.label
        category = [string]$def.category
        summary  = [string]$def.summary
        params   = $params
        presets  = @(@($def.presets.PSObject.Properties) | ForEach-Object { $_.Name })
        identity = $(if ($def.PSObject.Properties.Name -contains 'identity' -and $def.identity) {
                (@($def.identity.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' ')
            } else { $null })
    }
}

$rows = @(foreach ($entry in $all) { New-EffectRow $entry })

if ($Json) {
    if ($rows.Count -eq 1) { $rows[0] | ConvertTo-Json -Depth 8 }
    else { , $rows | ConvertTo-Json -Depth 8 }
    return
}

function Format-Range {
    param($Param)
    if ($Param.PSObject.Properties.Name -contains 'values') { return $Param.values }
    if ($null -eq $Param.min -and $null -eq $Param.max) { return 'any' }
    $min = if ($null -ne $Param.min) { $Param.min } else { '-inf' }
    $max = if ($null -ne $Param.max) { $Param.max } else { '+inf' }
    return "$min..$max"
}

# Summaries run to a paragraph each; wrap on word boundaries so they stay readable
# in a normal-width console.
function Format-Wrapped {
    param([string]$Text, [int]$Width = 96, [string]$Indent = '  ')
    $line = ''
    foreach ($word in ($Text -split '\s+' | Where-Object { $_ })) {
        if ($line.Length -eq 0) { $line = $word }
        elseif (($line.Length + 1 + $word.Length) -le $Width) { $line = "$line $word" }
        else { "$Indent$line"; $line = $word }
    }
    if ($line.Length -gt 0) { "$Indent$line" }
}

if ($Skeleton) {
    $row = $rows[0]
    $body = [ordered]@{ name = $row.name }
    $params = [ordered]@{}
    foreach ($p in $row.params) { $params[$p.key] = $p.default }
    if ($params.Count -gt 0) { $body['params'] = $params }
    $snippet = [ordered]@{ effects = @($body) }
    '# paste into a segment effects array; delete the lines you do not want to set'
    if ($row.identity) {
        "# above is the app's default blob; $($row.name) has a measured no-op too - use { `"name`": `"$($row.name)`", `"identity`": true } (=$($row.identity)) to keep the picture unchanged"
    }
    $snippet | ConvertTo-Json -Depth 6
    return
}

if ($rows.Count -eq 1) {
    $row = $rows[0]
    ''
    "$($row.name)  (id $($row.id), $($row.category)) - $($row.label)"
    ''
    Format-Wrapped -Text $row.summary
    ''
    '  parameter      type     default    allowed'
    '  ---------      ----     -------    -------'
    foreach ($p in $row.params) {
        '  {0,-14} {1,-8} {2,-10} {3}' -f $p.key, $p.type, $p.default, (Format-Range $p)
    }
    ''
    if ($row.presets.Count -gt 0) { "  presets: $($row.presets -join ', ')" }
    else { '  presets: none - "default" is the app default' }
    if ($row.identity) {
        "  identity: $($row.identity)  (measured no-op; `"identity`": true in a spec)"
    }
    ''
    return
}

$nameWidth = [Math]::Max(12, (($rows | ForEach-Object { $_.name.Length }) | Measure-Object -Maximum).Maximum)
$catWidth = [Math]::Max(8, (($rows | ForEach-Object { $_.category.Length }) | Measure-Object -Maximum).Maximum)
$rowFormat = '{0,-' + $nameWidth + '} {1,4}  {2,-' + $catWidth + '} {3,6} {4,7}'
''
$rowFormat -f 'name', 'id', 'category', 'params', 'presets'
$rowFormat -f ('-' * $nameWidth), '--', ('-' * $catWidth), '------', '-------'
foreach ($row in $rows) {
    $rowFormat -f $row.name, $row.id, $row.category, $row.params.Count, $row.presets.Count
}
''
"$($rows.Count) effect(s). .\Get-Effects.ps1 -Name <name> for the parameters."
''
