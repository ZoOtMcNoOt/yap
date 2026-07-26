#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$StateRoot = [Environment]::GetEnvironmentVariable(
    'YAP_FAKE_DOCKER_STATE_ROOT',
    [EnvironmentVariableTarget]::Process
)
$Mode = [Environment]::GetEnvironmentVariable(
    'YAP_FAKE_DOCKER_MODE',
    [EnvironmentVariableTarget]::Process
)
if (
    [string]::IsNullOrWhiteSpace($StateRoot) -or
    -not [IO.Path]::IsPathFullyQualified($StateRoot)
) {
    throw 'Fake Docker state root is invalid.'
}
$StateRoot = [IO.Path]::GetFullPath($StateRoot)
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null

$Arguments = @($args)
if ($Arguments.Count -lt 2) {
    exit 2
}

function Resolve-ResourceState {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('container', 'network')]
        [string]$ResourceKind,

        [Parameter(Mandatory)]
        [string]$ResourceName
    )

    if ($ResourceName -cnotmatch '^[a-z0-9][a-z0-9_.-]{0,127}$') {
        throw 'Fake Docker resource name is invalid.'
    }
    return Join-Path $StateRoot "$ResourceKind-$ResourceName"
}

function Write-Trace {
    param(
        [Parameter(Mandatory)]
        [string]$Value
    )

    Add-Content -LiteralPath (Join-Path $StateRoot 'trace.log') -Value $Value
}

$Group = $Arguments[0]
$Action = $Arguments[1]
if ($Group -ceq 'network' -and $Action -ceq 'create') {
    $Name = $Arguments[-1]
    Set-Content -LiteralPath (
        Resolve-ResourceState -ResourceKind network -ResourceName $Name
    ) -Value 'mock-oidc'
    Write-Trace -Value 'network create'
    if ($Mode -ceq 'malformed-network-create') {
        Write-Output 'successful creation with malformed output'
    }
    else {
        Write-Output ('a' * 64)
    }
    exit 0
}

if ($Group -ceq 'run') {
    $NameIndex = [Array]::IndexOf($Arguments, '--name')
    if ($NameIndex -lt 0 -or $NameIndex + 1 -ge $Arguments.Count) {
        exit 2
    }
    $Name = $Arguments[$NameIndex + 1]
    Set-Content -LiteralPath (
        Resolve-ResourceState -ResourceKind container -ResourceName $Name
    ) -Value 'mock-oidc'
    Write-Trace -Value 'container run'
    if ($Mode -ceq 'hang-container-run') {
        while ($true) {
            Start-Sleep -Seconds 1
        }
    }
    Write-Output ('b' * 64)
    exit 0
}

if (
    $Group -in @('container', 'network') -and
    $Action -ceq 'inspect'
) {
    $Name = $Arguments[-1]
    $State = Resolve-ResourceState -ResourceKind $Group -ResourceName $Name
    Write-Trace -Value "$Group inspect"
    if (-not (Test-Path -LiteralPath $State -PathType Leaf)) {
        exit 1
    }
    Write-Output (Get-Content -LiteralPath $State -Raw).Trim()
    exit 0
}

if (
    ($Group -ceq 'container' -and $Action -ceq 'rm') -or
    ($Group -ceq 'network' -and $Action -ceq 'rm')
) {
    $Name = $Arguments[-1]
    $State = Resolve-ResourceState -ResourceKind $Group -ResourceName $Name
    Write-Trace -Value "$Group rm"
    if (-not (Test-Path -LiteralPath $State -PathType Leaf)) {
        exit 1
    }
    Remove-Item -LiteralPath $State -Force
    Write-Output $Name
    exit 0
}

if (
    $Group -in @('container', 'network') -and
    $Action -ceq 'ls'
) {
    Write-Trace -Value "$Group ls"
    foreach ($State in Get-ChildItem -LiteralPath $StateRoot -File) {
        $Prefix = "$Group-"
        if ($State.Name.StartsWith($Prefix, [StringComparison]::Ordinal)) {
            Write-Output $State.Name.Substring($Prefix.Length)
        }
    }
    exit 0
}

exit 2
