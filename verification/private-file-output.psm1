#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-LinuxFileOwnerId {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $StatPath = '/usr/bin/stat'
    if (-not (Test-Path -LiteralPath $StatPath -PathType Leaf)) {
        throw 'Private file output requires the Linux stat executable.'
    }
    $OwnerOutput = @(
        & $StatPath --format=%u -- $Path 2> $null
    )
    if (
        $LASTEXITCODE -ne 0 -or
        $OwnerOutput.Count -ne 1 -or
        $OwnerOutput[0].Trim() -cnotmatch '^[0-9]+$'
    ) {
        throw 'Private file output could not resolve Linux ownership.'
    }
    return [uint32]$OwnerOutput[0].Trim()
}

function Get-LinuxEffectiveUserId {
    $IdPath = '/usr/bin/id'
    if (-not (Test-Path -LiteralPath $IdPath -PathType Leaf)) {
        throw 'Private file output requires the Linux id executable.'
    }
    $UserOutput = @(& $IdPath --user 2> $null)
    if (
        $LASTEXITCODE -ne 0 -or
        $UserOutput.Count -ne 1 -or
        $UserOutput[0].Trim() -cnotmatch '^[0-9]+$'
    ) {
        throw 'Private file output could not resolve its Linux identity.'
    }
    return [uint32]$UserOutput[0].Trim()
}

function Assert-LinuxRealDirectory {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $Item = Get-Item -LiteralPath $Path -Force
    if (
        -not $Item.PSIsContainer -or
        ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $null -ne $Item.LinkTarget
    ) {
        throw 'Private file output rejects linked directory components.'
    }
}

function Assert-LinuxPrivateDirectoryBoundary {
    param(
        [Parameter(Mandatory)]
        [string]$DirectoryPath
    )

    Assert-LinuxRealDirectory -Path $DirectoryPath
    $EffectiveUserId = Get-LinuxEffectiveUserId
    if ((Get-LinuxFileOwnerId -Path $DirectoryPath) -ne $EffectiveUserId) {
        throw 'Private file output requires an executor-owned parent directory.'
    }

    $CurrentPath = [IO.Path]::GetFullPath($DirectoryPath)
    while ($CurrentPath -cne [IO.Path]::GetPathRoot($CurrentPath)) {
        $ContainingPath = [IO.Directory]::GetParent($CurrentPath).FullName
        Assert-LinuxRealDirectory -Path $ContainingPath
        $ContainingMode = [IO.File]::GetUnixFileMode($ContainingPath)
        $ContainingOwnerId = Get-LinuxFileOwnerId -Path $ContainingPath
        if (
            $ContainingOwnerId -notin @([uint32]0, $EffectiveUserId)
        ) {
            throw 'Private file output has an untrusted ancestor owner.'
        }

        $SharedWrite = (
            ($ContainingMode -band [IO.UnixFileMode]::GroupWrite) -ne 0 -or
            ($ContainingMode -band [IO.UnixFileMode]::OtherWrite) -ne 0
        )
        if ($SharedWrite) {
            $Sticky = (
                ($ContainingMode -band [IO.UnixFileMode]::StickyBit) -ne 0
            )
            $CurrentOwnerId = Get-LinuxFileOwnerId -Path $CurrentPath
            if (
                -not $Sticky -or
                $ContainingOwnerId -notin @([uint32]0, $EffectiveUserId) -or
                $CurrentOwnerId -notin @([uint32]0, $EffectiveUserId)
            ) {
                throw 'Private file output has a replaceable ancestor.'
            }
        }
        $CurrentPath = $ContainingPath
    }
}

function Write-NewPrivateFileAtomically {
    param(
        [Parameter(Mandatory)]
        [string]$DestinationPath,

        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [byte[]]$Content
    )

    if (-not [IO.Path]::IsPathFullyQualified($DestinationPath)) {
        throw 'Private file output must be absolute.'
    }
    $CanonicalDestination = [IO.Path]::GetFullPath($DestinationPath)
    $ParentPath = [IO.Path]::GetDirectoryName($CanonicalDestination)
    $ParentItem = Get-Item -LiteralPath $ParentPath -Force
    if (
        -not $ParentItem.PSIsContainer -or
        ($ParentItem.Attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        throw 'Private file output requires a real parent directory.'
    }
    [IO.UnixFileMode]$PrivateDirectoryMode = (
        [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::UserWrite -bor
        [IO.UnixFileMode]::UserExecute
    )
    $PrivateArtifactHelper = Join-Path $PSScriptRoot 'private-gate-artifacts.ps1'
    if ([OperatingSystem]::IsWindows()) {
        & $PrivateArtifactHelper `
            -Operation verify-directory `
            -LiteralPath $ParentItem.FullName | Out-Null
    }
    elseif (
        [IO.File]::GetUnixFileMode($ParentItem.FullName) -ne
            $PrivateDirectoryMode
    ) {
        throw 'Private file output requires a user-only parent directory.'
    }
    if ([OperatingSystem]::IsLinux()) {
        Assert-LinuxPrivateDirectoryBoundary `
            -DirectoryPath $ParentItem.FullName
    }
    elseif (-not [OperatingSystem]::IsWindows()) {
        throw 'Private file output supports only Windows and Linux.'
    }
    if (Test-Path -LiteralPath $CanonicalDestination) {
        throw 'Private file output must be new.'
    }

    [IO.UnixFileMode]$PrivateUnixMode = (
        [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::UserWrite
    )
    $TemporaryPath = Join-Path $ParentItem.FullName (
        ".$([IO.Path]::GetFileName($CanonicalDestination))." +
        "$([guid]::NewGuid().ToString('N')).tmp"
    )
    $DestinationLinked = $false
    $PublicationSucceeded = $false
    try {
        $StreamOptions = [IO.FileStreamOptions]::new()
        $StreamOptions.Mode = [IO.FileMode]::CreateNew
        $StreamOptions.Access = [IO.FileAccess]::Write
        $StreamOptions.Share = [IO.FileShare]::None
        if (-not [OperatingSystem]::IsWindows()) {
            $StreamOptions.UnixCreateMode = $PrivateUnixMode
        }

        $OutputStream = [IO.File]::Open($TemporaryPath, $StreamOptions)
        try {
            $OutputStream.Write($Content, 0, $Content.Length)
            $OutputStream.Flush($true)
        }
        finally {
            $OutputStream.Dispose()
        }

        if ([OperatingSystem]::IsWindows()) {
            & $PrivateArtifactHelper `
                -Operation protect-file `
                -LiteralPath $TemporaryPath | Out-Null
        }
        elseif (
            [IO.File]::GetUnixFileMode($TemporaryPath) -ne $PrivateUnixMode
        ) {
            throw 'Private file output was not created with user-only access.'
        }
        New-Item `
            -ItemType HardLink `
            -Path $CanonicalDestination `
            -Target $TemporaryPath `
            -ErrorAction Stop | Out-Null
        $DestinationLinked = $true
        if (
            -not [OperatingSystem]::IsWindows() -and
            [IO.File]::GetUnixFileMode($CanonicalDestination) -ne
                $PrivateUnixMode
        ) {
            throw 'Private file output did not retain user-only access.'
        }
        Remove-Item -LiteralPath $TemporaryPath -Force
        if ([OperatingSystem]::IsWindows()) {
            & $PrivateArtifactHelper `
                -Operation verify-file `
                -LiteralPath $CanonicalDestination | Out-Null
        }
        $PublicationSucceeded = $true
    }
    finally {
        try {
            if (
                -not $PublicationSucceeded -and
                $DestinationLinked -and
                (Test-Path -LiteralPath $CanonicalDestination)
            ) {
                Remove-Item -LiteralPath $CanonicalDestination -Force
            }
        }
        finally {
            if (Test-Path -LiteralPath $TemporaryPath) {
                Remove-Item -LiteralPath $TemporaryPath -Force
            }
        }
    }
}

Export-ModuleMember -Function Write-NewPrivateFileAtomically
