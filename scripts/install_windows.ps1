[CmdletBinding()]
param(
    [string]$Archive = (Join-Path $PSScriptRoot 'artifact-selfcheck-3.0.2-skillhub.zip'),
    [string]$ProfileRoot = [Environment]::GetFolderPath('UserProfile'),
    [string]$DesktopPath = [Environment]::GetFolderPath('Desktop'),
    [string]$ExpectedArchiveHash = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Assert-Payload([string]$Root, $Manifest) {
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $expected = @($Manifest.files.PSObject.Properties.Name) + 'release-manifest.json'
    $actual = @(Get-ChildItem -LiteralPath $Root -Recurse -File | ForEach-Object { $_.FullName.Substring($prefix.Length).Replace('\','/') })
    if (@(Compare-Object $expected $actual).Count -ne 0) { throw 'Payload file set differs from manifest' }
    foreach ($item in $Manifest.files.PSObject.Properties) {
        $path = [IO.Path]::GetFullPath((Join-Path $Root $item.Name))
        if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe manifest path' }
        if ((Get-Sha256 $path) -ne $item.Value) { throw ('Hash mismatch: ' + $item.Name) }
    }
}

$tempRoot = $null
$results = @()
$reportPath = $null
try {
    $archivePath = (Resolve-Path -LiteralPath $Archive).Path
    $archiveHash = Get-Sha256 $archivePath
    if ($ExpectedArchiveHash -and $archiveHash -ne $ExpectedArchiveHash.ToLowerInvariant()) { throw 'Archive SHA256 differs from expected value' }
    $profilePath = [IO.Path]::GetFullPath($ProfileRoot).TrimEnd('\')
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('artifact-selfcheck-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $payloadRoot = Join-Path $tempRoot 'payload'
    New-Item -ItemType Directory -Path $payloadRoot | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $seen = @{}
        foreach ($entry in $zip.Entries) {
            $entryName = $entry.FullName.Replace('\','/')
            if ($entryName.EndsWith('/')) { continue }
            if ($entryName -match '(^/|:|(^|/)\.\.(/|$))' -or $seen.ContainsKey($entryName)) { throw 'Unsafe or duplicate archive path' }
            $seen[$entryName] = $true
            $destination = [IO.Path]::GetFullPath((Join-Path $payloadRoot $entryName))
            if (-not $destination.StartsWith($payloadRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive escaped extraction root' }
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
        }
    } finally { $zip.Dispose() }
    $manifest = Get-Content -LiteralPath (Join-Path $payloadRoot 'release-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.name -ne 'artifact-selfcheck' -or $manifest.version -ne '3.0.2' -or $manifest.license -ne 'MIT' -or @($manifest.files.PSObject.Properties).Count -eq 0) { throw 'Unexpected release identity' }
    Assert-Payload $payloadRoot $manifest
    if ((Get-Content -LiteralPath (Join-Path $payloadRoot 'VERSION') -Raw -Encoding UTF8).Trim() -ne '3.0.2') { throw 'VERSION mismatch' }
    $targets = @('.codex', '.workbuddy', '.workbuddy-ai')
    if (Test-Path -LiteralPath (Join-Path $profilePath '.codebuddy-intl\skills\artifact-selfcheck')) { $targets += '.codebuddy-intl' }
    New-Item -ItemType Directory -Path $DesktopPath -Force | Out-Null
    $reportPath = Join-Path $DesktopPath 'artifact-selfcheck-3.0.2-sync.json'
    [pscustomobject]@{ version='3.0.2'; status='running'; timestamp=(Get-Date).ToUniversalTime().ToString('o'); installations=@() } | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding UTF8
    # Inspect every destination before changing any installed copy.
    foreach ($hostName in $targets) {
        foreach ($relative in @($hostName, ($hostName + '\skills'), ($hostName + '\skills\artifact-selfcheck'), 'artifact-selfcheck-backups')) {
            $checkPath = [IO.Path]::GetFullPath((Join-Path $profilePath $relative))
            if (-not $checkPath.StartsWith($profilePath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target outside profile root' }
            if (Test-Path -LiteralPath $checkPath) {
                $existing = Get-Item -LiteralPath $checkPath -Force
                if (-not $existing.PSIsContainer) { throw ('Target is not a directory: ' + $checkPath) }
                if ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw ('Refuse redirected installation path: ' + $checkPath) }
            }
        }
    }
    foreach ($hostName in $targets) {
        $parent = [IO.Path]::GetFullPath((Join-Path $profilePath ($hostName + '\skills')))
        $target = [IO.Path]::GetFullPath((Join-Path $parent 'artifact-selfcheck'))
        if (-not $target.StartsWith($profilePath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target outside profile root' }
        if ((Test-Path -LiteralPath $parent) -and ((Get-Item -LiteralPath $parent).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Refuse redirected skills directory' }
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $staged = Join-Path $parent ('artifact-selfcheck-stage-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $staged | Out-Null
        Get-ChildItem -LiteralPath $payloadRoot -Force | Copy-Item -Destination $staged -Recurse -Force
        Assert-Payload $staged $manifest
        $backup = $null
        if (Test-Path -LiteralPath $target) {
            $backupRoot = Join-Path $profilePath 'artifact-selfcheck-backups'
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            $backup = Join-Path $backupRoot ($hostName.TrimStart('.') + '-' + [Guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath $target -Destination $backup
        }
        try {
            Move-Item -LiteralPath $staged -Destination $target
            Assert-Payload $target $manifest
        } catch {
            if (Test-Path -LiteralPath $target) {
                $failed = Join-Path $parent ('artifact-selfcheck-failed-' + [Guid]::NewGuid().ToString('N'))
                Move-Item -LiteralPath $target -Destination $failed
            }
            if ($backup) { Move-Item -LiteralPath $backup -Destination $target }
            throw
        }
        $results += [pscustomobject]@{ target=$target; version='3.0.2'; verified=$true; backup=$backup }
        Write-Output ('VERIFIED ' + $target)
    }
    New-Item -ItemType Directory -Path $DesktopPath -Force | Out-Null
    $desktopArchive = [IO.Path]::GetFullPath((Join-Path $DesktopPath 'artifact-selfcheck-3.0.2-skillhub.zip'))
    if ($desktopArchive -ne $archivePath) { Copy-Item -LiteralPath $archivePath -Destination $desktopArchive -Force }
    if ((Get-Sha256 $desktopArchive) -ne $archiveHash) { throw 'Desktop archive copy mismatch' }
    $report = [pscustomobject]@{ version='3.0.2'; status='success'; timestamp=(Get-Date).ToUniversalTime().ToString('o'); installations=$results; desktop_archive=$desktopArchive; sha256=$archiveHash; host_loaded='unverified: start a new session' }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Output ('SUCCESS: 3.0.2 verified in each listed directory. Desktop ZIP: ' + $desktopArchive)
    Write-Output 'Start new Codex and WorkBuddy sessions to confirm skill loading.'
} catch {
    $failureMessage = $_.Exception.Message
    if ($reportPath) {
        try {
            [pscustomobject]@{ version='3.0.2'; status='failed'; timestamp=(Get-Date).ToUniversalTime().ToString('o'); error=$failureMessage; installations=$results; requested_hosts=$targets; host_loaded='unverified' } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
        } catch { Write-Warning 'Could not save the failure report.' }
    }
    Write-Error ('INSTALL FAILED: ' + $failureMessage) -ErrorAction Continue
    exit 1
} finally {
    if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
        $resolvedTemp = [IO.Path]::GetFullPath($tempRoot)
        $allowedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if ($resolvedTemp.StartsWith($allowedTemp, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolvedTemp -Leaf) -like 'artifact-selfcheck-*') {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        }
    }
}
