#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:MaximumDockerOutputChars = 4 * 1024 * 1024

function Assert-MockOidcDockerText {
    param(
        [Parameter(Mandatory)]
        [string]$Value,

        [Parameter(Mandatory)]
        [string]$Field,

        [Parameter(Mandatory)]
        [int]$MaximumChars
    )

    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value.Length -gt $MaximumChars -or
        -not $Value.IsNormalized() -or
        $Value.Trim() -cne $Value
    ) {
        throw "$Field is invalid."
    }
}

function ConvertFrom-MockOidcDockerOutput {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Output
    )

    return @(
        $Output -split '\r?\n' |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
}

function Invoke-MockOidcDockerCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments = @(),

        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [Parameter(Mandatory)]
        [ValidateRange(100, 300000)]
        [int]$TimeoutMilliseconds,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken,

        [Parameter(Mandatory)]
        [string]$Operation,

        [Parameter()]
        [Collections.IDictionary]$EnvironmentVariables = @{}
    )

    if (-not [IO.Path]::IsPathFullyQualified($DockerPath)) {
        throw 'Docker executable path is invalid.'
    }
    Assert-MockOidcDockerText -Value $Operation -Field 'Docker operation' `
        -MaximumChars 128
    if ($Arguments.Count -eq 0) {
        throw 'Docker arguments are required.'
    }

    $StartInfo = [Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = [IO.Path]::GetFullPath($DockerPath)
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    foreach ($Argument in @($DockerPrefixArguments) + @($Arguments)) {
        if ($null -eq $Argument) {
            throw 'Docker arguments must not contain null values.'
        }
        [void]$StartInfo.ArgumentList.Add([string]$Argument)
    }
    foreach ($Entry in $EnvironmentVariables.GetEnumerator()) {
        if (
            $Entry.Key -isnot [string] -or
            [string]::IsNullOrWhiteSpace([string]$Entry.Key) -or
            $Entry.Value -isnot [string]
        ) {
            throw 'Docker environment overrides are invalid.'
        }
        $StartInfo.Environment[[string]$Entry.Key] = [string]$Entry.Value
    }

    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    $Started = $false
    try {
        if ($CancellationToken.IsCancellationRequested) {
            throw [OperationCanceledException]::new("$Operation was cancelled.")
        }
        $Started = $Process.Start()
        if (-not $Started) {
            throw [InvalidOperationException]::new("$Operation did not start.")
        }
        $StandardOutputTask = $Process.StandardOutput.ReadToEndAsync()
        $StandardErrorTask = $Process.StandardError.ReadToEndAsync()
        $Elapsed = [Diagnostics.Stopwatch]::StartNew()
        while (-not $Process.WaitForExit(50)) {
            if ($CancellationToken.IsCancellationRequested) {
                throw [OperationCanceledException]::new(
                    "$Operation was cancelled."
                )
            }
            if ($Elapsed.ElapsedMilliseconds -ge $TimeoutMilliseconds) {
                throw [TimeoutException]::new("$Operation timed out.")
            }
        }
        $Process.WaitForExit()
        $StandardOutput = $StandardOutputTask.GetAwaiter().GetResult()
        $StandardError = $StandardErrorTask.GetAwaiter().GetResult()
        if (
            $StandardOutput.Length -gt $script:MaximumDockerOutputChars -or
            $StandardError.Length -gt $script:MaximumDockerOutputChars
        ) {
            throw [IO.InvalidDataException]::new(
                "$Operation output exceeded its bound."
            )
        }
        return [pscustomobject]@{
            ExitCode = $Process.ExitCode
            StandardOutput = $StandardOutput
        }
    }
    catch {
        $Failure = $_.Exception
        $TerminationFailed = $false
        if ($Started -and -not $Process.HasExited) {
            try {
                $Process.Kill($true)
                if (-not $Process.WaitForExit(5000)) {
                    $TerminationFailed = $true
                }
            }
            catch {
                if (-not $Process.HasExited) {
                    $TerminationFailed = $true
                }
            }
        }
        if ($TerminationFailed) {
            throw [InvalidOperationException]::new(
                "$Operation child process did not stop."
            )
        }
        if (
            $Failure -is [OperationCanceledException] -or
            $Failure -is [TimeoutException] -or
            $Failure -is [IO.InvalidDataException]
        ) {
            throw $Failure
        }
        throw [InvalidOperationException]::new("$Operation failed.")
    }
    finally {
        $Process.Dispose()
    }
}

function Test-LockedMockOidcDockerImageInspection {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Result,

        [Parameter(Mandatory)]
        [string]$ExpectedPlatform,

        [Parameter(Mandatory)]
        [string[]]$AllowedImageIds
    )

    if ($Result.ExitCode -ne 0) {
        return $false
    }
    $Parts = @($Result.StandardOutput.Trim() -split '\|')
    if (
        $Parts.Count -ne 2 -or
        $AllowedImageIds -cnotcontains $Parts[0] -or
        $Parts[1] -cne $ExpectedPlatform
    ) {
        throw 'Synthetic OIDC image differs from the locked platform image.'
    }
    return $true
}

function Resolve-LockedMockOidcDockerImage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments = @(),

        [Parameter(Mandatory)]
        [string]$ManifestReference,

        [Parameter(Mandatory)]
        [hashtable]$PlatformManifestDigests,

        [Parameter(Mandatory)]
        [hashtable]$PlatformConfigDigests,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken
    )

    Assert-MockOidcDockerText -Value $ManifestReference `
        -Field 'Synthetic OIDC manifest reference' -MaximumChars 512
    if ($ManifestReference -cnotmatch '@sha256:[0-9a-f]{64}$') {
        throw 'Synthetic OIDC manifest reference is not digest locked.'
    }
    if (
        $PlatformManifestDigests.Count -eq 0 -or
        $PlatformManifestDigests.Count -ne $PlatformConfigDigests.Count
    ) {
        throw 'Synthetic OIDC platform image identities are required.'
    }
    foreach ($Platform in $PlatformManifestDigests.Keys) {
        if (
            $Platform -isnot [string] -or
            [string]$Platform -cnotmatch '^[a-z0-9]+/[a-z0-9_]+$' -or
            -not $PlatformConfigDigests.ContainsKey($Platform)
        ) {
            throw 'Synthetic OIDC platform image identities are invalid.'
        }
        foreach ($Digest in @(
            $PlatformManifestDigests[$Platform],
            $PlatformConfigDigests[$Platform]
        )) {
            if (
                $Digest -isnot [string] -or
                [string]$Digest -cnotmatch '^sha256:[0-9a-f]{64}$'
            ) {
                throw 'Synthetic OIDC platform image identities are invalid.'
            }
        }
    }

    $PlatformResult = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments @(
            'version'
            '--format'
            '{{.Server.Os}}/{{.Server.Arch}}'
        ) `
        -TimeoutMilliseconds 15000 `
        -CancellationToken $CancellationToken `
        -Operation 'synthetic OIDC Docker platform inspection'
    $DockerPlatform = $PlatformResult.StandardOutput.Trim()
    if (
        $PlatformResult.ExitCode -ne 0 -or
        -not $PlatformManifestDigests.ContainsKey($DockerPlatform)
    ) {
        throw 'Synthetic OIDC Docker platform is not locked.'
    }

    $ExpectedConfigDigest = [string]$PlatformConfigDigests[$DockerPlatform]
    $ExpectedPlatformManifest = [string](
        $PlatformManifestDigests[$DockerPlatform]
    )
    foreach ($StagedReference in @(
        $ExpectedConfigDigest,
        $ExpectedPlatformManifest
    )) {
        $StagedImageResult = Invoke-MockOidcDockerCommand `
            -DockerPath $DockerPath `
            -DockerPrefixArguments $DockerPrefixArguments `
            -Arguments @(
                'image'
                'inspect'
                '--platform'
                $DockerPlatform
                '--format'
                '{{.Id}}|{{.Os}}/{{.Architecture}}'
                $StagedReference
            ) `
            -TimeoutMilliseconds 15000 `
            -CancellationToken $CancellationToken `
            -Operation 'synthetic OIDC staged-image inspection'
        if (
            Test-LockedMockOidcDockerImageInspection `
                -Result $StagedImageResult `
                -ExpectedPlatform $DockerPlatform `
                -AllowedImageIds @($StagedReference)
        ) {
            return [pscustomobject]@{
                Platform = $DockerPlatform
                Reference = $StagedReference
            }
        }
    }

    $PullResult = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments @(
            'pull'
            '--platform'
            $DockerPlatform
            $ManifestReference
        ) `
        -TimeoutMilliseconds 120000 `
        -CancellationToken $CancellationToken `
        -Operation 'synthetic OIDC image pull'
    if ($PullResult.ExitCode -ne 0) {
        throw 'Synthetic OIDC image pull failed.'
    }
    $PulledImageResult = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments @(
            'image'
            'inspect'
            '--platform'
            $DockerPlatform
            '--format'
            '{{.Id}}|{{.Os}}/{{.Architecture}}'
            $ManifestReference
        ) `
        -TimeoutMilliseconds 15000 `
        -CancellationToken $CancellationToken `
        -Operation 'synthetic OIDC pulled-image inspection'
    if (
        -not (
            Test-LockedMockOidcDockerImageInspection `
                -Result $PulledImageResult `
                -ExpectedPlatform $DockerPlatform `
                -AllowedImageIds @(
                    $ExpectedConfigDigest,
                    $ExpectedPlatformManifest
                )
        )
    ) {
        throw 'Synthetic OIDC pulled image could not be inspected.'
    }
    return [pscustomobject]@{
        Platform = $DockerPlatform
        Reference = $ManifestReference
    }
}

function Invoke-MockOidcDockerResourceCreate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments = @(),

        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [Parameter(Mandatory)]
        [ValidateRange(100, 300000)]
        [int]$TimeoutMilliseconds,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken,

        [Parameter(Mandatory)]
        [string]$Operation,

        [Parameter()]
        [Collections.IDictionary]$EnvironmentVariables = @{}
    )

    $Result = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments $Arguments `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -CancellationToken $CancellationToken `
        -Operation $Operation `
        -EnvironmentVariables $EnvironmentVariables
    if ($Result.ExitCode -ne 0) {
        throw [InvalidOperationException]::new("$Operation failed.")
    }
    $Identifier = $Result.StandardOutput.Trim()
    if ($Identifier -cnotmatch '^[0-9a-f]{64}$') {
        throw [IO.InvalidDataException]::new("$Operation returned invalid output.")
    }
    return $Identifier
}

function Get-MockOidcDockerResourceNames {
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments,

        [Parameter(Mandatory)]
        [ValidateSet('container', 'network')]
        [string]$ResourceKind,

        [Parameter(Mandatory)]
        [string]$ResourceName,

        [Parameter(Mandatory)]
        [int]$TimeoutMilliseconds,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken
    )

    $Arguments = if ($ResourceKind -ceq 'container') {
        @(
            'container',
            'ls',
            '--all',
            '--filter',
            "name=$ResourceName",
            '--format',
            '{{.Names}}'
        )
    }
    else {
        @(
            'network',
            'ls',
            '--filter',
            "name=$ResourceName",
            '--format',
            '{{.Name}}'
        )
    }
    $Result = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments $Arguments `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -CancellationToken $CancellationToken `
        -Operation 'synthetic OIDC resource enumeration'
    if ($Result.ExitCode -ne 0) {
        throw 'Synthetic OIDC resource enumeration failed.'
    }
    return @(ConvertFrom-MockOidcDockerOutput -Output $Result.StandardOutput)
}

function Test-OwnedMockOidcDockerResource {
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments,

        [Parameter(Mandatory)]
        [ValidateSet('container', 'network')]
        [string]$ResourceKind,

        [Parameter(Mandatory)]
        [string]$ResourceName,

        [Parameter(Mandatory)]
        [string]$OwnerLabelKey,

        [Parameter(Mandatory)]
        [string]$OwnerLabelValue,

        [Parameter(Mandatory)]
        [int]$TimeoutMilliseconds,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken
    )

    $Format = if ($ResourceKind -ceq 'container') {
        '{{index .Config.Labels "' + $OwnerLabelKey + '"}}'
    }
    else {
        '{{index .Labels "' + $OwnerLabelKey + '"}}'
    }
    $Result = Invoke-MockOidcDockerCommand `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -Arguments @(
            $ResourceKind,
            'inspect',
            '--format',
            $Format,
            $ResourceName
        ) `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -CancellationToken $CancellationToken `
        -Operation 'synthetic OIDC resource ownership inspection'
    if ($Result.ExitCode -eq 0) {
        if ($Result.StandardOutput.Trim() -cne $OwnerLabelValue) {
            throw 'Synthetic OIDC resource is not owned by this harness.'
        }
        return $true
    }

    $Names = @(
        Get-MockOidcDockerResourceNames `
            -DockerPath $DockerPath `
            -DockerPrefixArguments $DockerPrefixArguments `
            -ResourceKind $ResourceKind `
            -ResourceName $ResourceName `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -CancellationToken $CancellationToken
    )
    if ($Names -ccontains $ResourceName) {
        throw 'Synthetic OIDC resource ownership could not be inspected.'
    }
    return $false
}

function Remove-OwnedMockOidcDockerResource {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$DockerPath,

        [Parameter()]
        [string[]]$DockerPrefixArguments = @(),

        [Parameter(Mandatory)]
        [ValidateSet('container', 'network')]
        [string]$ResourceKind,

        [Parameter(Mandatory)]
        [string]$ResourceName,

        [Parameter(Mandatory)]
        [string]$OwnerLabelKey,

        [Parameter(Mandatory)]
        [string]$OwnerLabelValue,

        [Parameter(Mandatory)]
        [ValidateRange(100, 300000)]
        [int]$TimeoutMilliseconds,

        [Parameter(Mandatory)]
        [Threading.CancellationToken]$CancellationToken
    )

    if ($ResourceName -cnotmatch '^[a-z0-9][a-z0-9_.-]{0,127}$') {
        throw 'Synthetic OIDC resource name is invalid.'
    }
    if ($OwnerLabelKey -cnotmatch '^[a-z0-9][a-z0-9_.-]{0,127}$') {
        throw 'Synthetic OIDC owner-label key is invalid.'
    }
    Assert-MockOidcDockerText -Value $OwnerLabelValue `
        -Field 'Synthetic OIDC owner-label value' -MaximumChars 128

    $Owned = Test-OwnedMockOidcDockerResource `
        -DockerPath $DockerPath `
        -DockerPrefixArguments $DockerPrefixArguments `
        -ResourceKind $ResourceKind `
        -ResourceName $ResourceName `
        -OwnerLabelKey $OwnerLabelKey `
        -OwnerLabelValue $OwnerLabelValue `
        -TimeoutMilliseconds $TimeoutMilliseconds `
        -CancellationToken $CancellationToken
    if ($Owned) {
        $RemoveArguments = if ($ResourceKind -ceq 'container') {
            @('container', 'rm', '--force', $ResourceName)
        }
        else {
            @('network', 'rm', $ResourceName)
        }
        $RemoveResult = Invoke-MockOidcDockerCommand `
            -DockerPath $DockerPath `
            -DockerPrefixArguments $DockerPrefixArguments `
            -Arguments $RemoveArguments `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -CancellationToken $CancellationToken `
            -Operation 'synthetic OIDC owned-resource removal'
        if ($RemoveResult.ExitCode -ne 0) {
            $NamesAfterFailedRemoval = @(
                Get-MockOidcDockerResourceNames `
                    -DockerPath $DockerPath `
                    -DockerPrefixArguments $DockerPrefixArguments `
                    -ResourceKind $ResourceKind `
                    -ResourceName $ResourceName `
                    -TimeoutMilliseconds $TimeoutMilliseconds `
                    -CancellationToken $CancellationToken
            )
            if ($NamesAfterFailedRemoval -ccontains $ResourceName) {
                throw 'Synthetic OIDC owned-resource removal failed.'
            }
        }
    }

    $RemainingNames = @(
        Get-MockOidcDockerResourceNames `
            -DockerPath $DockerPath `
            -DockerPrefixArguments $DockerPrefixArguments `
            -ResourceKind $ResourceKind `
            -ResourceName $ResourceName `
            -TimeoutMilliseconds $TimeoutMilliseconds `
            -CancellationToken $CancellationToken
    )
    if ($RemainingNames -ccontains $ResourceName) {
        throw 'Synthetic OIDC owned resource remained after teardown.'
    }
}

Export-ModuleMember -Function @(
    'Invoke-MockOidcDockerCommand',
    'Invoke-MockOidcDockerResourceCreate',
    'Resolve-LockedMockOidcDockerImage',
    'Remove-OwnedMockOidcDockerResource'
)
