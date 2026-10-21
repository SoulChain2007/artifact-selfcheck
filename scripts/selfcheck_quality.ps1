<#
.SYNOPSIS
  Calculate quality scores or summarize a read-only JSONL ledger.
.DESCRIPTION
  Schema 2 executes quick/partial/full contracts. Inputs without schema_version
  retain the legacy full calculation, and are not v3 admission evidence.
  Evidence checks validate structure only; they cannot prove referenced claims.
  Exit 0: calculated (legacy includes F); 1: schema 2 grade F; 2: input error.
  Compatible with Windows PowerShell 5.1.
#>
[CmdletBinding()]
param(
    [string]$Mode,
    [string]$Scores,
    [string]$Ledger,
    $SelfWeight = 0.5,
    $DropThreshold = 2.0,
    $ZeroYieldStreak = 3,
    [string]$Project,
    [switch]$Json
)
$ErrorActionPreference = 'Stop'
$SA_NAMES = @('sa1','sa2','sa3','sa4','sa5','sa6')
$SR_NAMES = @('sr1','sr2','sr3','sr4','sr5','sr6')
$GATE_NAMES = @('g1','g2','g3','g4','g5','g6')
function Get-Prop {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -ne $p) { return $p.Value }
    return $null
}
function Has-Prop {
    param($Object, [string]$Name)
    return ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name])
}
function Test-Object {
    param($Value)
    return ($null -ne $Value -and $Value -is [System.Management.Automation.PSCustomObject])
}
function Test-Number {
    param($Value, [double]$Min, [double]$Max)
    if ($null -eq $Value -or $Value -is [bool] -or $Value -is [string]) { return $false }
    if ($Value -isnot [byte] -and $Value -isnot [sbyte] -and $Value -isnot [int16] -and $Value -isnot [uint16] -and $Value -isnot [int32] -and $Value -isnot [uint32] -and $Value -isnot [int64] -and $Value -isnot [uint64] -and $Value -isnot [single] -and $Value -isnot [double] -and $Value -isnot [decimal]) { return $false }
    $n = [double]$Value
    return (-not [double]::IsNaN($n) -and -not [double]::IsInfinity($n) -and $n -ge $Min -and $n -le $Max)
}
function Test-Text {
    param($Value)
    return ($Value -is [string] -and -not [string]::IsNullOrWhiteSpace($Value))
}
function Test-Refs {
    param($Value)
    if (Test-Text $Value) { return $true }
    if ($Value -is [array] -and $Value.Count -gt 0) {
        foreach ($v in $Value) { if (-not (Test-Text $v)) { return $false } }
        return $true
    }
    return $false
}
function Assert-Refs {
    param($Value, [string]$Name)
    if (-not (Test-Refs $Value)) { throw ($Name + ' requires a nonempty reference or reference array') }
}
function Get-HalfScore {
    param($Object, [string[]]$Names, [bool]$Required)
    if ($null -ne $Object -and -not (Test-Object $Object)) { throw 'dimension scores must be an object' }
    $sum = 0.0
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($n in $Names) {
        $v = Get-Prop $Object $n
        if ($null -eq $v) {
            if ($Required) { throw ('missing dimension: ' + $n) }
            $missing.Add($n) | Out-Null
        } else {
            if (-not (Test-Number $v 0 5)) { throw ($n + ' must be a finite number in 0..5') }
            $sum += [double]$v
        }
    }
    return [pscustomobject]@{ Mean = $sum / 6.0; Missing = $missing.ToArray() }
}
function Join-List {
    param($Items, [string]$WhenEmpty)
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($item in $Items) { $parts.Add([string]$item) | Out-Null }
    if ($parts.Count -eq 0) { return $WhenEmpty }
    return ($parts -join ',')
}
function Write-InputError {
    param([string]$Message)
    if ($Json) { Write-Output ([pscustomobject]@{ error = $Message; exitCode = 2 } | ConvertTo-Json -Compress) }
    else { Write-Output ('ERROR: ' + $Message) }
}
# CLI numeric parameters arrive as strings. Parse them explicitly without allowing
# booleans, NaN, infinities or culture-dependent text into arithmetic.
try {
    if (@('score','ledger') -notcontains $Mode) { throw '-Mode must be score or ledger' }
    foreach ($parameterName in @('SelfWeight','DropThreshold')) {
        $v = Get-Variable -Name $parameterName -ValueOnly
        if ($v -is [string]) {
            $parsed = 0.0
            if (-not [double]::TryParse($v, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)) { throw ($parameterName + ' must be numeric') }
            Set-Variable -Name $parameterName -Value $parsed
        }
    }
    if (-not (Test-Number $SelfWeight 0 1)) { throw 'SelfWeight must be finite in 0..1' }
    if (-not (Test-Number $DropThreshold 0 5)) { throw 'DropThreshold must be finite in 0..5' }
    if ($ZeroYieldStreak -is [string]) {
        $parsedStreak = 0
        if (-not [int]::TryParse($ZeroYieldStreak, [ref]$parsedStreak)) { throw 'ZeroYieldStreak must be a positive integer' }
        $ZeroYieldStreak = $parsedStreak
    }
    if (-not (Test-Number $ZeroYieldStreak 1 ([int]::MaxValue)) -or [Math]::Floor([double]$ZeroYieldStreak) -ne [double]$ZeroYieldStreak) { throw 'ZeroYieldStreak must be a positive integer' }
} catch { Write-InputError $_.Exception.Message; exit 2 }

if ($Mode -eq 'score') {
    try {
        if ([string]::IsNullOrWhiteSpace($Scores)) { throw '-Scores is required' }
        $raw = $Scores
        if (Test-Path -LiteralPath $Scores -PathType Leaf) { $raw = Get-Content -LiteralPath $Scores -Raw -Encoding UTF8 }
        # Check the root token as ConvertFrom-Json may unwrap a one-element array.
        if (-not $raw.TrimStart().StartsWith('{')) { throw 'scores root must be an object' }
        $payload = $raw | ConvertFrom-Json
        if (-not (Test-Object $payload)) { throw 'scores root must be an object' }
        $legacy = -not (Has-Prop $payload 'schema_version')
        $executionMode = 'full'
        $external = $true
        $srApplicable = $true
        if (-not $legacy) {
            $schema = Get-Prop $payload 'schema_version'
            if (-not (Test-Number $schema 2 2)) { throw 'only schema_version 2 is supported; omit it for legacy input' }
            $executionMode = Get-Prop $payload 'mode'
            if ($executionMode -isnot [string] -or @('quick','partial','full') -cnotcontains $executionMode) { throw 'schema 2 requires mode quick|partial|full' }
            $external = Get-Prop $payload 'external_claims'
            if ($external -isnot [bool]) { throw 'external_claims must be a JSON boolean' }
            if (-not (Has-Prop $payload 'sr')) { throw 'schema 2 requires sr (scores or explicit null)' }
            $srApplicable = ($null -ne (Get-Prop $payload 'sr'))
            if (-not $srApplicable) {
                if ($external) { throw 'external claims require all six SR scores' }
                if (-not (Test-Text (Get-Prop $payload 'sr_scope'))) { throw 'sr=null requires sr_scope' }
                if ($null -ne (Get-Prop $payload 'review_sr')) { throw 'review_sr cannot be scored when SR is not applicable' }
            }
        }
        $gatesObj = Get-Prop $payload 'gates'
        if (-not $legacy -and -not (Test-Object $gatesObj)) { throw 'schema 2 requires gates object' }
        $evidence = Get-Prop $payload 'evidence'
        $reasons = Get-Prop $payload 'gate_reasons'
        if (-not $legacy) {
            if (-not (Test-Object $evidence)) { throw 'schema 2 requires evidence object' }
            foreach ($g in @('g1','g2','g6')) { Assert-Refs (Get-Prop $evidence $g) ('evidence.' + $g) }
            if (-not $external -and -not (Test-Text (Get-Prop $reasons 'g3'))) { throw 'external_claims=false requires gate_reasons.g3' }
        }
        $hardFails = New-Object System.Collections.Generic.List[string]
        $gateState = [pscustomobject]@{}
        $singleSession = $false
        foreach ($g in $GATE_NAMES) {
            $v = Get-Prop $gatesObj $g
            $state = 'FAIL'
            if ($v -is [bool]) {
                if ($v) { $state = 'pass' }
            } elseif ($v -is [string] -and @('notdone','single_session','未做') -contains $v) {
                $state = 'notdone'
                if ($g -eq 'g5') {
                    if (-not $legacy -and -not (Test-Text (Get-Prop $reasons 'g5'))) { throw 'g5 notdone requires gate_reasons.g5' }
                    $singleSession = $true
                }
            } elseif ($v -is [string] -and $v -eq 'na' -and -not $legacy) {
                if (-not (($g -eq 'g3' -and -not $external) -or ($g -eq 'g5' -and $executionMode -eq 'quick'))) { throw ($g + ' cannot be na in this scope') }
                if (-not (Test-Text (Get-Prop $reasons $g))) { throw ($g + '=na requires gate_reasons.' + $g) }
                $state = 'na'
            } elseif ($null -eq $v) {
                if (-not $legacy) { throw ('missing gate: ' + $g) }
                $state = 'missing'
            } elseif (-not $legacy) { throw ($g + ' must be a boolean or an allowed na/notdone state') }
            if ($state -eq 'pass' -and -not $legacy) {
                if ($g -eq 'g3') { Assert-Refs (Get-Prop $evidence 'g3') 'evidence.g3' }
                if ($g -eq 'g4') {
                    Assert-Refs (Get-Prop $evidence 'g4') 'evidence.g4'
                    $kind = Get-Prop $payload 'g4_kind'
                    if ($executionMode -eq 'quick') {
                        if ($kind -cne 'reverse_check') { throw 'quick G4 requires g4_kind=reverse_check' }
                    } else {
                        if ($kind -cne 'sensitivity') { throw 'partial/full G4 requires g4_kind=sensitivity' }
                        $valid = Get-Prop $payload 'sensitivity_valid'
                        if ($valid -isnot [bool]) { throw 'sensitivity_valid must be a JSON boolean' }
                        if (-not $valid) { $state = 'FAIL' }
                    }
                }
                if ($g -eq 'g5') {
                    if (-not (Test-Text (Get-Prop $payload 'reviewer'))) { throw 'g5 pass requires reviewer identity' }
                    Assert-Refs (Get-Prop $payload 'review_evidence') 'review_evidence'
                }
            }
            $gateState | Add-Member -NotePropertyName $g -NotePropertyValue $state
            if ($state -eq 'FAIL' -or $state -eq 'missing' -or ($state -eq 'notdone' -and $g -ne 'g5')) { $hardFails.Add($g) | Out-Null }
        }
        $saObj = Get-Prop $payload 'sa'
        $srObj = Get-Prop $payload 'sr'
        $sa = Get-HalfScore $saObj $SA_NAMES (-not $legacy)
        $sr = $null
        if ($srApplicable) { $sr = Get-HalfScore $srObj $SR_NAMES (-not $legacy) }
        $effectiveSa = [pscustomobject]@{}
        $effectiveSr = [pscustomobject]@{}
        $drift = New-Object System.Collections.Generic.List[object]
        $reviewerSa = $null
        $reviewerSr = $null
        foreach ($half in @('sa','sr')) {
            if ($half -eq 'sr' -and -not $srApplicable) { continue }
            $names = $SA_NAMES; $selfObj = $saObj; $effective = $effectiveSa
            if ($half -eq 'sr') { $names = $SR_NAMES; $selfObj = $srObj; $effective = $effectiveSr }
            $review = Get-Prop $payload ('review_' + $half)
            if ($null -ne $review) {
                $reviewHalf = Get-HalfScore $review $names (-not $legacy)
                if ($half -eq 'sa') { $reviewerSa = [Math]::Round($reviewHalf.Mean,3) } else { $reviewerSr = [Math]::Round($reviewHalf.Mean,3) }
            }
            foreach ($n in $names) {
                $a = Get-Prop $selfObj $n
                $b = Get-Prop $review $n
                $value = $a
                if ($null -ne $a -and $null -ne $b -and [Math]::Abs([double]$a - [double]$b) -gt 1) {
                    $value = $b
                    $drift.Add([pscustomobject]@{ dimension=$n; self=[double]$a; reviewer=[double]$b }) | Out-Null
                }
                $effective | Add-Member -NotePropertyName $n -NotePropertyValue $value
            }
        }
        $effectiveSaMean = (Get-HalfScore $effectiveSa $SA_NAMES $false).Mean
        $effectiveSrMean = $null
        $originalSr = $null
        $missingAll = @($sa.Missing)
        $total = $effectiveSaMean
        $originalTotal = $sa.Mean
        $effectiveWeight = 1.0
        if ($srApplicable) {
            $effectiveSrMean = (Get-HalfScore $effectiveSr $SR_NAMES $false).Mean
            $originalSr = [Math]::Round($sr.Mean,3)
            $missingAll += @($sr.Missing)
            $effectiveWeight = [double]$SelfWeight
            $total = $SelfWeight * $effectiveSaMean + (1.0 - $SelfWeight) * $effectiveSrMean
            $originalTotal = $SelfWeight * $sa.Mean + (1.0 - $SelfWeight) * $sr.Mean
        }
        $percent = [Math]::Round($total * 20,2)
        $grade = 'D'
        if ($hardFails.Count -gt 0) { $grade = 'F' }
        elseif ($percent -ge 90) { $grade = 'A' }
        elseif ($percent -ge 78) { $grade = 'B' }
        elseif ($percent -ge 66) { $grade = 'C' }
        if ($singleSession -and $grade -ne 'F') { $grade = 'D' }
        $lowDims = New-Object System.Collections.Generic.List[string]
        foreach ($obj in @($effectiveSa,$effectiveSr)) {
            foreach ($p in $obj.PSObject.Properties) { if ($null -ne $p.Value -and [double]$p.Value -le $DropThreshold) { $lowDims.Add($p.Name) | Out-Null } }
        }
        $outputSr = $null
        if ($srApplicable) { $outputSr = [Math]::Round($effectiveSrMean,3) }
        $inputVersion = 2
        if ($legacy) { $inputVersion = 1 }
        $result = [pscustomobject]@{
            mode='score'; executionMode=$executionMode; schemaVersion=$inputVersion; legacyInput=$legacy
            legacyAdmissionBlocked=$legacy; validationScope='structure_only'; evidenceVerified=$false
            artifactType=[string](Get-Prop $payload 'artifact_type'); selfWeight=$SelfWeight; effectiveSelfWeight=$effectiveWeight
            sa=[Math]::Round($effectiveSaMean,3); sr=$outputSr; srApplicable=$srApplicable; srScope=(Get-Prop $payload 'sr_scope')
            total=[Math]::Round($total,3); percent=$percent; grade=$grade; hardFails=$hardFails.ToArray(); gates=$gateState
            originalSa=[Math]::Round($sa.Mean,3); originalSr=$originalSr; originalTotal=[Math]::Round($originalTotal,3)
            originalScores=[pscustomobject]@{sa=$saObj;sr=$srObj}; effectiveScores=[pscustomobject]@{sa=$effectiveSa;sr=$effectiveSr}
            missingDims=$missingAll; lowDims=$lowDims.ToArray(); drift=$drift.ToArray(); driftFlag=($drift.Count -gt 0)
            reviewerSa=$reviewerSa; reviewerSr=$reviewerSr; singleSession=$singleSession
            gateReasons=$reasons; evidenceReferences=$evidence
        }
        if ($Json) { Write-Output ($result | ConvertTo-Json -Depth 10 -Compress) }
        else {
            Write-Output ('grade=' + $grade + ' percent=' + $percent + ' sa=' + $result.sa + ' sr=' + $result.sr + ' total=' + $result.total)
            Write-Output ('executionMode=' + $executionMode + ' legacyInput=' + $legacy + ' hardFails=' + (Join-List $hardFails 'none'))
            Write-Output 'Evidence references checked for structure only; truth and independent execution are not verified.'
            if ($singleSession) { Write-Output 'singleSession=true: no independent review; grade capped at D.' }
            if ($drift.Count -gt 0) { Write-Output 'self_assessment_drift=true: effective scores use reviewer values for differences greater than 1.' }
        }
        if (-not $legacy -and $grade -eq 'F') { exit 1 }
        exit 0
    } catch { Write-InputError $_.Exception.Message; exit 2 }
}
# ---------------------------------------------------------------- ledger mode

if ([string]::IsNullOrWhiteSpace($Ledger)) {
    Write-InputError '-Ledger is required for -Mode ledger'
    exit 2
}
if (-not (Test-Path -LiteralPath $Ledger -PathType Leaf)) {
    Write-InputError ('ledger not found: ' + $Ledger)
    exit 2
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
    # 拼写变体：台账 lens 列是自由文本，实测历史行混用了两种箭头写法。
    # ASCII 箭头 5 行曾全部落进 unknownLabels（17 行里 5 行、2 个标签），把 lensRun / zeroStreak
    # 统计按拼写切碎 ⇒ 僵尸判据读数失真。这两个变体是**规范透镜的同义拼法**，故并入。
    # ⚠️ 只并同义拼法。**不并**活动名（如「溯源复核」）—— 按本文件设计意图「anything unknown is
    #    reported instead of silently merged」，非规范标签必须继续出现在 unknownLensLabels 里当报警；
    #    独立复核（2026-10-03）指出把「溯源复核」并进「溯源」会抹掉这条报警通道，已回退该条。
    '声称<->实存' = '声称↔实存'
    '应有<->实有' = '应有↔实有'
}

$rows = New-Object System.Collections.Generic.List[object]
$parseErrors = 0
$blankLines = 0
try { $ledgerLines = Get-Content -LiteralPath $Ledger -Encoding UTF8 } catch { Write-InputError $_.Exception.Message; exit 2 }
foreach ($line in $ledgerLines) {
    $t = $line.Trim()
    if ($t.Length -eq 0) { $blankLines = $blankLines + 1; continue }
    try {
        if (-not $t.StartsWith('{')) { throw 'ledger row must be an object' }
        $row = $t | ConvertFrom-Json
        if (-not (Test-Object $row)) { throw 'ledger row must be an object' }
        $rows.Add($row) | Out-Null
    } catch {
        $parseErrors = $parseErrors + 1
    }
}
if ($parseErrors -gt 0 -or $rows.Count -eq 0) {
    Write-InputError ('ledger requires nonempty object rows; parseErrors=' + $parseErrors + ' rows=' + $rows.Count)
    exit 2
}
$sourceRows = $rows.Count
if (-not [string]::IsNullOrWhiteSpace($Project)) {
    $filtered = New-Object System.Collections.Generic.List[object]
    foreach ($row in $rows) { if ([string](Get-Prop $row 'project') -ceq $Project) { $filtered.Add($row) | Out-Null } }
    $rows = $filtered
    if ($rows.Count -eq 0) { Write-InputError ('project filter matched no ledger rows: ' + $Project); exit 2 }
}
# The documented class vocabulary is advisory: project-specific historical codes
# remain visible in counts. Missing class is unknown, not a zero-yield result.
$knownClasses = @('module_not_closed','claim_without_artifact','stale_artifact','duplicate_truth_source','broken_reference','numbering_gap','unverified_claim','coverage_gap','scope_overreach','sourcing_reuse_without_search','sourcing_weak_disguised','ritual_report','process_ossification','rule_accretion','self_assessment_as_evidence','vanity_metric','backlog_rot','spec_ambiguity','self_assessment_drift','gate_shift')
$unknownClasses = New-Object System.Collections.Generic.List[string]
$missingClass = New-Object System.Collections.Generic.List[string]
$lensUnknownClass = @{}

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
    $classKnown = (Has-Prop $r 'class') -and ($null -ne (Get-Prop $r 'class'))
    if (-not $classKnown) { $missingClass.Add($batch) | Out-Null }
    if (-not [string]::IsNullOrWhiteSpace($class)) { $hasYield = $true }
    if ($hasYield -and $knownClasses -cnotcontains $class -and -not $unknownClasses.Contains($class)) { $unknownClasses.Add($class) | Out-Null }

    $labels = New-Object System.Collections.Generic.List[string]
    foreach ($part in ($lensRaw -split '[/、,，]')) {
        $p = $part.Trim()
        if ($p.Length -eq 0) { continue }
        if ($lensAlias.ContainsKey($p)) {
            if (-not $labels.Contains($lensAlias[$p])) { $labels.Add($lensAlias[$p]) | Out-Null }
        } else {
            if (-not $labels.Contains($p)) { $labels.Add($p) | Out-Null }
            if (-not $unknownLabels.Contains($p)) { $unknownLabels.Add($p) | Out-Null }
        }
    }
    if ($labels.Count -eq 0) { $labels.Add('(blank)') | Out-Null }

    foreach ($l in $labels) {
        if (-not $lensRuns.ContainsKey($l)) {
            $lensRuns[$l] = 0
            $lensYields[$l] = 0
            $lensStreak[$l] = 0
            $lensUnknownClass[$l] = 0
        }
        $lensRuns[$l] = $lensRuns[$l] + 1
        if ($hasYield) {
            $lensYields[$l] = $lensYields[$l] + 1
            $lensStreak[$l] = 0
        } elseif ($classKnown) {
            $lensStreak[$l] = $lensStreak[$l] + 1
        } else {
            $lensUnknownClass[$l] = $lensUnknownClass[$l] + 1
            $lensStreak[$l] = 0
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
        if (-not (Test-Object $q)) { Write-InputError ('quality must be an object: batch=' + $batch); exit 2 }
        foreach ($key in @('percent','total')) {
            $value = Get-Prop $q $key
            $maxValue = 5
            if ($key -eq 'percent') { $maxValue = 100 }
            if ($null -ne $value -and -not (Test-Number $value 0 $maxValue)) { Write-InputError ('invalid quality.' + $key + ': batch=' + $batch); exit 2 }
        }
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
    $rate = $null
    $evaluatedRuns = $runs - $lensUnknownClass[$k]
    if ($evaluatedRuns -gt 0) { $rate = [Math]::Round((100.0 * $y) / $evaluatedRuns, 1) }
    $lensTable.Add((New-Object psobject -Property @{
                lens          = $k
                runs          = $runs
                yields        = $y
                detectionRate = $rate
                zeroStreak    = $lensStreak[$k]
                lastBatch     = $lensLastBatch[$k]
                unknownClassRows = $lensUnknownClass[$k]
                evaluatedRuns = $evaluatedRuns
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
    sourceRows        = $sourceRows
    project           = $Project
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
    unknownClassCodes = $unknownClasses.ToArray()
    classMissingBatches = $missingClass.ToArray()
    roundsWithoutQuality = $rows.Count - $qualityRows.Count
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
if ($unknownClasses.Count -gt 0) { Write-Output ('unknown class codes (preserved): ' + ($unknownClasses -join ',')) }
if ($missingClass.Count -gt 0) { Write-Output ('class missing (unknown yield): ' + ($missingClass -join ',')) }
exit 0
