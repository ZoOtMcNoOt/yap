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
if (
    $Lock.schemaVersion -ne 1 -or
    $Lock.provider -cne 'navikt/mock-oauth2-server' -or
    $Lock.version -cne '5.0.2' -or
    $Lock.license -cne 'MIT' -or
    $Lock.manifestDigest -cne $ExpectedDigest -or
    $Lock.reference -cne "ghcr.io/navikt/mock-oauth2-server:5.0.2@$ExpectedDigest"
) {
    throw 'The synthetic OIDC provider lock is invalid.'
}
$ImageReference = [string]$Lock.reference
$Docker = Get-Command docker -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
Import-Module (Join-Path $PSScriptRoot 'mock-oidc-docker-owner.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'exact-python-runtime.psm1') -Force
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

    $PullResult = Invoke-MockOidcDockerCommand `
        -DockerPath $Docker.Source `
        -Arguments @('pull', $ImageReference) `
        -TimeoutMilliseconds 120000 `
        -CancellationToken $RunCancellationSource.Token `
        -Operation 'synthetic OIDC image pull'
    if ($PullResult.ExitCode -ne 0) {
        throw 'Synthetic OIDC image pull failed.'
    }

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

    $ContainerRunAttempted = $true
    Invoke-MockOidcDockerResourceCreate `
        -DockerPath $Docker.Source `
        -Arguments @(
            'run',
            '--detach',
            '--rm',
            '--pull',
            'never',
            '--name',
            $ContainerName,
            '--label',
            "$OwnerLabelKey=$OwnerLabelValue",
            '--hostname',
            'localhost',
            '--network',
            $NetworkName,
            '--publish',
            "127.0.0.1:${ProviderPort}:8080",
            '--read-only',
            '--tmpfs',
            '/tmp:rw,noexec,nosuid,size=32m',
            '--cap-drop',
            'ALL',
            '--security-opt',
            'no-new-privileges=true',
            '--memory',
            '512m',
            '--cpus',
            '1',
            '--env',
            'SERVER_HOSTNAME=0.0.0.0',
            '--env',
            'JSON_CONFIG',
            $ImageReference
        ) `
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
        $ConfiguredImage -cne $ImageReference
    ) {
        throw 'Synthetic OIDC container did not retain the locked image reference.'
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

    foreach ($ChildProcess in @($Flow)) {
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
    $TemporaryReceipt = Join-Path $ReceiptDestination.Parent (
        ".$([IO.Path]::GetFileName($ReceiptDestination.Path))." +
        "$([guid]::NewGuid().ToString('N')).tmp"
    )
    try {
        $ReceiptStream = [IO.File]::Open(
            $TemporaryReceipt,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        try {
            $ReceiptStream.Write($ReceiptBytes, 0, $ReceiptBytes.Length)
            $ReceiptStream.Flush($true)
        }
        finally {
            $ReceiptStream.Dispose()
        }
        [IO.File]::Move(
            $TemporaryReceipt,
            $ReceiptDestination.Path,
            $false
        )
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryReceipt) {
            Remove-Item -LiteralPath $TemporaryReceipt -Force
        }
    }
}
Write-Output $Result
