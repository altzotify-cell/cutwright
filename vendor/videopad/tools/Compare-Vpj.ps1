<#
.SYNOPSIS
    Field-level diff of two .vpj files, matched by record identity.

.DESCRIPTION
    The autosave oracle only pays off if the comparison is trustworthy: the app
    re-serialises records in its own order, so a line-by-line diff reports noise,
    and effect blobs are URL-encoded twice over, so a raw diff hides real changes
    inside percent signs. This matches records by what identifies them — a clip's
    handle, an effectchains record's hclip, a media handle, a sequence handle —
    and then compares field by field, decoding preset/data blobs before comparing
    them.

    That is the check behind every "round-tripped unchanged" claim in
    docs/HANDOFF.md:

        .\tools\Compare-Vpj.ps1 -A .\out\cut5-cadence.vpj `
                                -B .\out\oracle\cut5-cadence.roundtrip.vpj

    Expected output for a healthy project is either "no differences" or only the
    sequence record's thumb/thumbpos (VideoPad zeroes its thumbnail cache on load).
    Anything else is a real change: the app clamps a clip, drops a record, or
    re-derives a preset label (which is expected when params were overridden —
    diff dataN, never presetN).

.PARAMETER A
    The file as written (left side).

.PARAMETER B
    The file as returned by the app (right side).

.OUTPUTS
    Text lines "  <record> <field> '<old>' -> '<new>'" plus a count.

.EXAMPLE
    .\Compare-Vpj.ps1 -A .\out\cut4-split-effects.vpj -B .\out\oracle\cut4-split-effects.roundtrip.vpj
#>
param(
    [Parameter(Mandatory = $true)][string]$A,
    [Parameter(Mandatory = $true)][string]$B
)

$ErrorActionPreference = 'Stop'
function Get-F1 {
    param([string]$Line, [string]$Key)
    $m = [regex]::Match($Line, '(?:^|&)' + [regex]::Escape($Key) + '=([^&]*)')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Read-Records([string]$Path) {
    $rec = [ordered]@{}
    foreach ($l in (Get-Content -LiteralPath $Path)) {
        $key = $null
        if ($l -match '^size=' -and $l -match '(?:^|&)hclip=(\d+)') { $key = 'ec:' + $Matches[1] }
        elseif ($l -match '^h=(\d+)&type=7&') { $key = 'tc:' + $Matches[1] }
        elseif ($l -match '^h=(\d+)&type=6&') { $key = 'seq:' + $Matches[1] }
        elseif ($l -match '^h=(\d+)&type=[35]&') { $key = 'media:' + $Matches[1] }
        elseif ($l -match '^(tracks?|transitions|subtitletracks|subtitleclips|groups|bookmarks|folders|clips|effectchains)=(\d+)$') {
            $key = 'count:' + $Matches[1]
            $rec[$key] = $l
            continue
        }
        if ($key) { $rec[$key] = $l }
    }
    return $rec
}

$ra = Read-Records $A
$rb = Read-Records $B

$changed = 0
foreach ($k in $ra.Keys) {
    if (-not $rb.Contains($k)) { "MISSING in B : $k"; $changed++; continue }
    if ($ra[$k] -eq $rb[$k]) { continue }
    $la = $ra[$k]; $lb = $rb[$k]
    $ka = @($la -split '&' | ForEach-Object { ($_ -split '=', 2)[0] })
    $kb = @($lb -split '&' | ForEach-Object { ($_ -split '=', 2)[0] })
    foreach ($f in ($ka + $kb | Sort-Object -Unique)) {
        $va = Get-F1 $la $f
        $vb = Get-F1 $lb $f
        if ($va -ne $vb) {
            if ($f -match '^(preset|data)\d+$' -and [Math]::Floor([int]($f -replace '\D', '')) -ge 0) {
                # effect blobs are compared decoded and only when they really differ
                $da = [uri]::UnescapeDataString([string]$va)
                $db = [uri]::UnescapeDataString([string]$vb)
                if ($da -eq $db) { continue }
                "  {0,-12} {1,-16} '{2}' -> '{3}'" -f $k, $f, $da, $db
            }
            else {
                "  {0,-12} {1,-16} '{2}' -> '{3}'" -f $k, $f, $va, $vb
            }
            $changed++
        }
    }
}
foreach ($k in $rb.Keys) {
    if (-not $ra.Contains($k)) { "ADDED in B   : $k"; $changed++ }
}

if ($changed -eq 0) { 'no differences' } else { "`n$changed difference(s)" }
