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
    [string]$SkillRoot,
    [string]$Engine = 'powershell'
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
    $json = & $Engine -NoProfile -ExecutionPolicy Bypass -File $script -Mode score -Scores $Path -Json
    Assert-Equal ((Split-Path -Leaf $Path) + '.exit') 0 $LASTEXITCODE | Out-Host
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

# quality.md 第二节 G5 单会话例外：g5 标 "notdone" ⇒ 不判 F，但评级上限 D。
# 回归：这条曾经缺失 —— 单会话环境（本项目常态）每轮都被机械判 F。
$ss = Invoke-Score (Join-Path $fixtures 'score_single_session.json')
Assert-Equal 'single-session.grade' 'D' $ss.grade
Assert-Equal 'single-session.percent' 100 $ss.percent
Assert-Equal 'single-session.hardFails' 'none' (Get-ListText $ss.hardFails 'none')
Assert-Equal 'single-session.g5state' 'notdone' $ss.gates.g5
Assert-Equal 'single-session.flag' $true $ss.singleSession

Write-Output '--- ledger mode ---'
$ledgerPath = Join-Path $fixtures 'ledger_sample.jsonl'
$ledgerJson = & $Engine -NoProfile -ExecutionPolicy Bypass -File $script -Mode ledger -Ledger $ledgerPath -Json
Assert-Equal 'legacy-ledger.exit' 0 $LASTEXITCODE
$lg = $ledgerJson | ConvertFrom-Json
Assert-Equal 'ledger.rows' 5 $lg.rows
Assert-Equal 'ledger.parseErrors' 0 $lg.parseErrors
$expected = $lg.lensTable | Where-Object { $_.lens -eq '应有↔实有' }
Assert-Equal 'ledger.应有↔实有.runs' 2 $expected.runs
Assert-Equal 'ledger.应有↔实有.yields' 1 $expected.yields
Assert-Equal 'ledger.应有↔实有.zeroStreak' 1 $expected.zeroStreak
$alias = $lg.lensTable | Where-Object { $_.lens -eq '内部一致' }
Assert-Equal 'ledger.alias-一致性->内部一致.runs' 1 $alias.runs
# 拼写变体归并回归：ASCII 箭头（'声称<->实存'）是规范透镜的同义拼法，必须并进 '声称↔实存'，
# 否则会落进 unknownLensLabels 并把 lensRun 切碎。
$ascii = $lg.lensTable | Where-Object { $_.lens -eq '声称↔实存' }
Assert-Equal 'ledger.alias-ASCII箭头->声称↔实存.runs' 1 $ascii.runs
# 反例回归：活动名「溯源复核」**不是**规范透镜，按设计意图必须继续被上报，
# ⛔ 不许静默并进任何桶（独立复核 2026-10-03 指出合并它会抹掉报警通道）。
Assert-Equal 'ledger.unknownLensLabels-保留非规范标签' '溯源复核' (Get-ListText $lg.unknownLensLabels 'none')
Assert-Equal 'ledger.classesRepeated' 'none' (Get-ListText $lg.classesRepeated 'none')

Write-Output '--- schema 2 contract regression ---'
& $Engine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test_quality_v3.ps1') -SkillRoot $SkillRoot -Engine $Engine
Assert-Equal 'v3-contract-suite.exit' 0 $LASTEXITCODE
Write-Output ''
if ($failures -eq 0) {
    Write-Output 'ALL TESTS PASSED'
} else {
    Write-Output ('TESTS FAILED: ' + $failures)
}
exit $failures
