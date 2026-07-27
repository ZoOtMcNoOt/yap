#requires -Version 7.4
#requires -PSEdition Core

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $SourcePathsBase64,

    [Parameter(Mandatory)]
    [string] $LaunchSpecPath,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string] $LaunchSpecSha256,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string] $LaunchNonce,

    [Parameter(Mandatory)]
    [string] $StatusPath,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string] $ExpectedCSharpSourceSha256,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string] $ExpectedEnvironmentSha256,

    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string] $SupervisorIdentitySha256,

    [Parameter(Mandatory)]
    [ValidateRange(1000, 10000)]
    [int] $CleanupTimeoutMilliseconds
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$environmentBase64 = [Console]::In.ReadLine()
if ($null -eq $environmentBase64) {
    throw 'The Windows command environment prelude was not provided.'
}
$environmentBytes = [Convert]::FromBase64String($environmentBase64)
$environmentSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($environmentBytes)
).ToLowerInvariant()
if ($environmentSha256 -cne $ExpectedEnvironmentSha256) {
    throw 'The Windows command environment changed before target creation.'
}
$environmentJson = [Text.UTF8Encoding]::new($false, $true).GetString(
    $environmentBytes
)
$targetEnvironmentEntries = [string[]] @($environmentJson | ConvertFrom-Json)

$sourcePathsJson = [Text.UTF8Encoding]::new($false, $true).GetString(
    [Convert]::FromBase64String($SourcePathsBase64)
)
$sourcePaths = [string[]] @($sourcePathsJson | ConvertFrom-Json)
if ($sourcePaths.Count -ne 5) {
    throw 'The Windows command Job supervisor requires exactly five source files.'
}
if (($sourcePaths | Sort-Object -Unique).Count -ne $sourcePaths.Count) {
    throw 'Windows command Job supervisor source paths must be unique.'
}

$sourceBuffer = [IO.MemoryStream]::new()
try {
    for ($index = 0; $index -lt $sourcePaths.Count; $index += 1) {
        $sourcePath = $sourcePaths[$index]
        if (-not [IO.Path]::IsPathFullyQualified($sourcePath)) {
            throw 'Windows command Job supervisor source paths must be absolute.'
        }
        if ($index -gt 0) {
            $sourceBuffer.WriteByte(10)
        }
        $sourceStream = [IO.File]::Open(
            $sourcePath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::Read
        )
        try {
            $sourceStream.CopyTo($sourceBuffer)
        }
        finally {
            $sourceStream.Dispose()
        }
    }
    $sourceBytes = $sourceBuffer.ToArray()
}
finally {
    $sourceBuffer.Dispose()
}

$csharpSourceSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($sourceBytes)
).ToLowerInvariant()
if ($csharpSourceSha256 -cne $ExpectedCSharpSourceSha256) {
    throw 'The Windows command Job supervisor source changed before compilation.'
}
$sourceText = [Text.UTF8Encoding]::new($false, $true).GetString($sourceBytes)
Add-Type -TypeDefinition $sourceText -Language CSharp

$launchStream = [IO.File]::Open(
    $LaunchSpecPath,
    [IO.FileMode]::Open,
    [IO.FileAccess]::Read,
    [IO.FileShare]::None
)
try {
    $launchBuffer = [IO.MemoryStream]::new()
    try {
        $launchStream.CopyTo($launchBuffer)
        $launchBytes = $launchBuffer.ToArray()
    }
    finally {
        $launchBuffer.Dispose()
    }
}
finally {
    $launchStream.Dispose()
    [IO.File]::Delete($LaunchSpecPath)
}
$observedLaunchSpecSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData($launchBytes)
).ToLowerInvariant()
if ($observedLaunchSpecSha256 -cne $LaunchSpecSha256) {
    throw 'The Windows command launch specification changed before execution.'
}
$launchSpec = [Text.UTF8Encoding]::new($false, $true).GetString($launchBytes) |
    ConvertFrom-Json
if ([string] $launchSpec.launchNonce -cne $LaunchNonce) {
    throw 'The Windows command launch nonce did not match its invocation.'
}

$arguments = [string[]] @($launchSpec.arguments)
$wrapperExitCode = [Yap.Verification.WindowsCommandJobSupervisor]::Run(
    [string] $launchSpec.executablePath,
    $arguments,
    [string] $launchSpec.workingDirectory,
    $targetEnvironmentEntries,
    $StatusPath,
    $SupervisorIdentitySha256,
    $environmentSha256,
    $LaunchNonce,
    $LaunchSpecSha256,
    $CleanupTimeoutMilliseconds
)
exit $wrapperExitCode
