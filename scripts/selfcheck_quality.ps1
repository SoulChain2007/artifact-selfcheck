<#
.SYNOPSIS
  Quality scorer and ledger statistician for the artifact-selfcheck skill.
.DESCRIPTION
  -Mode score  : read one JSON object describing this round's gate results and dimension
                 scores; print SA/SR/total/percent/grade plus failing gates and any
                 self-assessment drift against an independent reviewer's scores.
  -Mode ledger : read a selfcheck_ledger.jsonl file; print per-lens detection stats,
                 classes seen twice or more, trailing zero-yield streaks, verify aging and
                 the quality-score trend.
  Input formats are documented in the skill's references/quality.md and references/learning.md.
  Windows PowerShell 5.1 safe: no "if" used as an expression, no ordered-dictionary cast.
.PARAMETER Mode
  score | ledger
.PARAMETER Scores
  score mode: path to a JSON file, or inline JSON text.
.PARAMETER Ledger
  ledger mode: path to the .jsonl ledger.
.PARAMETER SelfWeight
  Weight of the self-check half (default 0.5; the sourcing half gets 1 - SelfWeight).
.PARAMETER DropThreshold
  Dimension score at or below which a dimension counts as "low" (default 2).
.PARAMETER ZeroYieldStreak
  Trailing rounds with an empty class before a lens becomes a zombie-rule candidate (default 3).
.PARAMETER Json
  Emit machine-readable JSON instead of text lines.
.NOTES
  Exit code: 0 on success, 1 when the input cannot be read or parsed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('score', 'ledger')][string]$Mode,
    [string]$Scores,
    [string]$Ledger,
    [double]$SelfWeight = 0.5,
    [double]$DropThreshold = 2.0,
    [int]$ZeroYieldStreak = 3,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$SA_NAMES = @('sa1', 'sa2', 'sa3', 'sa4', 'sa5', 'sa6')
$SR_NAMES = @('sr1', 'sr2', 'sr3', 'sr4', 'sr5', 'sr6')
$GATE_NAMES = @('g1', 'g2', 'g3', 'g4', 'g5', 'g6')

function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Get-HalfScore {
    param($Object, [string[]]$Names)
    $sum = 0.0
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($n in $Names) {
        $v = Get-Prop $Object $n
        if ($null -eq $v) {
            $missing.Add($n) | Out-Null
        } else {
            $sum = $sum + [double]$v
        }
    }
    # A missing dimension counts as 0, never as "not asked": the report contract
    # requires all six dimensions, so an absent one is a real defect.
    $mean = $sum / [double]$Names.Count
    return New-Object psobject -Property @{ Mean = $mean; Missing = $missing }
}

function Join-List {
    param($Items, [string]$WhenEmpty)
    if ($null -eq $Items) { return $WhenEmpty }
    # Windows PowerShell 5.1 throws "Argument types do not match" when @() folds a
    # generic List whose elements are custom objects, so count and join explicitly.
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($item in $Items) { $parts.Add([string]$item) | Out-Null }
    if ($parts.Count -eq 0) { return $WhenEmpty }
    return ($parts -join ',')
}

if ($Mode -eq 'score') {
    if ([string]::IsNullOrWhiteSpace($Scores)) {
        Write-Output 'ERROR: -Scores is required for -Mode score'
        exit 1
    }
    $raw = $Scores
    $isFile = Test-Path -LiteralPath $Scores
    if ($isFile) { $raw = Get-Content -LiteralPath $Scores -Raw -Encoding UTF8 }

    $payload = $null
    try {
        $payload = $raw | ConvertFrom-Json
    } catch {
        Write-Output ('ERROR: -Scores is not valid JSON: ' + $_.Exception.Message)
        exit 1
    }

    $gatesObj = Get-Prop $payload 'gates'
    $gateState = New-Object psobject -Property @{}
    $hardFails = New-Object System.Collections.Generic.List[string]
    foreach ($g in $GATE_NAMES) {
        $v = Get-Prop $gatesObj $g
        if ($v -eq $true) {
            $gateState | Add-Member -NotePropertyName $g -NotePropertyValue 'pass'
        } elseif ($null -eq $v) {
            $gateState | Add-Member -NotePropertyName $g -NotePropertyValue 'missing'
            $hardFails.Add($g) | Out-Null
        } else {
            $gateState | Add-Member -NotePropertyName $g -NotePropertyValue 'FAIL'
            $hardFails.Add($g) | Out-Null
        }
    }

    $saObj = Get-Prop $payload 'sa'
    $srObj = Get-Prop $payload 'sr'
    $sa = Get-HalfScore $saObj $SA_NAMES
    $sr = Get-HalfScore $srObj $SR_NAMES
    $total = ($SelfWeight * $sa.Mean) + ((1.0 - $SelfWeight) * $sr.Mean)
    $percent = [Math]::Round(($total / 5.0) * 100.0, 2)

    $grade = 'D'
    if ($hardFails.Count -gt 0) { $grade = 'F' }
    elseif ($percent -ge 90) { $grade = 'A' }
    elseif ($percent -ge 78) { $grade = 'B' }
    elseif ($percent -ge 66) { $grade = 'C' }

    $lowDims = New-Object System.Collections.Generic.List[string]
    foreach ($n in $SA_NAMES) {
        $v = Get-Prop $saObj $n
        if (($null -ne $v) -and ([double]$v -le $DropThreshold)) { $lowDims.Add($n) | Out-Null }
    }
    foreach ($n in $SR_NAMES) {
        $v = Get-Prop $srObj $n
        if (($null -ne $v) -and ([double]$v -le $DropThreshold)) { $lowDims.Add($n) | Out-Null }
    }

    # Self-assessment drift: when the independent reviewer's scores are supplied, any
    # dimension differing by more than 1 point is a drift finding and the reviewer wins.
    $revSaObj = Get-Prop $payload 'review_sa'
    $revSrObj = Get-Prop $payload 'review_sr'
    $hasReview = $false
    if (($null -ne $revSaObj) -or ($null -ne $revSrObj)) { $hasReview = $true }
    $drift = New-Object System.Collections.Generic.List[object]
    if ($hasReview) {
        foreach ($n in $SA_NAMES) {
            $a = Get-Prop $saObj $n
            $b = Get-Prop $revSaObj $n
            if (($null -ne $a) -and ($null -ne $b)) {
                if ([Math]::Abs([double]$a - [double]$b) -gt 1.0) {
                    $drift.Add((New-Object psobject -Property @{ dimension = $n; self = [double]$a; reviewer = [double]$b })) | Out-Null
                }
            }
        }
        foreach ($n in $SR_NAMES) {
            $a = Get-Prop $srObj $n
            $b = Get-Prop $revSrObj $n
            if (($null -ne $a) -and ($null -ne $b)) {
                if ([Math]::Abs([double]$a - [double]$b) -gt 1.0) {
                    $drift.Add((New-Object psobject -Property @{ dimension = $n; self = [double]$a; reviewer = [double]$b })) | Out-Null
                }
            }
        }
    }

    $revSaMean = $null
    $revSrMean = $null
    if ($null -ne $revSaObj) { $revSaMean = [Math]::Round((Get-HalfScore $revSaObj $SA_NAMES).Mean, 3) }
    if ($null -ne $revSrObj) { $revSrMean = [Math]::Round((Get-HalfScore $revSrObj $SR_NAMES).Mean, 3) }

    $missingAll = $sa.Missing.ToArray() + $sr.Missing.ToArray()
    $driftFlag = $false
    if ($drift.Count -gt 0) { $driftFlag = $true }

    $result = New-Object psobject -Property @{
        mode        = 'score'
        artifactType = [string](Get-Prop $payload 'artifact_type')
        selfWeight  = $SelfWeight
        sa          = [Math]::Round($sa.Mean, 3)
        sr          = [Math]::Round($sr.Mean, 3)
        total       = [Math]::Round($total, 3)
        percent     = $percent
        grade       = $grade
        hardFails   = $hardFails.ToArray()
        gates       = $gateState
        missingDims = $missingAll
        lowDims     = $lowDims.ToArray()
        drift       = $drift.ToArray()
        driftFlag   = $driftFlag
        reviewerSa  = $revSaMean
        reviewerSr  = $revSrMean
    }

    if ($Json) {
        Write-Output ($result | ConvertTo-Json -Depth 6 -Compress)
        exit 0
    }

    Write-Output ('grade=' + $grade + ' percent=' + $percent + ' sa=' + $result.sa + ' sr=' + $result.sr + ' total=' + $result.total + ' selfWeight=' + $SelfWeight)
    $gateLine = New-Object System.Collections.Generic.List[string]
    foreach ($g in $GATE_NAMES) { $gateLine.Add($g + '=' + $gateState.$g) | Out-Null }
    Write-Output ('gates: ' + ($gateLine -join ' '))
    Write-Output ('hardFails=' + (Join-List $hardFails 'none') + '  (any hard fail forces grade F; g3/g4/g6 must never be "missing")')
    Write-Output ('missingDimensions=' + (Join-List $missingAll 'none') + '  (counted as 0 in the mean)')
    Write-Output ('lowDimensions(<= ' + $DropThreshold + ')=' + (Join-List $lowDims 'none') + '  (two consecutive rounds triggers a meta review)')
    if ($hasReview) {
        $driftText = 'none'
        if ($drift.Count -gt 0) {
            $parts = New-Object System.Collections.Generic.List[string]
            foreach ($d in $drift) { $parts.Add($d.dimension + '(' + $d.self + 'vs' + $d.reviewer + ')') | Out-Null }
            $driftText = ($parts -join ',')
        }
        Write-Output ('reviewer: sa=' + $revSaMean + ' sr=' + $revSrMean + ' reviewWeight=' + (1.0 - $SelfWeight) + ' driftDimensions=' + $driftText)
        if ($driftFlag) { Write-Output 'self_assessment_drift=true -> reviewer scores win (quality.md section 4)' }
    } else {
        Write-Output 'reviewer: not supplied (independent review is gate g5, so g5 cannot pass without it)'
    }
    exit 0
}

# ---------------------------------------------------------------- ledger mode

if ([string]::IsNullOrWhiteSpace($Ledger)) {
    Write-Output 'ERROR: -Ledger is required for -Mode ledger'
    exit 1
}
if (-not (Test-Path -LiteralPath $Ledger)) {
    Write-Output ('ERROR: ledger not found: ' + $Ledger)
    exit 1
}

# Label normalisation: the lens column is free text in practice, so known spellings map
# onto the six canonical lenses and anything unknown is reported instead of silently
# merged. Combined labels ("A/B") count for both sides.
$lensAlias = @{
    '声称↔实存' = '声称↔实存'
    '应有↔实有' = '应有↔实有'
    '内部一致'   = '内部一致'
    '一致性'     = '内部一致'
    '引用完整'   = '引用完整'
    '可验证性'   = '可验证性'
    '注意力限制' = '注意力限制'
    '迭代'       = '迭代'
    '溯源'       = '溯源'
}

$rows = New-Object System.Collections.Generic.List[object]
$parseErrors = 0
$blankLines = 0
foreach ($line in (Get-Content -LiteralPath $Ledger -Encoding UTF8)) {
    $t = $line.Trim()
    if ($t.Length -eq 0) { $blankLines = $blankLines + 1; continue }
    try {
        $rows.Add(($t | ConvertFrom-Json)) | Out-Null
    } catch {
        $parseErrors = $parseErrors + 1
    }
}

$lensRuns = @{}
$lensYields = @{}
$lensStreak = @{}
$lensLastBatch = @{}
$unknownLabels = New-Object System.Collections.Generic.List[string]
$classCounts = @{}
$missingVerify = New-Object System.Collections.Generic.List[object]
$verifyNoCmdHint = New-Object System.Collections.Generic.List[object]
$qualityRows = New-Object System.Collections.Generic.List[object]
$driftRows = New-Object System.Collections.Generic.List[object]
$cmdHints = @('.ps1', '.py', '.sh', '.cmd', '.bat', 'powershell', 'python', 'dotnet', 'npm ', 'rg ', 'git ', 'node ', 'pwsh')

foreach ($r in $rows) {
    $batch = [string](Get-Prop $r 'batch')
    $lensRaw = [string](Get-Prop $r 'lens')
    $class = [string](Get-Prop $r 'class')
    $verify = [string](Get-Prop $r 'verify')
    $hasYield = $false
    if (-not [string]::IsNullOrWhiteSpace($class)) { $hasYield = $true }

    $labels = New-Object System.Collections.Generic.List[string]
    foreach ($part in ($lensRaw -split '[/、,，]')) {
        $p = $part.Trim()
        if ($p.Length -eq 0) { continue }
        if ($lensAlias.ContainsKey($p)) {
            $labels.Add($lensAlias[$p]) | Out-Null
        } else {
            $labels.Add($p) | Out-Null
            if (-not $unknownLabels.Contains($p)) { $unknownLabels.Add($p) | Out-Null }
        }
    }
    if ($labels.Count -eq 0) { $labels.Add('(blank)') | Out-Null }

    foreach ($l in $labels) {
        if (-not $lensRuns.ContainsKey($l)) {
            $lensRuns[$l] = 0
            $lensYields[$l] = 0
            $lensStreak[$l] = 0
        }
        $lensRuns[$l] = $lensRuns[$l] + 1
        if ($hasYield) {
            $lensYields[$l] = $lensYields[$l] + 1
            $lensStreak[$l] = 0
        } else {
            $lensStreak[$l] = $lensStreak[$l] + 1
        }
        $lensLastBatch[$l] = $batch
    }

    if ($hasYield) {
        if (-not $classCounts.ContainsKey($class)) { $classCounts[$class] = 0 }
        $classCounts[$class] = $classCounts[$class] + 1
    }

    if ([string]::IsNullOrWhiteSpace($verify) -or ($verify -eq 'null')) {
        $missingVerify.Add((New-Object psobject -Property @{ batch = $batch; date = [string](Get-Prop $r 'date'); lens = $lensRaw })) | Out-Null
    } else {
        $low = $verify.ToLowerInvariant()
        $hit = $false
        foreach ($h in $cmdHints) {
            if ($low.Contains($h)) { $hit = $true; break }
        }
        if (-not $hit) {
            $verifyNoCmdHint.Add((New-Object psobject -Property @{ batch = $batch; lens = $lensRaw; verify = $verify })) | Out-Null
        }
    }

    $q = Get-Prop $r 'quality'
    if ($null -ne $q) {
        $qualityRows.Add((New-Object psobject -Property @{
                    batch   = $batch
                    date    = [string](Get-Prop $r 'date')
                    grade   = [string](Get-Prop $q 'grade')
                    percent = Get-Prop $q 'percent'
                    total   = Get-Prop $q 'total'
                })) | Out-Null
        $d = Get-Prop $q 'drift'
        if ($null -ne $d) {
            $dCount = 0
            foreach ($x in $d) { $dCount = $dCount + 1 }
            if ($dCount -gt 0) {
                $driftRows.Add((New-Object psobject -Property @{ batch = $batch; entries = $dCount })) | Out-Null
            }
        }
    }
}

$classesRepeated = New-Object System.Collections.Generic.List[object]
$zombies = New-Object System.Collections.Generic.List[object]
$lensTable = New-Object System.Collections.Generic.List[object]
foreach ($k in ($lensRuns.Keys | Sort-Object)) {
    $runs = $lensRuns[$k]
    $y = $lensYields[$k]
    $rate = 0
    if ($runs -gt 0) { $rate = [Math]::Round((100.0 * $y) / $runs, 1) }
    $lensTable.Add((New-Object psobject -Property @{
                lens          = $k
                runs          = $runs
                yields        = $y
                detectionRate = $rate
                zeroStreak    = $lensStreak[$k]
                lastBatch     = $lensLastBatch[$k]
            })) | Out-Null
    if ($lensStreak[$k] -ge $ZeroYieldStreak) {
        $zombies.Add((New-Object psobject -Property @{ lens = $k; trailingZeroYield = $lensStreak[$k] })) | Out-Null
    }
}
foreach ($kv in ($classCounts.GetEnumerator() | Sort-Object -Property Value -Descending)) {
    if ($kv.Value -ge 2) {
        $classesRepeated.Add((New-Object psobject -Property @{ class = $kv.Key; count = $kv.Value })) | Out-Null
    }
}

$recap = New-Object psobject -Property @{
    mode              = 'ledger'
    path              = $Ledger
    rows              = $rows.Count
    parseErrors       = $parseErrors
    blankLines        = $blankLines
    roundsWithQuality = $qualityRows.Count
    lensTable         = $lensTable.ToArray()
    classesRepeated   = $classesRepeated.ToArray()
    zombieCandidates  = $zombies.ToArray()
    verifyMissing     = $missingVerify.ToArray()
    verifyNoCommandHint = $verifyNoCmdHint.ToArray()
    qualityTrend      = $qualityRows.ToArray()
    driftRows         = $driftRows.ToArray()
    unknownLensLabels = $unknownLabels.ToArray()
}

if ($Json) {
    Write-Output ($recap | ConvertTo-Json -Depth 8 -Compress)
    exit 0
}

Write-Output ('ledger=' + $Ledger)
Write-Output ('rows=' + $rows.Count + ' parseErrors=' + $parseErrors + ' blankLines=' + $blankLines + ' roundsWithQuality=' + $qualityRows.Count)
Write-Output ''
Write-Output 'per-lens detection (runs = rows naming this lens, yields = rows with a non-empty class):'
Write-Output ($lensTable | Format-Table -AutoSize | Out-String -Width 200)
$repeatedText = New-Object System.Collections.Generic.List[string]
foreach ($cr in $classesRepeated) { $repeatedText.Add($cr.class + '=' + $cr.count) | Out-Null }
Write-Output ('classes seen twice or more (forces a meta review): ' + (Join-List $repeatedText 'none'))
Write-Output ''
$zombieText = New-Object System.Collections.Generic.List[string]
foreach ($z in $zombies) { $zombieText.Add($z.lens + '(' + $z.trailingZeroYield + ')') | Out-Null }
Write-Output ('zombie-rule candidates (trailing zero-yield >= ' + $ZeroYieldStreak + '): ' + (Join-List $zombieText 'none'))
Write-Output '  NOTE: zero yield alone is not proof a lens is useless. Split the cause: (a) that defect class is really gone -> keep it, but sample; (b) the rule is too soft -> move to a harder evidence source. Never delete a rule just because it caught nothing this round.'
Write-Output ''
Write-Output ('verify missing/empty rows: ' + $missingVerify.Count)
if ($missingVerify.Count -gt 0) { Write-Output ($missingVerify | Format-Table -AutoSize | Out-String -Width 200) }
Write-Output ('verify rows with no command-like token (heuristic, advisory): ' + $verifyNoCmdHint.Count)
if ($verifyNoCmdHint.Count -gt 0) { Write-Output ($verifyNoCmdHint | Format-Table -AutoSize | Out-String -Width 220) }
Write-Output ''
if ($qualityRows.Count -eq 0) {
    Write-Output 'quality trend: no row carries a "quality" object yet (older ledger lines stay legal; they count as rounds without a quality reading, not as zero scores).'
} else {
    Write-Output 'quality trend:'
    Write-Output ($qualityRows | Format-Table -AutoSize | Out-String -Width 200)
    $nums = New-Object System.Collections.Generic.List[double]
    foreach ($q in $qualityRows) {
        if ($null -ne $q.percent) { $nums.Add([double]$q.percent) | Out-Null }
    }
    if ($nums.Count -ge 2) {
        Write-Output ('first=' + $nums[0] + ' last=' + $nums[$nums.Count - 1] + ' delta=' + [Math]::Round($nums[$nums.Count - 1] - $nums[0], 2))
    }
}
if ($driftRows.Count -gt 0) {
    $driftBatchText = New-Object System.Collections.Generic.List[string]
    foreach ($dr in $driftRows) { $driftBatchText.Add([string]$dr.batch) | Out-Null }
    Write-Output ('self_assessment_drift rows: ' + (Join-List $driftBatchText 'none'))
}
if ($unknownLabels.Count -gt 0) {
    Write-Output ''
    Write-Output ('unknown lens labels (normalise them in the ledger, or extend the alias table): ' + ($unknownLabels -join ' '))
}
exit 0
