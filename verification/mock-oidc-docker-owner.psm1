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
    'Remove-OwnedMockOidcDockerResource'
)
