#requires -Version 7.4
#requires -PSEdition Core

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $ExpectedHead,

    [Parameter(Mandatory)]
    [string] $RunnerEnvironment,

    [Parameter(Mandatory)]
    [ValidateSet('Linux', 'Windows')]
    [string] $ExpectedRunnerOs,

    [Parameter(Mandatory)]
    [ValidateSet('git', 'git.exe')]
    [string] $GitCommandName,

    [Parameter(Mandatory)]
    [string] $ExpectedPowerShellExecutable,

    [Parameter(Mandatory)]
    [string] $OutputFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (
    $PSVersionTable.PSEdition -cne 'Core' -or
    $PSVersionTable.PSVersion -lt [version] '7.4'
) {
    throw 'Hosted checkout proof requires PowerShell Core 7.4 or newer.'
}

function Get-BytesSha256 {
    param(
        [Parameter(Mandatory)]
        [byte[]] $Bytes
    )

    [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

$ExpectedPowerShellPath = [IO.Path]::GetFullPath(
    $ExpectedPowerShellExecutable
)
$PowerShellExecutable = [IO.Path]::GetFullPath(
    [Environment]::ProcessPath
)
$PathComparer = if ($ExpectedRunnerOs -ceq 'Windows') {
    [StringComparer]::OrdinalIgnoreCase
}
else {
    [StringComparer]::Ordinal
}
if (-not $PathComparer.Equals(
    $PowerShellExecutable,
    $ExpectedPowerShellPath
)) {
    throw 'The hosted proof did not start in the required absolute PowerShell host.'
}
$PowerShellItem = Get-Item `
    -LiteralPath $PowerShellExecutable `
    -Force `
    -ErrorAction Stop
if (
    $PowerShellItem.PSIsContainer -or
    ($PowerShellItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not $PathComparer.Equals(
        $PowerShellItem.FullName,
        $PowerShellExecutable
    )
) {
    throw 'The PowerShell host must be one real regular file.'
}
$PowerShellBytes = [IO.File]::ReadAllBytes($PowerShellExecutable)
$PowerShellSha256 = Get-BytesSha256 -Bytes $PowerShellBytes

$GitCommand = Get-Command `
    $GitCommandName `
    -CommandType Application `
    -ErrorAction Stop |
    Select-Object -First 1
if ($null -eq $GitCommand) {
    throw 'The hosted runner did not expose the required Git application.'
}
$GitExecutable = [IO.Path]::GetFullPath($GitCommand.Source)
$GitBytes = [IO.File]::ReadAllBytes($GitExecutable)
$GitSha256 = Get-BytesSha256 -Bytes $GitBytes

$GuardPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot 'verify-github-hosted-checkout.ps1')
)
$GuardItem = Get-Item -LiteralPath $GuardPath -Force -ErrorAction Stop
if (
    $GuardItem.PSIsContainer -or
    ($GuardItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not [StringComparer]::OrdinalIgnoreCase.Equals(
        $GuardItem.FullName,
        $GuardPath
    )
) {
    throw 'The exact-head guard source must be one real regular file.'
}
$GuardBytes = [IO.File]::ReadAllBytes($GuardPath)
$GuardSha256 = Get-BytesSha256 -Bytes $GuardBytes
$GuardText = [Text.UTF8Encoding]::new($false, $true).GetString($GuardBytes)
$GuardBlock = [ScriptBlock]::Create($GuardText)

$RepositoryRoot = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
$GuardOutput = @(& $GuardBlock `
    -ExpectedHead $ExpectedHead `
    -VerificationStage Initial `
    -RunnerEnvironment $RunnerEnvironment `
    -ExpectedRunnerOs $ExpectedRunnerOs `
    -GitExecutable $GitExecutable `
    -ExpectedGitSha256 $GitSha256 `
    -RepositoryRoot $RepositoryRoot)
$CheckoutMarker = @(
    $GuardOutput |
        Where-Object {
            $_ -ceq (
                'GITHUB_HOSTED_CHECKOUT=verified:' +
                $ExpectedRunnerOs.ToLowerInvariant() +
                ':initial'
            )
        }
)
$ManifestMarker = @(
    $GuardOutput |
        Where-Object {
            $_ -cmatch '^GITHUB_HOSTED_TRACKED_MANIFEST_SHA256=[0-9a-f]{64}$'
        }
)
$IndexMarker = @(
    $GuardOutput |
        Where-Object {
            $_ -cmatch '^GITHUB_HOSTED_GIT_INDEX_SHA256=[0-9a-f]{64}$'
        }
)
if (
    $GuardOutput.Count -ne 3 -or
    $CheckoutMarker.Count -ne 1 -or
    $ManifestMarker.Count -ne 1 -or
    $IndexMarker.Count -ne 1
) {
    throw 'The initial exact-head guard returned an invalid proof shape.'
}
$TrackedManifestSha256 = $ManifestMarker[0].Substring(
    'GITHUB_HOSTED_TRACKED_MANIFEST_SHA256='.Length
)
$GitIndexSha256 = $IndexMarker[0].Substring(
    'GITHUB_HOSTED_GIT_INDEX_SHA256='.Length
)
Write-Output $CheckoutMarker[0]

if (-not [IO.Path]::IsPathRooted($OutputFile)) {
    throw 'The hosted proof output file must be an absolute path.'
}
$OutputLines = @(
    "git_executable_base64=$(
        [Convert]::ToBase64String(
            [Text.UTF8Encoding]::new($false).GetBytes($GitExecutable)
        )
    )"
    "git_sha256=$GitSha256"
    "guard_sha256=$GuardSha256"
    "guard_source_base64=$([Convert]::ToBase64String($GuardBytes))"
    "powershell_executable_base64=$(
        [Convert]::ToBase64String(
            [Text.UTF8Encoding]::new($false).GetBytes(
                $PowerShellExecutable
            )
        )
    )"
    "powershell_sha256=$PowerShellSha256"
    "repository_root_base64=$(
        [Convert]::ToBase64String(
            [Text.UTF8Encoding]::new($false).GetBytes($RepositoryRoot)
        )
    )"
    "tracked_manifest_sha256=$TrackedManifestSha256"
    "git_index_sha256=$GitIndexSha256"
)
$OutputLines | Out-File `
    -LiteralPath $OutputFile `
    -Encoding utf8 `
    -Append
