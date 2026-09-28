<#
.SYNOPSIS
  Reproducible smoke tests for scripts/selfcheck_quality.ps1.
.DESCRIPTION
  Runs the scorer and the ledger statistician against fixtures under tests/fixtures and
  asserts the readings that references/quality.md and references/learning.md promise.
  Windows PowerShell 5.1 safe (no "if" used as an expression).
.NOTES
  Exit code = number of failed assertions (0 = all green).
#>
[CmdletBinding()]
param(
    [string]$SkillRoot
)

$ErrorActionPreference = 'Stop'
# 强制 UTF-8 控制台代码页：嵌套子进程的 stdout 由父进程按 [Console]::OutputEncoding 解码，
# GBK 控制台下台账透镜名里的「↔」（U+2194）会被码页吞成「?」导致断言拿到空值（2.3.0 修 F08）。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
if ([string]::IsNullOrWhiteSpace($SkillRoot)) { $SkillRoot = Split-Path -Parent $PSScriptRoot }
$script = Join-Path (Join-Path $SkillRoot 'scripts') 'selfcheck_quality.ps1'
$fixtures = Join-Path $PSScriptRoot 'fixtures'

if (-not (Test-Path -LiteralPath $script)) {
    Write-Output ('FAIL: script not found: ' + $script)
    exit 1
}

$failures = 0
function Assert-Equal {
    param([string]$Name, $Expected, $Actual)
    $ok = $false
    if ($Expected -eq $Actual) { $ok = $true }
    if ($ok) {
        Write-Output ('PASS ' + $Name + ' = ' + $Actual)
    } else {
        Write-Output ('FAIL ' + $Name + ' expected <' + $Expected + '> actual <' + $Actual + '>')
        $script:failures = $script:failures + 1
    }
}

function Invoke-Score {
    param([string]$Path)
    $json = & powershell -NoProfile -ExecutionPolicy Bypass -File $script -Mode score -Scores $Path -Json
    return ($json | ConvertFrom-Json)
}

function Get-ListText {
    param($Items, [string]$WhenEmpty)
    if ($null -eq $Items) { return $WhenEmpty }
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($i in $Items) { $parts.Add([string]$i) | Out-Null }
    if ($parts.Count -eq 0) { return $WhenEmpty }
    return ($parts -join ',')
}

Write-Output '--- score mode ---'
$pass = Invoke-Score (Join-Path $fixtures 'score_all_pass.json')
Assert-Equal 'all-pass.grade' 'A' $pass.grade
Assert-Equal 'all-pass.percent' 100 $pass.percent
Assert-Equal 'all-pass.hardFails' 'none' (Get-ListText $pass.hardFails 'none')
Assert-Equal 'all-pass.driftFlag' $false $pass.driftFlag

$fail = Invoke-Score (Join-Path $fixtures 'score_gate_fail.json')
Assert-Equal 'gate-fail.grade' 'F' $fail.grade
Assert-Equal 'gate-fail.hardFails' 'g4' (Get-ListText $fail.hardFails 'none')

Write-Output '--- ledger mode ---'
$ledgerPath = Join-Path $fixtures 'ledger_sample.jsonl'
$ledgerJson = & powershell -NoProfile -ExecutionPolicy Bypass -File $script -Mode ledger -Ledger $ledgerPath -Json
$lg = $ledgerJson | ConvertFrom-Json
Assert-Equal 'ledger.rows' 3 $lg.rows
Assert-Equal 'ledger.parseErrors' 0 $lg.parseErrors
$expected = $lg.lensTable | Where-Object { $_.lens -eq '应有↔实有' }
Assert-Equal 'ledger.应有↔实有.runs' 2 $expected.runs
Assert-Equal 'ledger.应有↔实有.yields' 1 $expected.yields
Assert-Equal 'ledger.应有↔实有.zeroStreak' 1 $expected.zeroStreak
$alias = $lg.lensTable | Where-Object { $_.lens -eq '内部一致' }
Assert-Equal 'ledger.alias-一致性->内部一致.runs' 1 $alias.runs
Assert-Equal 'ledger.classesRepeated' 'none' (Get-ListText $lg.classesRepeated 'none')
Assert-Equal 'ledger.unknownLensLabels' 'none' (Get-ListText $lg.unknownLensLabels 'none')

Write-Output ''
if ($failures -eq 0) {
    Write-Output 'ALL TESTS PASSED'
} else {
    Write-Output ('TESTS FAILED: ' + $failures)
}
exit $failures
