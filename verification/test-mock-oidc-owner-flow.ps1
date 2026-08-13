#requires -Version 7.4
#requires -PSEdition Core

param(
    [Parameter()]
    [string]$CheckedHead,

    [Parameter()]
    [string]$ReceiptOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = [IO.Path]::GetFullPath(
    (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
)
$RunningOnWindows = [OperatingSystem]::IsWindows()
$RunningOnLinux = [OperatingSystem]::IsLinux()
$PathComparison = if ($RunningOnWindows) {
    [StringComparison]::OrdinalIgnoreCase
}
else {
    [StringComparison]::Ordinal
}

function Assert-ExactCleanHead {
    param(
        [Parameter(Mandatory)]
        [string]$ExpectedHead
    )

    $Git = Get-Command git -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $PreviousPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $ActualHead = @(
            & $Git.Source -C $Repository rev-parse --verify HEAD 2> $null
        )
        if (
            $LASTEXITCODE -ne 0 -or
            $ActualHead.Count -ne 1 -or
            $ActualHead[0].Trim() -cne $ExpectedHead
        ) {
            throw 'The synthetic OIDC receipt head does not match the checkout.'
        }
        $TrackedStatus = @(
            & $Git.Source -C $Repository status --short `
                --untracked-files=no 2> $null
        )
        if ($LASTEXITCODE -ne 0 -or $TrackedStatus.Count -ne 0) {
            throw 'The synthetic OIDC receipt checkout has tracked drift.'
        }
    }
    finally {
        $PSNativeCommandUseErrorActionPreference = $PreviousPreference
    }
}

function Resolve-NewReceiptOutput {
    param(
        [Parameter(Mandatory)]
        [string]$OutputPath
    )

    if (-not [IO.Path]::IsPathFullyQualified($OutputPath)) {
        throw 'The synthetic OIDC receipt output must be absolute.'
    }
    $CanonicalOutput = [IO.Path]::GetFullPath($OutputPath)
    $RequestedParent = [IO.Path]::GetDirectoryName($CanonicalOutput)
    $ParentItem = Get-Item -LiteralPath $RequestedParent -Force
    if (
        -not $ParentItem.PSIsContainer -or
        ($ParentItem.Attributes -band [IO.FileAttributes]::ReparsePoint)
    ) {
        throw 'The synthetic OIDC receipt parent must be a real directory.'
    }
    $CanonicalParent = [IO.Path]::GetFullPath(
        (Resolve-Path -LiteralPath $RequestedParent).Path
    )
    if (
        -not [string]::Equals(
            $RequestedParent,
            $CanonicalParent,
            $PathComparison
        )
    ) {
        throw 'The synthetic OIDC receipt parent must not be redirected.'
    }
    $RelativeToRepository = [IO.Path]::GetRelativePath(
        $Repository,
        $CanonicalOutput
    )
    $OutsideRepository = (
        $RelativeToRepository -ceq '..' -or
        $RelativeToRepository.StartsWith(
            "..$([IO.Path]::DirectorySeparatorChar)",
            $PathComparison
        ) -or
        $RelativeToRepository.StartsWith(
            "..$([IO.Path]::AltDirectorySeparatorChar)",
            $PathComparison
        ) -or
        [IO.Path]::IsPathFullyQualified($RelativeToRepository)
    )
    if (-not $OutsideRepository) {
        throw 'The synthetic OIDC receipt output must stay outside Git.'
    }
    if (Test-Path -LiteralPath $CanonicalOutput) {
        throw 'The synthetic OIDC receipt output must be new.'
    }
    return [pscustomobject]@{
        Path = $CanonicalOutput
        Parent = $CanonicalParent
    }
}

$HasCheckedHead = -not [string]::IsNullOrWhiteSpace($CheckedHead)
$HasReceiptOutput = -not [string]::IsNullOrWhiteSpace($ReceiptOutput)
if ($HasCheckedHead -xor $HasReceiptOutput) {
    throw 'CheckedHead and ReceiptOutput must be supplied together.'
}
$ReceiptMode = $HasCheckedHead -and $HasReceiptOutput
$ReceiptDestination = $null
if ($ReceiptMode) {
    if (-not ($RunningOnWindows -or $RunningOnLinux)) {
        throw 'Synthetic OIDC receipt publication supports Windows or Linux.'
    }
    if ($CheckedHead -cnotmatch '^[0-9a-f]{40}$') {
        throw 'The synthetic OIDC receipt head must be a lowercase SHA-1.'
    }
    $ReceiptDestination = Resolve-NewReceiptOutput -OutputPath $ReceiptOutput
    Assert-ExactCleanHead -ExpectedHead $CheckedHead
}

$ServerRoot = Join-Path $Repository 'server'
$LockPath = Join-Path $PSScriptRoot 'mock-oidc-provider.lock.json'
$Lock = Get-Content -LiteralPath $LockPath -Raw | ConvertFrom-Json
$ExpectedDigest = 'sha256:f625692f5bf84939f3d0af4931f2c0f038dca84c4f1bac1171710d544181f97f'
$ExpectedPlatformManifestDigests = @{
    'linux/amd64' = 'sha256:26c173827c93382eab6543dfc66d5707e39024868618d3c3fd8e6f694717333c'
    'linux/arm64' = 'sha256:9687bd8fdd9d9ddbbe10de97aac103f7aa6e1b9f9f1426e0cf476945ecdde5b9'
}
$ExpectedPlatformConfigDigests = @{
    'linux/amd64' = 'sha256:9acf7f7170b230703710e7454105b9bd8cd7922460b3403837821b78e1272e17'
    'linux/arm64' = 'sha256:06bfe1111be534917068f27b5424bd64feb0fb2be3d4eace7f34765d6b4be508'
}
$LockedDigestMaps = @{}
foreach ($LockField in @('platformManifests', 'platformConfigDigests')) {
    $LockedDigestMaps[$LockField] = @{}
    $LockValue = $Lock.$LockField
    if ($null -ne $LockValue) {
        foreach ($Property in $LockValue.PSObject.Properties) {
            $LockedDigestMaps[$LockField][$Property.Name] = (
                [string]$Property.Value
            )
        }
    }
}
$ExpectedDigestMaps = @{
    platformManifests = $ExpectedPlatformManifestDigests
    platformConfigDigests = $ExpectedPlatformConfigDigests
}
$PlatformDigestLocksMatch = @(
    foreach ($LockField in $ExpectedDigestMaps.Keys) {
        $ExpectedMap = $ExpectedDigestMaps[$LockField]
        $LockedMap = $LockedDigestMaps[$LockField]
        if (
            $LockedMap.Count -ne $ExpectedMap.Count -or
            @(
                $ExpectedMap.GetEnumerator() |
                    Where-Object {
                        -not $LockedMap.ContainsKey($_.Key) -or
                        $LockedMap[$_.Key] -cne $_.Value
                    }
            ).Count -ne 0
        ) {
            $false
        }
    }
).Count -eq 0
if (
    $Lock.schemaVersion -ne 1 -or
    $Lock.provider -cne 'navikt/mock-oauth2-server' -or
    $Lock.version -cne '5.0.2' -or
    $Lock.license -cne 'MIT' -or
    $Lock.manifestDigest -cne $ExpectedDigest -or
    $Lock.reference -cne "ghcr.io/navikt/mock-oauth2-server:5.0.2@$ExpectedDigest" -or
    -not $PlatformDigestLocksMatch
) {
    throw 'The synthetic OIDC provider lock is invalid.'
}
$ImageReference = [string]$Lock.reference
$Docker = Get-Command docker -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
Import-Module (Join-Path $PSScriptRoot 'mock-oidc-docker-owner.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'exact-python-runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'private-file-output.psm1') -Force
$Runtime = Sync-LockedServerEnvironment -ServerRoot $ServerRoot
$OwnerLabelKey = 'com.mcnatg1.yap.test-owner'
$OwnerLabelValue = 'mock-oidc'

$Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$Listener.Start()
$ProviderPort = ([Net.IPEndPoint]$Listener.LocalEndpoint).Port
$Listener.Stop()

$Suffix = [guid]::NewGuid().ToString('N')
$NetworkName = "yap-mock-oidc-$Suffix"
$ContainerName = "yap-mock-oidc-$Suffix"
$DirectorySeparators = [char[]]@(
    [IO.Path]::DirectorySeparatorChar
    [IO.Path]::AltDirectorySeparatorChar
)
$CanonicalTemp = [IO.Path]::GetFullPath(
    [IO.Path]::GetTempPath()
).TrimEnd($DirectorySeparators)
$StateRoot = [IO.Path]::GetFullPath(
    (Join-Path $CanonicalTemp "yap-mock-oidc-$Suffix")
)
$StateRootPrefix = Join-Path $CanonicalTemp 'yap-mock-oidc-'
if (
    -not [string]::Equals(
        [IO.Path]::GetDirectoryName($StateRoot),
        $CanonicalTemp,
        $PathComparison
    )
) {
    throw 'Synthetic OIDC state escaped the temporary directory.'
}

$Claims = @{
    alice = @{
        sub = '00000000-0000-4000-8000-000000000072'
        aud = @('00000000-0000-4000-8000-000000000075')
        tid = '00000000-0000-4000-8000-000000000071'
        oid = '00000000-0000-4000-8000-000000000072'
        azp = '00000000-0000-4000-8000-000000000074'
        scp = 'access_as_user'
        roles = @('Yap.IdentityAdministrator')
    }
    bob = @{
        sub = '00000000-0000-4000-8000-000000000073'
        aud = @('00000000-0000-4000-8000-000000000075')
        tid = '00000000-0000-4000-8000-000000000071'
        oid = '00000000-0000-4000-8000-000000000073'
        azp = '00000000-0000-4000-8000-000000000074'
        scp = 'access_as_user'
        roles = @()
    }
    'wrong-audience' = @{
        sub = '00000000-0000-4000-8000-000000000072'
        aud = @('00000003-0000-0000-c000-000000000000')
        tid = '00000000-0000-4000-8000-000000000071'
        oid = '00000000-0000-4000-8000-000000000072'
        azp = '00000000-0000-4000-8000-000000000074'
        scp = 'access_as_user'
        roles = @()
    }
    'insufficient-scope' = @{
        sub = '00000000-0000-4000-8000-000000000072'
        aud = @('00000000-0000-4000-8000-000000000075')
        tid = '00000000-0000-4000-8000-000000000071'
        oid = '00000000-0000-4000-8000-000000000072'
        azp = '00000000-0000-4000-8000-000000000074'
        scp = 'User.Read'
        roles = @()
    }
}
$Mappings = foreach ($Fixture in @(
    'alice',
    'bob',
    'wrong-audience',
    'insufficient-scope'
)) {
    @{
        requestParam = 'fixture'
        match = $Fixture
        typeHeader = 'at+jwt'
        claims = $Claims[$Fixture]
    }
}
$JsonConfig = @{
    interactiveLogin = $false
    httpServer = 'NettyWrapper'
    tokenCallbacks = @(
        @{
            issuerId = 'yap-phase7'
            tokenExpiry = 300
            requestMappings = @($Mappings)
        }
    )
} | ConvertTo-Json -Depth 10 -Compress

$RunCancellationSource = [Threading.CancellationTokenSource]::new()
$CleanupCancellationSource = $null
$script:CancellationSource = $RunCancellationSource
$CancelHandler = [ConsoleCancelEventHandler]{
    param($Sender, $EventArgs)
    $EventArgs.Cancel = $true
    $script:CancellationSource.Cancel()
}

$Flow = $null
$LoopbackProxy = $null
$Result = $null
$RunFailure = $null
$CancelHandlerRegistered = $false
$NetworkCreateAttempted = $false
$ContainerRunAttempted = $false
$TeardownFailures = [Collections.Generic.List[string]]::new()
$PreviousPythonPath = [Environment]::GetEnvironmentVariable(
    'PYTHONPATH',
    [EnvironmentVariableTarget]::Process
)

try {
    New-Item -ItemType Directory -Path $StateRoot | Out-Null
    [Console]::add_CancelKeyPress($CancelHandler)
    $CancelHandlerRegistered = $true

    $ResolvedImage = Resolve-LockedMockOidcDockerImage `
        -DockerPath $Docker.Source `
        -ManifestReference $ImageReference `
        -PlatformManifestDigests $ExpectedPlatformManifestDigests `
        -PlatformConfigDigests $ExpectedPlatformConfigDigests `
        -CancellationToken $RunCancellationSource.Token
    $DockerPlatform = $ResolvedImage.Platform
    $RunnableImageReference = $ResolvedImage.Reference

    $NetworkCreateAttempted = $true
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $Docker.Source `
        -Arguments @(
            'network',
            'create',
            '--internal',
            '--label',
            "$OwnerLabelKey=$OwnerLabelValue",
            $NetworkName
        ) `
        -TimeoutMilliseconds 15000 `
        -CancellationToken $RunCancellationSource.Token `
        -Operation 'synthetic OIDC internal network creation' | Out-Null

    $InternalNetworkResult = Invoke-MockOidcDockerCommand `
        -DockerPath $Docker.Source `
        -Arguments @(
            'network'
            'inspect'
            '--format'
            '{{.Name}}|{{.Internal}}'
            $NetworkName
        ) `
        -TimeoutMilliseconds 15000 `
        -CancellationToken $RunCancellationSource.Token `
        -Operation 'synthetic OIDC internal network inspection'
    if (
        $InternalNetworkResult.ExitCode -ne 0 -or
        $InternalNetworkResult.StandardOutput.Trim() -cne "$NetworkName|true"
    ) {
        throw 'Synthetic OIDC network is not the required internal bridge.'
    }

    $ContainerArguments = @(
        'run'
        '--detach'
        '--rm'
        '--pull'
        'never'
        '--platform'
        $DockerPlatform
        '--name'
        $ContainerName
        '--label'
        "$OwnerLabelKey=$OwnerLabelValue"
        '--hostname'
        'localhost'
        '--network'
        $NetworkName
    )
    if (-not $RunningOnLinux) {
        $ContainerArguments += @(
            '--publish'
            "127.0.0.1:${ProviderPort}:8080"
        )
    }
    $ContainerArguments += @(
        '--read-only'
        '--tmpfs'
        '/tmp:rw,noexec,nosuid,size=32m'
        '--cap-drop'
        'ALL'
        '--security-opt'
        'no-new-privileges=true'
        '--memory'
        '512m'
        '--cpus'
        '1'
        '--env'
        'SERVER_HOSTNAME=0.0.0.0'
        '--env'
        'JSON_CONFIG'
        $RunnableImageReference
    )

    $ContainerRunAttempted = $true
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $Docker.Source `
        -Arguments $ContainerArguments `
        -TimeoutMilliseconds 30000 `
        -CancellationToken $RunCancellationSource.Token `
        -Operation 'synthetic OIDC container startup' `
        -EnvironmentVariables @{ JSON_CONFIG = $JsonConfig } | Out-Null
    $ConfiguredImageResult = Invoke-MockOidcDockerCommand `
        -DockerPath $Docker.Source `
        -Arguments @(
            'container',
            'inspect',
            '--format',
            '{{.Config.Image}}',
            $ContainerName
        ) `
        -TimeoutMilliseconds 15000 `
        -CancellationToken $RunCancellationSource.Token `
        -Operation 'synthetic OIDC locked-image inspection'
    $ConfiguredImage = $ConfiguredImageResult.StandardOutput.Trim()
    if (
        $ConfiguredImageResult.ExitCode -ne 0 -or
        $ConfiguredImage -cne $RunnableImageReference
    ) {
        throw 'Synthetic OIDC container did not retain the locked image ID.'
    }

    if ($RunningOnLinux) {
        $NetworkIdentityResult = Invoke-MockOidcDockerCommand `
            -DockerPath $Docker.Source `
            -Arguments @(
                'container'
                'inspect'
                '--format'
                '{{.HostConfig.NetworkMode}}|{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
                $ContainerName
            ) `
            -TimeoutMilliseconds 15000 `
            -CancellationToken $RunCancellationSource.Token `
            -Operation 'synthetic OIDC network identity inspection'
        $NetworkIdentity = $NetworkIdentityResult.StandardOutput.Trim()
        $NetworkIdentityParts = $NetworkIdentity.Split('|')
        if (
            $NetworkIdentityResult.ExitCode -ne 0 -or
            $NetworkIdentityParts.Count -ne 2 -or
            $NetworkIdentityParts[0] -cne $NetworkName -or
            $NetworkIdentityParts[1] -cnotmatch (
                '^(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})' +
                '(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}$'
            )
        ) {
            throw 'Synthetic OIDC container network identity is invalid.'
        }
        $ProxyStartInfo = [Diagnostics.ProcessStartInfo]::new()
        $ProxyStartInfo.FileName = $Runtime.Python
        $ProxyStartInfo.UseShellExecute = $false
        $ProxyStartInfo.CreateNoWindow = $true
        $ProxyStartInfo.RedirectStandardOutput = $true
        $ProxyStartInfo.RedirectStandardError = $true
        foreach ($ProxyArgument in @(
            (Join-Path $PSScriptRoot 'mock-oidc-loopback-proxy.py')
            '--listen-port'
            $ProviderPort
            '--target-address'
            $NetworkIdentityParts[1]
            '--target-port'
            8080
        )) {
            $ProxyStartInfo.ArgumentList.Add([string]$ProxyArgument)
        }
        $LoopbackProxy = [Diagnostics.Process]::new()
        $LoopbackProxy.StartInfo = $ProxyStartInfo
        if (-not $LoopbackProxy.Start()) {
            throw 'Synthetic OIDC loopback proxy failed to start.'
        }
        $ProxyReadyLine = $LoopbackProxy.StandardOutput.ReadLineAsync()
        $ProxyDeadline = [DateTime]::UtcNow.AddSeconds(10)
        $ProxyReady = $false
        while (-not $ProxyReady) {
            $LoopbackProxy.Refresh()
            if ($LoopbackProxy.HasExited) {
                throw 'Synthetic OIDC loopback proxy exited during startup.'
            }
            if ([DateTime]::UtcNow -ge $ProxyDeadline) {
                throw [TimeoutException]::new(
                    'Synthetic OIDC loopback proxy readiness timed out.'
                )
            }
            if ($ProxyReadyLine.IsCompleted) {
                $ProxyReady = (
                    $ProxyReadyLine.GetAwaiter().GetResult() -ceq
                    'MOCK_OIDC_LOOPBACK_PROXY=READY'
                )
                if (-not $ProxyReady) {
                    throw 'Synthetic OIDC loopback proxy readiness was invalid.'
                }
            }
            if (-not $ProxyReady) {
                Start-Sleep -Milliseconds 100
            }
        }
    }

    $ProviderBaseUrl = "http://127.0.0.1:$ProviderPort"
    $ReadyDeadline = [DateTime]::UtcNow.AddSeconds(30)
    $Ready = $false
    while (-not $Ready) {
        if ($script:CancellationSource.IsCancellationRequested) {
            throw [OperationCanceledException]::new('Synthetic OIDC readiness cancelled.')
        }
        if ([DateTime]::UtcNow -ge $ReadyDeadline) {
            throw [TimeoutException]::new('Synthetic OIDC readiness timed out.')
        }
        try {
            $Response = Invoke-WebRequest `
                -Uri "$ProviderBaseUrl/isalive" `
                -TimeoutSec 2
            $Ready = $Response.StatusCode -eq 200
        }
        catch {
            Start-Sleep -Milliseconds 200
        }
    }

    $PathSeparator = [IO.Path]::PathSeparator
    $env:PYTHONPATH = (
        (Join-Path $ServerRoot 'src'),
        $ServerRoot
    ) -join $PathSeparator
    $FlowOut = Join-Path $StateRoot 'flow.stdout'
    $FlowErr = Join-Path $StateRoot 'flow.stderr'
    $FlowStart = @{
        FilePath = $Runtime.Python
        ArgumentList = @(
            (Join-Path $PSScriptRoot 'mock-oidc-owner-flow.py')
            '--provider-base-url'
            $ProviderBaseUrl
            '--state-root'
            $StateRoot
        )
        PassThru = $true
        RedirectStandardOutput = $FlowOut
        RedirectStandardError = $FlowErr
    }
    if ($RunningOnWindows) {
        $FlowStart['WindowStyle'] = 'Hidden'
    }
    $Flow = Start-Process @FlowStart
    $FlowDeadline = [DateTime]::UtcNow.AddSeconds(60)
    while (-not $Flow.HasExited) {
        if ($script:CancellationSource.IsCancellationRequested) {
            throw [OperationCanceledException]::new('Synthetic OIDC flow cancelled.')
        }
        if ([DateTime]::UtcNow -ge $FlowDeadline) {
            throw [TimeoutException]::new('Synthetic OIDC flow timed out.')
        }
        Start-Sleep -Milliseconds 100
        $Flow.Refresh()
    }
    if ($Flow.ExitCode -ne 0) {
        $FailureMarker = $null
        if (Test-Path -LiteralPath $FlowOut) {
            $FlowOutput = Get-Item -LiteralPath $FlowOut -Force
            if ($FlowOutput.Length -le 512) {
                $FailureMarkers = @(
                    Get-Content -LiteralPath $FlowOut |
                        Where-Object {
                            $_ -cmatch (
                                '^MOCK_OIDC_OWNER_FLOW=FAIL:' +
                                '[a-z][a-z0-9-]{0,31}:' +
                                '(?:timeout|http|assertion|transport|' +
                                'invalid-data|runtime|internal)$'
                            )
                        }
                )
                if ($FailureMarkers.Count -eq 1) {
                    $FailureMarker = $FailureMarkers[0]
                }
            }
        }
        if ($null -ne $FailureMarker) {
            throw (
                "Synthetic OIDC owner flow failed with exit code " +
                "$($Flow.ExitCode) at $FailureMarker."
            )
        }
        throw "Synthetic OIDC owner flow failed with exit code $($Flow.ExitCode)."
    }
    $Result = (Get-Content -LiteralPath $FlowOut -Raw).Trim()
    if ($Result -cne 'MOCK_OIDC_OWNER_FLOW=PASS') {
        throw 'Synthetic OIDC owner flow did not publish its pass marker.'
    }
}
catch {
    $RunFailure = $_
}
finally {
    try {
        [Environment]::SetEnvironmentVariable(
            'PYTHONPATH',
            $PreviousPythonPath,
            [EnvironmentVariableTarget]::Process
        )
    }
    catch {
        $TeardownFailures.Add('process environment restoration failed')
    }

    $CleanupCancellationSource = [Threading.CancellationTokenSource]::new()
    $script:CancellationSource = $CleanupCancellationSource

    foreach ($ChildProcess in @($Flow, $LoopbackProxy)) {
        if ($null -eq $ChildProcess -or $ChildProcess.HasExited) {
            continue
        }
        try {
            Stop-Process -Id $ChildProcess.Id -Force -ErrorAction Stop
            if (-not $ChildProcess.WaitForExit(5000)) {
                $TeardownFailures.Add(
                    "child process $($ChildProcess.Id) did not stop"
                )
            }
        }
        catch {
            $TeardownFailures.Add(
                "child process $($ChildProcess.Id) cleanup failed"
            )
        }
    }

    if ($ContainerRunAttempted) {
        try {
            Remove-OwnedMockOidcDockerResource `
                -DockerPath $Docker.Source `
                -ResourceKind container `
                -ResourceName $ContainerName `
                -OwnerLabelKey $OwnerLabelKey `
                -OwnerLabelValue $OwnerLabelValue `
                -TimeoutMilliseconds 15000 `
                -CancellationToken $CleanupCancellationSource.Token
        }
        catch {
            $TeardownFailures.Add('synthetic OIDC container cleanup failed')
        }
    }
    if ($NetworkCreateAttempted) {
        try {
            Remove-OwnedMockOidcDockerResource `
                -DockerPath $Docker.Source `
                -ResourceKind network `
                -ResourceName $NetworkName `
                -OwnerLabelKey $OwnerLabelKey `
                -OwnerLabelValue $OwnerLabelValue `
                -TimeoutMilliseconds 15000 `
                -CancellationToken $CleanupCancellationSource.Token
        }
        catch {
            $TeardownFailures.Add('synthetic OIDC network cleanup failed')
        }
    }

    $PortDeadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $Probe = [Net.Sockets.TcpClient]::new()
        try {
            $Connection = $Probe.ConnectAsync('127.0.0.1', $ProviderPort)
            $PortOwned = $Connection.Wait(200) -and $Probe.Connected
        }
        catch {
            $PortOwned = $false
        }
        finally {
            $Probe.Dispose()
        }
        if ($PortOwned) {
            Start-Sleep -Milliseconds 100
        }
    } while ($PortOwned -and [DateTime]::UtcNow -lt $PortDeadline)
    if ($PortOwned) {
        $TeardownFailures.Add(
            'synthetic OIDC loopback port remained owned after teardown'
        )
    }

    if ($CancelHandlerRegistered) {
        try {
            [Console]::remove_CancelKeyPress($CancelHandler)
            $CancelHandlerRegistered = $false
        }
        catch {
            $TeardownFailures.Add('cancellation handler cleanup failed')
        }
    }
    foreach ($CancellationSource in @(
        $RunCancellationSource,
        $CleanupCancellationSource
    )) {
        if ($null -eq $CancellationSource) {
            continue
        }
        try {
            $CancellationSource.Dispose()
        }
        catch {
            $TeardownFailures.Add('cancellation source cleanup failed')
        }
    }
    $script:CancellationSource = $null

    $ResolvedStateRoot = [IO.Path]::GetFullPath($StateRoot)
    if (
        -not [string]::Equals(
            [IO.Path]::GetDirectoryName($ResolvedStateRoot),
            $CanonicalTemp,
            $PathComparison
        ) -or
        -not $ResolvedStateRoot.StartsWith(
            $StateRootPrefix,
            $PathComparison
        )
    ) {
        $TeardownFailures.Add('synthetic OIDC state root was unexpected')
    }
    elseif (Test-Path -LiteralPath $ResolvedStateRoot) {
        try {
            Remove-Item -LiteralPath $ResolvedStateRoot -Recurse -Force
        }
        catch {
            $TeardownFailures.Add('synthetic OIDC state cleanup failed')
        }
    }
    if (Test-Path -LiteralPath $ResolvedStateRoot) {
        $TeardownFailures.Add('synthetic OIDC state remained after cleanup')
    }
}

if ($null -ne $RunFailure) {
    if ($TeardownFailures.Count -gt 0) {
        throw (
            'Synthetic OIDC verification failed and teardown was incomplete: ' +
            ($TeardownFailures -join '; ')
        )
    }
    throw $RunFailure
}
if ($TeardownFailures.Count -gt 0) {
    throw (
        'Synthetic OIDC teardown was incomplete: ' +
        ($TeardownFailures -join '; ')
    )
}
if ($ReceiptMode) {
    Assert-ExactCleanHead -ExpectedHead $CheckedHead
    $ReceiptDestination = Resolve-NewReceiptOutput -OutputPath $ReceiptOutput
    $Receipt = [ordered]@{
        schemaVersion = 1
        receiptContract = 'mock-oidc-owner-flow-v1'
        checkedHead = $CheckedHead
        lockedImageDigest = $ExpectedDigest
        validatorSources = [ordered]@{
            oidcAccessTokensSha256 = (
                Get-FileHash -LiteralPath (
                    Join-Path $ServerRoot 'src/yap_server/auth/oidc_access_tokens.py'
                ) -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            oidcMetadataSha256 = (
                Get-FileHash -LiteralPath (
                    Join-Path $ServerRoot 'src/yap_server/auth/oidc_metadata.py'
                ) -Algorithm SHA256
            ).Hash.ToLowerInvariant()
        }
        ownerFlowSha256 = (
            Get-FileHash -LiteralPath (
                Join-Path $PSScriptRoot 'mock-oidc-owner-flow.py'
            ) -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        teardown = [ordered]@{
            childProcessesStopped = $true
            containerAbsent = $true
            networkAbsent = $true
            loopbackPortReleased = $true
            stateDirectoryRemoved = $true
            cancellationHandlerRemoved = $true
            remainingContainers = 0
            remainingNetworks = 0
            status = 'passed'
        }
        status = 'passed'
    }
    $ReceiptJson = ($Receipt | ConvertTo-Json -Depth 5) + [Environment]::NewLine
    $ReceiptBytes = [Text.UTF8Encoding]::new($false).GetBytes($ReceiptJson)
    if ($ReceiptBytes.Length -gt 4096) {
        throw 'The synthetic OIDC receipt exceeded its public evidence bound.'
    }
    Write-NewPrivateFileAtomically `
        -DestinationPath $ReceiptDestination.Path `
        -Content $ReceiptBytes
}
Write-Output $Result
