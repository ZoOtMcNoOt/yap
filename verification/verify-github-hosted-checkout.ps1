#requires -Version 7.4
#requires -PSEdition Core

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $ExpectedHead,

    [Parameter(Mandatory)]
    [ValidateSet('Initial', 'Final')]
    [string] $VerificationStage,

    [Parameter(Mandatory)]
    [string] $RunnerEnvironment,

    [Parameter(Mandatory)]
    [ValidateSet('Linux', 'Windows')]
    [string] $ExpectedRunnerOs,

    [Parameter(Mandatory)]
    [string] $GitExecutable,

    [Parameter(Mandatory)]
    [string] $ExpectedGitSha256,

    [Parameter(Mandatory)]
    [string] $RepositoryRoot,

    [string] $ExpectedTrackedManifestSha256 = '',

    [string] $ExpectedGitIndexSha256 = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (
    $PSVersionTable.PSEdition -cne 'Core' -or
    $PSVersionTable.PSVersion -lt [version] '7.4'
) {
    throw 'Exact-head verification requires PowerShell Core 7.4 or newer.'
}

if (
    $env:GITHUB_ACTIONS -cne 'true' -or
    $env:RUNNER_OS -cne $ExpectedRunnerOs -or
    $RunnerEnvironment -cne 'github-hosted'
) {
    throw "Exact-head verification requires a fresh GitHub-hosted $ExpectedRunnerOs runner."
}
if ($ExpectedHead -cnotmatch '^[0-9a-f]{40}$') {
    throw 'The expected checkout head must be one lowercase Git SHA.'
}
if (-not [IO.Path]::IsPathRooted($GitExecutable)) {
    throw 'The Git executable must be an absolute path.'
}
if ($ExpectedGitSha256 -cnotmatch '^[0-9a-f]{64}$') {
    throw 'The expected Git executable identity must be one lowercase SHA-256.'
}
if (-not [IO.Path]::IsPathRooted($RepositoryRoot)) {
    throw 'The repository root must be an absolute path.'
}
if ($VerificationStage -ceq 'Final') {
    if ($ExpectedTrackedManifestSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'The expected tracked-content manifest must be one lowercase SHA-256.'
    }
    if ($ExpectedGitIndexSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'The expected Git index identity must be one lowercase SHA-256.'
    }
}
elseif (
    $ExpectedTrackedManifestSha256.Length -ne 0 -or
    $ExpectedGitIndexSha256.Length -ne 0
) {
    throw 'Initial verification must create, not consume, tracked-state identities.'
}

$PathComparer = if ($ExpectedRunnerOs -ceq 'Windows') {
    [StringComparer]::OrdinalIgnoreCase
}
else {
    [StringComparer]::Ordinal
}
$VerifiedTrackedAncestors = [Collections.Generic.HashSet[string]]::new(
    $PathComparer
)
$ResolvedRepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$RepositoryItem = Get-Item `
    -LiteralPath $ResolvedRepositoryRoot `
    -Force `
    -ErrorAction Stop
if (
    -not $RepositoryItem.PSIsContainer -or
    ($RepositoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not $PathComparer.Equals(
        $RepositoryItem.FullName,
        $ResolvedRepositoryRoot
    )
) {
    throw 'The repository root must be one real directory.'
}
$ResolvedGit = [IO.Path]::GetFullPath($GitExecutable)
$GitItem = Get-Item -LiteralPath $ResolvedGit -Force -ErrorAction Stop
if (
    $GitItem.PSIsContainer -or
    ($GitItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not $PathComparer.Equals(
        $GitItem.FullName,
        $ResolvedGit
    )
) {
    throw 'The Git executable must be one real regular file.'
}

function Get-VerifiedFileSha256 {
    param(
        [Parameter(Mandatory)]
        [string] $LiteralPath
    )

    $Bytes = [IO.File]::ReadAllBytes($LiteralPath)
    [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData($Bytes)
    ).ToLowerInvariant()
}

function Clear-GitOverrideEnvironment {
    $ExactNames = @(
        'GIT_ALTERNATE_OBJECT_DIRECTORIES',
        'GIT_ATTR_NOSYSTEM',
        'GIT_CEILING_DIRECTORIES',
        'GIT_COMMON_DIR',
        'GIT_CONFIG',
        'GIT_CONFIG_GLOBAL',
        'GIT_CONFIG_NOSYSTEM',
        'GIT_CONFIG_PARAMETERS',
        'GIT_CONFIG_SYSTEM',
        'GIT_DIR',
        'GIT_DISCOVERY_ACROSS_FILESYSTEM',
        'GIT_EXEC_PATH',
        'GIT_EXTERNAL_DIFF',
        'GIT_GLOB_PATHSPECS',
        'GIT_ICASE_PATHSPECS',
        'GIT_INDEX_FILE',
        'GIT_LITERAL_PATHSPECS',
        'GIT_NOGLOB_PATHSPECS',
        'GIT_OBJECT_DIRECTORY',
        'GIT_PREFIX',
        'GIT_REPLACE_REF_BASE',
        'GIT_WORK_TREE'
    )
    foreach ($Name in $ExactNames) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }
    foreach ($Variable in @(Get-ChildItem Env:)) {
        if ($Variable.Name -cmatch '^GIT_CONFIG_(?:COUNT|KEY_[0-9]+|VALUE_[0-9]+)$') {
            Remove-Item "Env:$($Variable.Name)" -ErrorAction SilentlyContinue
        }
    }
    $env:GIT_NO_REPLACE_OBJECTS = '1'
    $env:GIT_OPTIONAL_LOCKS = '0'
}

function Invoke-VerifiedGit {
    param(
        [Parameter(Mandatory)]
        [string[]] $Arguments
    )

    if ((Get-VerifiedFileSha256 -LiteralPath $ResolvedGit) -cne $ExpectedGitSha256) {
        throw 'The selected Git executable changed after exact-head admission.'
    }
    $FixedArguments = @(
        '-c',
        'core.fsmonitor=false',
        '-c',
        'core.ignoreStat=false',
        '-c',
        'core.untrackedCache=false'
    )
    if ($ExpectedRunnerOs -ceq 'Linux') {
        $FixedArguments += @('-c', 'core.fileMode=true')
    }
    $FixedArguments += @('-C', $ResolvedRepositoryRoot)
    $Output = @(& $ResolvedGit @FixedArguments @Arguments 2>&1)
    $ExitCode = $LASTEXITCODE
    [pscustomobject]@{
        ExitCode = $ExitCode
        Output   = @($Output)
    }
}

function Get-OneGitOutput {
    param(
        [Parameter(Mandatory)]
        [string[]] $Arguments,

        [Parameter(Mandatory)]
        [string] $FailureMessage
    )

    $Result = Invoke-VerifiedGit -Arguments $Arguments
    $NormalizedOutput = @($Result.Output)
    if ($Result.ExitCode -ne 0 -or $NormalizedOutput.Count -ne 1) {
        throw $FailureMessage
    }
    [string] $NormalizedOutput[0]
}

function Assert-RealTrackedAncestors {
    param(
        [Parameter(Mandatory)]
        [string] $LiteralPath
    )

    $Current = [IO.Directory]::GetParent($LiteralPath)
    while (
        $null -ne $Current -and
        -not $PathComparer.Equals(
            $Current.FullName,
            $ResolvedRepositoryRoot
        )
    ) {
        if (-not $VerifiedTrackedAncestors.Add($Current.FullName)) {
            return
        }
        $Item = Get-Item `
            -LiteralPath $Current.FullName `
            -Force `
            -ErrorAction Stop
        if (
            -not $Item.PSIsContainer -or
            ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not $PathComparer.Equals($Item.FullName, $Current.FullName)
        ) {
            throw 'A reviewed tracked ancestor is not one real directory.'
        }
        $Current = $Current.Parent
    }
    if (
        $null -eq $Current -or
        -not $PathComparer.Equals(
            $Current.FullName,
            $ResolvedRepositoryRoot
        )
    ) {
        throw 'A reviewed tracked ancestor escaped the repository root.'
    }
}

function Get-TrackedContentManifestSha256 {
    $TreeOutput = Get-OneGitOutput `
        -Arguments @(
            'ls-tree',
            '-r',
            '-z',
            '--full-tree',
            $ExpectedHead
        ) `
        -FailureMessage 'Git could not enumerate the reviewed tracked tree.'
    $TreeEntries = @(
        $TreeOutput.Split(
            [char] 0,
            [StringSplitOptions]::RemoveEmptyEntries
        )
    )
    if ($TreeEntries.Count -eq 0) {
        throw 'The reviewed tracked tree is unexpectedly empty.'
    }

    $Utf8 = [Text.UTF8Encoding]::new($false, $true)
    $Manifest = [Security.Cryptography.IncrementalHash]::CreateHash(
        [Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        foreach ($Entry in $TreeEntries) {
            if (
                $Entry -cnotmatch (
                    '^(?<mode>[0-9]{6}) blob ' +
                    '[0-9a-f]{40}(?:[0-9a-f]{24})?' +
                    "`t(?<path>.+)$"
                )
            ) {
                throw 'The reviewed tree contains an unsupported tracked entry.'
            }
            $Mode = $Matches.mode
            $TrackedPath = $Matches.path
            if (
                $TrackedPath.IndexOf([char] 0) -ge 0 -or
                $TrackedPath.IndexOf("`r") -ge 0 -or
                $TrackedPath.IndexOf("`n") -ge 0
            ) {
                throw 'The reviewed tree contains an unsupported control-character path.'
            }
            $FullPath = [IO.Path]::GetFullPath(
                (Join-Path $ResolvedRepositoryRoot $TrackedPath)
            )
            $RelativePath = [IO.Path]::GetRelativePath(
                $ResolvedRepositoryRoot,
                $FullPath
            )
            if (
                [IO.Path]::IsPathRooted($RelativePath) -or
                $RelativePath -ceq '..' -or
                $RelativePath.StartsWith(
                    "..$([IO.Path]::DirectorySeparatorChar)",
                    [StringComparison]::Ordinal
                )
            ) {
                throw 'A reviewed tracked path escaped the repository root.'
            }

            Assert-RealTrackedAncestors -LiteralPath $FullPath
            $Item = Get-Item -LiteralPath $FullPath -Force -ErrorAction Stop
            if ($Item.PSIsContainer) {
                throw 'A reviewed tracked path became a directory.'
            }
            $IsReparsePoint = (
                $Item.Attributes -band [IO.FileAttributes]::ReparsePoint
            ) -ne 0
            if ($IsReparsePoint -and $Mode -cne '120000') {
                throw 'A regular reviewed tracked file became a reparse point.'
            }

            if ($IsReparsePoint) {
                if ([string]::IsNullOrEmpty($Item.LinkTarget)) {
                    throw 'A reviewed tracked symbolic link has no link target.'
                }
                $Kind = 'symlink'
                $ContentBytes = $Utf8.GetBytes($Item.LinkTarget)
                $ContentLength = $ContentBytes.LongLength
                $ContentSha256 = [Convert]::ToHexString(
                    [Security.Cryptography.SHA256]::HashData($ContentBytes)
                ).ToLowerInvariant()
            }
            else {
                $Kind = 'file'
                $Stream = [IO.File]::Open(
                    $FullPath,
                    [IO.FileMode]::Open,
                    [IO.FileAccess]::Read,
                    [IO.FileShare]::Read
                )
                try {
                    $ContentLength = $Stream.Length
                    $ContentSha256 = [Convert]::ToHexString(
                        [Security.Cryptography.SHA256]::HashData($Stream)
                    ).ToLowerInvariant()
                }
                finally {
                    $Stream.Dispose()
                }
            }

            $Record = (
                "$Mode`0$TrackedPath`0$Kind`0" +
                "$ContentLength`0$ContentSha256`n"
            )
            $Manifest.AppendData($Utf8.GetBytes($Record))
        }
        [Convert]::ToHexString(
            $Manifest.GetHashAndReset()
        ).ToLowerInvariant()
    }
    finally {
        $Manifest.Dispose()
    }
}

function Assert-CanonicalGitIndexFlags {
    $IndexOutput = Get-OneGitOutput `
        -Arguments @('ls-files', '-v', '-z') `
        -FailureMessage 'Git could not inspect the reviewed index flags.'
    $IndexEntries = @(
        $IndexOutput.Split(
            [char] 0,
            [StringSplitOptions]::RemoveEmptyEntries
        )
    )
    if ($IndexEntries.Count -eq 0) {
        throw 'The reviewed Git index is unexpectedly empty.'
    }
    foreach ($Entry in $IndexEntries) {
        if ($Entry.Length -lt 3 -or $Entry[0] -cne 'H' -or $Entry[1] -cne ' ') {
            throw 'The Git index contains hidden or noncanonical tracked state.'
        }
    }
}

Clear-GitOverrideEnvironment

$TopLevel = Get-OneGitOutput `
    -Arguments @('rev-parse', '--show-toplevel') `
    -FailureMessage 'Git could not resolve the disposable checkout root.'
$ResolvedTopLevel = [IO.Path]::GetFullPath($TopLevel.Trim())
if (-not $PathComparer.Equals(
    $ResolvedTopLevel,
    $ResolvedRepositoryRoot
)) {
    throw 'Git resolved a different disposable checkout root.'
}
$GitDirectory = Get-OneGitOutput `
    -Arguments @('rev-parse', '--path-format=absolute', '--git-dir') `
    -FailureMessage 'Git could not resolve the disposable metadata directory.'
$ExpectedGitDirectory = [IO.Path]::GetFullPath(
    (Join-Path $ResolvedRepositoryRoot '.git')
)
$ResolvedGitDirectory = [IO.Path]::GetFullPath($GitDirectory.Trim())
if (-not $PathComparer.Equals(
    $ResolvedGitDirectory,
    $ExpectedGitDirectory
)) {
    throw 'Git resolved an unexpected disposable metadata directory.'
}
$GitDirectoryItem = Get-Item `
    -LiteralPath $ResolvedGitDirectory `
    -Force `
    -ErrorAction Stop
if (
    -not $GitDirectoryItem.PSIsContainer -or
    ($GitDirectoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
) {
    throw 'The disposable Git metadata root must be one real directory.'
}
$GitIndexPath = [IO.Path]::GetFullPath(
    (Join-Path $ResolvedGitDirectory 'index')
)
$GitIndexItem = Get-Item `
    -LiteralPath $GitIndexPath `
    -Force `
    -ErrorAction Stop
if (
    $GitIndexItem.PSIsContainer -or
    ($GitIndexItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not $PathComparer.Equals($GitIndexItem.FullName, $GitIndexPath)
) {
    throw 'The disposable Git index must be one real regular file.'
}

$HeadResult = Invoke-VerifiedGit -Arguments @('rev-parse', 'HEAD')
if ($HeadResult.ExitCode -ne 0) {
    throw 'Git could not read the disposable checkout head.'
}
$HeadOutput = @($HeadResult.Output)
if ($HeadOutput.Count -ne 1) {
    throw 'Git returned an invalid disposable checkout head.'
}
$ActualHead = ([string] $HeadOutput[0]).Trim()
if (
    $ActualHead -cnotmatch '^[0-9a-f]{40}$' -or
    $ActualHead -cne $ExpectedHead
) {
    throw 'The disposable checkout does not match the reviewed head.'
}

Assert-CanonicalGitIndexFlags
$GitIndexSha256 = Get-VerifiedFileSha256 -LiteralPath $GitIndexPath
$TrackedManifestSha256 = Get-TrackedContentManifestSha256
if (
    $VerificationStage -ceq 'Final' -and
    $GitIndexSha256 -cne $ExpectedGitIndexSha256
) {
    throw 'The disposable Git index changed after exact-head admission.'
}
if (
    $VerificationStage -ceq 'Final' -and
    $TrackedManifestSha256 -cne $ExpectedTrackedManifestSha256
) {
    throw 'Reviewed tracked content changed after exact-head admission.'
}

$StatusArguments = @('status', '--porcelain')
if ($VerificationStage -ceq 'Final') {
    $StatusArguments += '--untracked-files=no'
}
$StatusResult = Invoke-VerifiedGit -Arguments $StatusArguments
if ($StatusResult.ExitCode -ne 0) {
    throw 'Git could not verify the disposable checkout state.'
}
if (@($StatusResult.Output).Count -ne 0) {
    $State = if ($VerificationStage -ceq 'Initial') {
        'clean'
    }
    else {
        'unchanged'
    }
    throw "The disposable checkout is not $State."
}

if ($VerificationStage -ceq 'Initial') {
    Write-Output (
        'GITHUB_HOSTED_TRACKED_MANIFEST_SHA256=' +
        $TrackedManifestSha256
    )
    Write-Output "GITHUB_HOSTED_GIT_INDEX_SHA256=$GitIndexSha256"
}
$RunnerMarker = $ExpectedRunnerOs.ToLowerInvariant()
$StageMarker = $VerificationStage.ToLowerInvariant()
Write-Output "GITHUB_HOSTED_CHECKOUT=verified:${RunnerMarker}:$StageMarker"
