#requires -Version 7.4
#requires -PSEdition Core

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$CheckedHead,

    [Parameter(Mandatory = $true)]
    [string]$ModelsDirectory,

    [Parameter(Mandatory = $true)]
    [string]$AudioFixture,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$AudioFixtureSha256,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceDirectory,

    [ValidatePattern('^[A-Za-z0-9()@._ +\-]{3,128}$')]
    [string]$ExpectedProcessorToken,

    [ValidateRange(0, 256)]
    [int]$ExpectedLogicalProcessors = 0,

    [ValidateRange(2, 32)]
    [int]$SessionCycles = 12,

    [ValidateRange(1, 32)]
    [int]$AudioRepeat = 1,

    [ValidateRange(300, 3600)]
    [int]$NativeTimeoutSeconds = 1200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ExistingRealPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Container', 'Leaf')]
        [string]$PathType,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Path).Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType $PathType)) {
        throw "$Label must be an existing $PathType path."
    }
    $item = Get-Item -LiteralPath $resolved -Force
    $current = $item
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label must not use a link or reparse redirect in its directory chain."
        }
        $current = if ($current -is [IO.FileInfo]) {
            $current.Directory
        }
        else {
            $current.Parent
        }
    }
    return $resolved
}

function Assert-PathOutsideRepository {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,

        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot
    )

    $separator = [IO.Path]::DirectorySeparatorChar
    $repoPrefix = $RepositoryRoot.TrimEnd($separator) + $separator
    if (
        $Candidate.Equals($RepositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $Candidate.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw 'Private target-client evidence must stay outside the repository.'
    }
}

function Set-PrivateDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $identity) {
        throw 'The current Windows security identity is unavailable.'
    }
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $rights = [Security.AccessControl.FileSystemRights]::FullControl
    $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity,
        $rights,
        $inheritance,
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Get-ProcessorName {
    $key = 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0'
    $name = (Get-ItemProperty -LiteralPath $key -Name ProcessorNameString).ProcessorNameString
    if ([string]::IsNullOrWhiteSpace($name)) {
        throw 'The Windows processor identity is unavailable.'
    }
    return $name.Trim()
}

if (-not $IsWindows) {
    throw 'The target-client resource gate runs only on Windows.'
}

$processorName = Get-ProcessorName
$processorConstraint = if ([string]::IsNullOrWhiteSpace($ExpectedProcessorToken)) {
    $null
}
else {
    $ExpectedProcessorToken.Trim()
}
if (
    $null -ne $processorConstraint -and
    $processorName.IndexOf($processorConstraint, [StringComparison]::OrdinalIgnoreCase) -lt 0
) {
    throw "This machine does not satisfy the requested processor constraint '$processorConstraint'; observed '$processorName'."
}
$logicalProcessors = [Environment]::ProcessorCount
$logicalProcessorBudget = if ($ExpectedLogicalProcessors -eq 0) {
    $logicalProcessors
}
else {
    $ExpectedLogicalProcessors
}
if ($logicalProcessors -ne $logicalProcessorBudget) {
    throw "The host must expose exactly $logicalProcessorBudget logical processors; observed $logicalProcessors."
}

$repositoryRoot = [IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
)
$actualHead = (& git -C $repositoryRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualHead -ne $CheckedHead) {
    throw 'CheckedHead does not match the checked-out repository HEAD.'
}
$gitStatus = (& git -C $repositoryRoot status --porcelain=v1 --untracked-files=normal) -join "`n"
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace($gitStatus)) {
    throw 'The target-client resource gate requires a clean checked head.'
}

$models = Resolve-ExistingRealPath -Path $ModelsDirectory -PathType Container -Label 'ModelsDirectory'
$fixture = Resolve-ExistingRealPath -Path $AudioFixture -PathType Leaf -Label 'AudioFixture'
$fixtureDigest = (Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash.ToLowerInvariant()
if ($fixtureDigest -ne $AudioFixtureSha256) {
    throw 'AudioFixture does not match AudioFixtureSha256.'
}

$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
Assert-PathOutsideRepository -Candidate $evidence -RepositoryRoot $repositoryRoot
if (Test-Path -LiteralPath $evidence) {
    throw 'EvidenceDirectory must be a new path.'
}
$evidenceParent = Resolve-ExistingRealPath -Path (Split-Path -Parent $evidence) -PathType Container -Label 'EvidenceDirectory parent'
Assert-PathOutsideRepository -Candidate $evidenceParent -RepositoryRoot $repositoryRoot

New-Item -ItemType Directory -Path $evidence -ErrorAction Stop | Out-Null
Set-PrivateDirectoryAcl -Path $evidence

$contextPath = Join-Path $evidence 'resource-gate-context.json'
$profilePath = Join-Path $evidence 'resident-language-routing-profile.json'
$logPath = Join-Path $evidence 'native-resource-gate.log'
$context = [ordered]@{
    schemaVersion = 4
    status = 'started'
    checkedHead = $CheckedHead
    processorName = $processorName
    processorConstraint = $processorConstraint
    logicalProcessors = $logicalProcessors
    logicalProcessorBudget = $logicalProcessorBudget
    sessionCycles = $SessionCycles
    nativeTimeoutSeconds = $NativeTimeoutSeconds
    audioFixtureSha256 = $AudioFixtureSha256
    modelsDirectoryRecorded = $false
    audioFixturePathRecorded = $false
    boundary = 'desktop-prepared-audio-frame-to-final-resource-profile'
    networkBoundary = 'direct-local-runtime-with-no-server-client'
    exclusions = @(
        'physical-microphone'
        'rendered-ui'
        'server-transport'
        'energy'
        'thermal'
    )
}
$context | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $contextPath -Encoding utf8NoBOM

$savedEnvironment = @{}
$environment = [ordered]@{
    YAP_MODELS_DIR = $models
    YAP_TEST_LOCAL_ROUTING_AUDIO = $fixture
    YAP_TEST_LOCAL_ROUTING_AUDIO_SHA256 = $AudioFixtureSha256
    YAP_TEST_LOCAL_ROUTING_AUDIO_REPEAT = [string]$AudioRepeat
    YAP_TEST_LOCAL_ASR_THREADS = '2'
    YAP_TEST_LOCAL_ROUTING_SESSION_CYCLES = [string]$SessionCycles
    YAP_TEST_LOCAL_ROUTING_EVIDENCE = $profilePath
}
foreach ($entry in $environment.GetEnumerator()) {
    $savedEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
}

try {
    $nativeWorkingDirectory = Join-Path $repositoryRoot 'desktop\src-tauri'
    $nativeStandardOutput = Join-Path $evidence '.native-resource.stdout.tmp'
    $nativeStandardError = Join-Path $evidence '.native-resource.stderr.tmp'
    $cargo = Get-Command cargo -CommandType Application -ErrorAction Stop
    $nativeProcess = $null
    $nativeTimedOut = $false
    try {
        $nativeProcess = Start-Process `
            -FilePath $cargo.Source `
            -ArgumentList @(
                'test',
                '--release',
                'resident_language_routing_profiles_nemotron_interference_and_teardown',
                '--',
                '--ignored',
                '--nocapture'
            ) `
            -WorkingDirectory $nativeWorkingDirectory `
            -RedirectStandardOutput $nativeStandardOutput `
            -RedirectStandardError $nativeStandardError `
            -NoNewWindow `
            -PassThru
        if (-not $nativeProcess.WaitForExit($NativeTimeoutSeconds * 1000)) {
            $nativeTimedOut = $true
            $nativeProcess.Kill($true)
            $nativeProcess.WaitForExit()
        }
        $nativeExitCode = $nativeProcess.ExitCode
        $nativeOutput = @(
            if (Test-Path -LiteralPath $nativeStandardOutput) {
                Get-Content -LiteralPath $nativeStandardOutput
            }
            if (Test-Path -LiteralPath $nativeStandardError) {
                Get-Content -LiteralPath $nativeStandardError
            }
        )
        $nativeOutput | Set-Content -LiteralPath $logPath -Encoding utf8NoBOM
        if ($nativeTimedOut) {
            throw "The native target-client resource collector exceeded its $NativeTimeoutSeconds-second wall-clock limit."
        }
        if ($nativeExitCode -ne 0) {
            throw "The native target-client resource collector failed with exit code $nativeExitCode."
        }
    }
    finally {
        if ($nativeProcess -and -not $nativeProcess.HasExited) {
            $nativeProcess.Kill($true)
            $nativeProcess.WaitForExit()
        }
        Remove-Item -LiteralPath $nativeStandardOutput, $nativeStandardError -Force -ErrorAction SilentlyContinue
    }
}
finally {
    foreach ($entry in $savedEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}

if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
    throw 'The native resource collector did not publish its aggregate profile.'
}
$profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
if (
    $profile.schemaVersion -ne 5 -or
    $profile.audioFixtureSha256 -ne $AudioFixtureSha256 -or
    $profile.logicalProcessorBudget -ne $logicalProcessorBudget -or
    $profile.localAsrThreads -ne 2 -or
    $profile.sustained.requestedCycles -ne $SessionCycles -or
    $profile.sustained.completedCycles -ne $SessionCycles -or
    -not $profile.combinedRealTimeGatePassed -or
    -not $profile.paced.pacedGatePassed -or
    -not $profile.sustained.sustainedGatePassed
) {
    throw 'The native resource profile did not satisfy the frozen target-client contract.'
}

$context.status = 'passed'
$context.profileSha256 = (Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash.ToLowerInvariant()
$context.logSha256 = (Get-FileHash -LiteralPath $logPath -Algorithm SHA256).Hash.ToLowerInvariant()
$context | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $contextPath -Encoding utf8NoBOM

Write-Output 'TARGET_CLIENT_NATIVE_RESOURCE_GATE=PASS'
Write-Output "CHECKED_HEAD=$CheckedHead"
Write-Output "SESSION_CYCLES=$SessionCycles"
Write-Output 'PHYSICAL_MICROPHONE_RENDERED_UI_ENERGY_THERMAL=NOT_CLAIMED'
