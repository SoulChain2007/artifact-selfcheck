<# Contract regression tests: child-process exit codes and independently expected results. #>
[CmdletBinding()]
param([string]$SkillRoot, [string]$Engine = 'powershell')
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
if ([string]::IsNullOrWhiteSpace($SkillRoot)) { $SkillRoot = Split-Path -Parent $PSScriptRoot }
$scorer = Join-Path $SkillRoot 'scripts/selfcheck_quality.ps1'
$fullFixture = Join-Path $PSScriptRoot 'fixtures/score_v2_full.json'
$temp = Join-Path ([IO.Path]::GetTempPath()) ('selfcheck-v3-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
$script:failed = 0
$script:checked = 0
function Check {
    param([string]$Name, $Expected, $Actual)
    $script:checked++
    if ($Expected -eq $Actual) { Write-Output ('PASS ' + $Name) }
    else { Write-Output ('FAIL ' + $Name + ': expected=' + $Expected + ' actual=' + $Actual); $script:failed++ }
}
function Fresh { return (Get-Content -LiteralPath $fullFixture -Raw -Encoding UTF8 | ConvertFrom-Json) }
function Run-Score {
    param($Payload, [string[]]$Extra = @())
    $file = Join-Path $temp 'score.json'
    [IO.File]::WriteAllText($file, ($Payload | ConvertTo-Json -Depth 20 -Compress), (New-Object Text.UTF8Encoding($false)))
    return (Run-Raw $file $Extra)
}
function Run-Raw {
    param([string]$InputFile, [string[]]$Extra = @())
    # Windows PowerShell's native argument marshaller removes JSON quotes unless
    # escaped for the child process. PowerShell 7 preserves them itself.
    if ($PSVersionTable.PSVersion.Major -lt 6 -and $InputFile.StartsWith('{')) {
        $InputFile = $InputFile.Replace('"','\"')
    }
    $stdout = & $Engine -NoProfile -ExecutionPolicy Bypass -File $scorer -Mode score -Scores $InputFile -Json @Extra
    $exitCode = $LASTEXITCODE
    $value = ($stdout -join "`n") | ConvertFrom-Json
    return [pscustomobject]@{ Code=$exitCode; Value=$value }
}
function Run-Ledger {
    param([string]$Content, [string[]]$Extra = @())
    $file = Join-Path $temp 'ledger.jsonl'
    [IO.File]::WriteAllText($file, $Content, (New-Object Text.UTF8Encoding($false)))
    $stdout = & $Engine -NoProfile -ExecutionPolicy Bypass -File $scorer -Mode ledger -Ledger $file -Json @Extra
    $exitCode = $LASTEXITCODE
    return [pscustomobject]@{ Code=$exitCode; Value=(($stdout -join "`n") | ConvertFrom-Json) }
}
try {
    $r = Run-Score (Fresh)
    Check 'schema2.full.exit' 0 $r.Code
    Check 'schema2.full.grade' A $r.Value.grade
    Check 'structure-only' structure_only $r.Value.validationScope
    Check 'truth-not-proven' $false $r.Value.evidenceVerified
    Check 'schema2.not-legacy' $false $r.Value.legacyInput
    $p = Fresh; $p.mode = 'partial'
    $r = Run-Score $p
    Check 'partial.pass' A $r.Value.grade
    $p = Fresh; $p.mode = 'quick'; $p.g4_kind = 'reverse_check'; $p.gates.g5 = 'na'; $p | Add-Member gate_reasons ([pscustomobject]@{g5='quick review is outside scope'})
    $r = Run-Score $p
    Check 'quick.exit' 0 $r.Code
    Check 'quick.g5-na-no-cap' A $r.Value.grade
    Check 'quick.na-state' na $r.Value.gates.g5
    foreach ($mode in @('quick','partial','full')) {
        $p = Fresh; $p.mode = $mode; $p.external_claims = $false; $p.gates.g3 = 'na'; $p.sr = $null
        $p | Add-Member gate_reasons ([pscustomobject]@{g3='No current external claims'})
        $p | Add-Member sr_scope 'No sourcing assessment is applicable'
        if ($mode -eq 'quick') { $p.g4_kind='reverse_check' }
        $r = Run-Score $p
        Check ($mode + '.no-external.exit') 0 $r.Code
        Check ($mode + '.no-external.grade') A $r.Value.grade
        Check ($mode + '.sr-null') $null $r.Value.sr
        Check ($mode + '.sa-reweighted') 1 $r.Value.effectiveSelfWeight
        Check ($mode + '.sr-inapplicable') $false $r.Value.srApplicable
    }
    foreach ($mode in @('partial','full')) {
        $p=Fresh; $p.mode=$mode; $p.gates.g5='notdone'; $p | Add-Member gate_reasons ([pscustomobject]@{g5='No independent reviewer available'})
        $r=Run-Score $p
        Check ($mode + '.single-session.exit') 0 $r.Code
        Check ($mode + '.single-session.cap') D $r.Value.grade
    }
    foreach ($g in @('g1','g2','g3','g4','g5','g6')) {
        $p=Fresh; $p.gates.$g=$false
        $r=Run-Score $p
        Check ($g + '.false.exit') 1 $r.Code
        Check ($g + '.false.grade') F $r.Value.grade
        Check ($g + '.false.hardfail') $g ($r.Value.hardFails -join ',')
        $p=Fresh; $p.gates.PSObject.Properties.Remove($g)
        $r=Run-Score $p
        Check ($g + '.missing.exit') 2 $r.Code
        $p=Fresh; $p.gates.$g='na'
        $r=Run-Score $p
        Check ($g + '.illegal-na.exit') 2 $r.Code
    }
    foreach ($g in @('g1','g2','g3','g4','g6')) {
        $p=Fresh; $p.evidence.PSObject.Properties.Remove($g)
        $r=Run-Score $p
        Check ($g + '.no-reference.exit') 2 $r.Code
        $p=Fresh; $p.evidence.$g=@('valid.log:1',' ')
        $r=Run-Score $p
        Check ($g + '.invalid-reference-array.exit') 2 $r.Code
    }
    foreach ($key in @('reviewer','review_evidence')) {
        $p=Fresh; $p.PSObject.Properties.Remove($key)
        $r=Run-Score $p
        Check ($key + '.required.exit') 2 $r.Code
    }
    foreach ($state in @('na','notdone')) {
        $p=Fresh; $p.mode='quick'; $p.g4_kind='reverse_check'; $p.gates.g5=$state
        $r=Run-Score $p
        Check ('g5.' + $state + '.needs-reason') 2 $r.Code
    }
    $p=Fresh; $p.external_claims=$false; $p.gates.g3='na'; $p.sr=$null; $p | Add-Member sr_scope 'not applicable'
    $r=Run-Score $p; Check 'g3.na-needs-reason' 2 $r.Code
    $p | Add-Member gate_reasons ([pscustomobject]@{g3='no external claims'}); $p.PSObject.Properties.Remove('sr_scope')
    $r=Run-Score $p; Check 'sr.null-needs-scope' 2 $r.Code
    $p=Fresh; $p.sr=$null
    $r=Run-Score $p; Check 'external.claims-need-sr' 2 $r.Code
    foreach ($bad in @('false',1,$null)) {
        $p=Fresh; $p.external_claims=$bad; $r=Run-Score $p
        Check ('external.reject-' + [string]$bad) 2 $r.Code
    }
    foreach ($key in @('schema_version','mode','external_claims','sa','sr','gates','evidence')) {
        if ($key -eq 'schema_version') { continue }
        $p=Fresh; $p.PSObject.Properties.Remove($key); $r=Run-Score $p
        Check ($key + '.missing-schema2') 2 $r.Code
    }
    foreach ($bad in @('2',1,3,$true)) {
        $p=Fresh; $p.schema_version=$bad; $r=Run-Score $p
        Check ('schema-version.reject-' + [string]$bad) 2 $r.Code
    }
    foreach ($bad in @('FULL','bogus','')) {
        $p=Fresh; $p.mode=$bad; $r=Run-Score $p
        Check ('mode.reject-' + $bad) 2 $r.Code
    }
    foreach ($mode in @('partial','full')) {
        $p=Fresh; $p.mode=$mode; $p.g4_kind='reverse_check'; $r=Run-Score $p
        Check ($mode + '.requires-sensitivity') 2 $r.Code
    }
    $p=Fresh; $p.mode='quick'; $r=Run-Score $p; Check 'quick.requires-reverse' 2 $r.Code
    $p=Fresh; $p.sensitivity_valid=$false; $r=Run-Score $p; Check 'invalid-sensitivity-is-F' F $r.Value.grade; Check 'invalid-sensitivity.exit' 1 $r.Code
    $p=Fresh; $p.sensitivity_valid='true'; $r=Run-Score $p; Check 'sensitivity-bool-required' 2 $r.Code
    $p=Fresh; $p.external_claims=$false; $p.gates.g3=$false; $p | Add-Member gate_reasons ([pscustomobject]@{g3='No external claims, but the actual check failed'})
    $r=Run-Score $p; Check 'inapplicable-scope-never-masks-false' F $r.Value.grade; Check 'inapplicable-false.exit' 1 $r.Code
    $p=Fresh; $p.gates.g1=$false; $p.evidence.PSObject.Properties.Remove('g1'); $r=Run-Score $p
    Check 'required-reference-even-when-failed' 2 $r.Code
    foreach ($half in @('sa','sr')) {
        $key=$half+'1'
        foreach ($bad in @($true,'5',-0.01,5.01,'NaN')) {
            $p=Fresh; $p.$half.$key=$bad; $r=Run-Score $p
            Check ($half + '.reject-' + [string]$bad) 2 $r.Code
        }
        $p=Fresh; $p.$half.PSObject.Properties.Remove($key); $r=Run-Score $p
        Check ($half + '.missing-dimension') 2 $r.Code
    }
    $p=Fresh; $p.sa.sa1=4.5; $p.sr.sr1=0; $r=Run-Score $p
    Check 'fractional-boundary-valid' 0 $r.Code
    Check 'fractional-weighted-percent' 90.83 $r.Value.percent
    foreach ($weight in @('-0.1','1.1','NaN','Infinity','true')) {
        $r=Run-Score (Fresh) @('-SelfWeight',$weight)
        Check ('reject-weight-' + $weight) 2 $r.Code
    }
    $p=Fresh
    foreach ($prop in $p.sr.PSObject.Properties) { $prop.Value=1 }
    $r=Run-Score $p @('-SelfWeight','0'); Check 'weight-zero-uses-sr' 20 $r.Value.percent
    $r=Run-Score $p @('-SelfWeight','1'); Check 'weight-one-uses-sa' 100 $r.Value.percent
    $p=Fresh; $p | Add-Member review_sa ([pscustomobject]@{sa1=1;sa2=4;sa3=5;sa4=5;sa5=5;sa6=5})
    $p | Add-Member review_sr ([pscustomobject]@{sr1=1;sr2=5;sr3=5;sr4=5;sr5=5;sr6=5})
    $r=Run-Score $p
    Check 'reviewer-effective-total' 4.333 $r.Value.total
    Check 'reviewer-effective-percent' 86.67 $r.Value.percent
    Check 'reviewer-effective-grade' B $r.Value.grade
    Check 'original-preserved' 5 $r.Value.originalTotal
    Check 'drift-two-dimensions' 2 @($r.Value.drift).Count
    Check 'difference-exactly-one-retains-self' 5 $r.Value.effectiveScores.sa.sa2
    $p.PSObject.Properties.Remove('schema_version'); $r=Run-Score $p
    Check 'legacy-reviewer-recomputes-total' 4.333 $r.Value.total
    $p | Add-Member schema_version 2
    $p.review_sa.PSObject.Properties.Remove('sa6'); $r=Run-Score $p; Check 'review-score-missing-dimension' 2 $r.Code
    $p.review_sa | Add-Member sa6 5
    $p.review_sa.sa1='1'; $r=Run-Score $p; Check 'review-score-validates' 2 $r.Code
    foreach ($token in @('NaN','Infinity','-Infinity')) {
        $file=Join-Path $temp 'nonfinite.json'
        $raw=(Fresh|ConvertTo-Json -Depth 20 -Compress).Replace('"sa1":5',('"sa1":'+$token))
        [IO.File]::WriteAllText($file,$raw)
        $r=Run-Raw $file; Check ('reject-nonfinite-json-' + $token) 2 $r.Code
    }
    $inline=Fresh|ConvertTo-Json -Depth 20 -Compress
    $r=Run-Raw $inline; Check 'inline-json-supported' 0 $r.Code
    $r=Run-Raw $fullFixture @('-ZeroYieldStreak','NaN'); Check 'invalid-streak-is-input-error' 2 $r.Code
    $r=Run-Raw $fullFixture @('-DropThreshold','Infinity'); Check 'invalid-drop-threshold-is-input-error' 2 $r.Code
    foreach ($raw in @('null','[]','[{}]','true','{bad')) {
        $file=Join-Path $temp 'bad.json'; [IO.File]::WriteAllText($file,$raw)
        $r=Run-Raw $file; Check ('root-reject-' + $raw) 2 $r.Code
    }
    $r=Run-Raw (Join-Path $PSScriptRoot 'fixtures/score_gate_fail.json')
    Check 'legacy-F-successful-calculation' 0 $r.Code
    Check 'legacy-F-kept' F $r.Value.grade
    Check 'legacy-defaults-full' full $r.Value.executionMode
    Check 'legacy-marked' $true $r.Value.legacyInput
    Check 'legacy-not-admission' $true $r.Value.legacyAdmissionBlocked
    $p=Fresh; $p.PSObject.Properties.Remove('schema_version'); $p.gates.g1='true'; $r=Run-Score $p
    Check 'legacy-string-true-is-fail' F $r.Value.grade
    $p.sa.sa1='5'; $r=Run-Score $p; Check 'legacy-reject-number-string' 2 $r.Code
    $old=[pscustomobject]@{batch='b1';date='2026-10-15';lens='内部一致/一致性/内部一致';class='';fixed=$null;verify='python check.py'}
    $line=$old|ConvertTo-Json -Compress
    $r=Run-Ledger $line
    Check 'old-six-key-ledger-accepted' 0 $r.Code
    Check 'ledger-alias-deduplicated' 1 $r.Value.lensTable[0].runs
    Check 'quality-absence-unscored' 0 $r.Value.roundsWithQuality
    Check 'quality-absence-count' 1 $r.Value.roundsWithoutQuality
    Check 'quality-absence-no-zero-trend' 0 @($r.Value.qualityTrend).Count
    foreach ($raw in @('',' ','null','[]','[{}]','true','{bad',($line+"`n{bad"))) {
        $r=Run-Ledger $raw; Check ('ledger-invalid-rejected-' + $raw.Length) 2 $r.Code
    }
    $a=$old|ConvertTo-Json -Compress|ConvertFrom-Json; $a|Add-Member project 'A'
    $b=$old|ConvertTo-Json -Compress|ConvertFrom-Json; $b|Add-Member project 'B'; $b.class='project_specific_defect'
    $r=Run-Ledger (($a|ConvertTo-Json -Compress)+"`n"+($b|ConvertTo-Json -Compress)+"`n"+$line) @('-Project','B')
    Check 'project-source-rows' 3 $r.Value.sourceRows
    Check 'project-selected-only' 1 $r.Value.rows
    Check 'project-unknown-code-retained' project_specific_defect $r.Value.unknownClassCodes[0]
    $r=Run-Ledger (($b|ConvertTo-Json -Compress)+"`n"+($b|ConvertTo-Json -Compress))
    Check 'unknown-code-still-counted' 2 $r.Value.classesRepeated[0].count
    $a.PSObject.Properties.Remove('class')
    $r=Run-Ledger ($a|ConvertTo-Json -Compress)
    Check 'missing-class-reported' b1 $r.Value.classMissingBatches[0]
    Check 'missing-class-not-zero-yield-streak' 0 $r.Value.lensTable[0].zeroStreak
    Check 'missing-class-unknown-count' 1 $r.Value.lensTable[0].unknownClassRows
    Check 'missing-class-rate-is-unknown' $null $r.Value.lensTable[0].detectionRate
    $b|Add-Member quality ([pscustomobject]@{percent='100';total=5;grade='A'})
    $r=Run-Ledger ($b|ConvertTo-Json -Compress); Check 'ledger-invalid-quality-rejected' 2 $r.Code
    $b.quality.percent=100
    $r=Run-Ledger ($b|ConvertTo-Json -Compress); Check 'ledger-scored-row' 1 $r.Value.roundsWithQuality
    $r=Run-Ledger ($b|ConvertTo-Json -Compress) @('-Project','missing'); Check 'empty-filter-input-error' 2 $r.Code
} finally {
    # Only remove this exact, unique temporary test directory.
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($temp))) -eq ([IO.Path]::GetTempPath().TrimEnd('\'))) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
Write-Output ('Assertions=' + $script:checked + ' Failures=' + $script:failed + ' Engine=' + $Engine)
if ($script:failed -gt 0) { exit 1 }
exit 0
