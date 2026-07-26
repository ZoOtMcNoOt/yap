#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
$NativeRoot = Join-Path $Repository 'desktop\native'
$Project = Join-Path $NativeRoot 'Yap.Identity.Broker\Yap.Identity.Broker.csproj'
$GlobalJson = Get-Content -LiteralPath (Join-Path $NativeRoot 'global.json') -Raw |
    ConvertFrom-Json
$ExpectedVersion = [string]$GlobalJson.sdk.version
if ($ExpectedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw 'The pinned .NET SDK version is invalid.'
}

$ExecutableName = if ($IsWindows) { 'dotnet.exe' } else { 'dotnet' }
$Candidates = @(
    (Join-Path $Repository ".tools\dotnet\$ExecutableName")
    $ExecutableName
)
$Dotnet = $null
foreach ($Candidate in $Candidates | Select-Object -Unique) {
    if ([IO.Path]::IsPathRooted($Candidate) -and -not (
        Test-Path -LiteralPath $Candidate -PathType Leaf
    )) {
        continue
    }
    Push-Location -LiteralPath $NativeRoot
    try {
        $Version = (& $Candidate --version 2>$null | Out-String).Trim()
    }
    catch {
        $Version = ''
    }
    finally {
        Pop-Location
    }
    if ($LASTEXITCODE -eq 0 -and $Version -ceq $ExpectedVersion) {
        $Dotnet = $Candidate
        break
    }
}
if (-not $Dotnet) {
    throw "The NuGet audit requires the pinned .NET SDK $ExpectedVersion."
}

Push-Location -LiteralPath $NativeRoot
try {
    & $Dotnet restore $Project -p:RestoreLockedMode=true --nologo | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Locked NuGet restore failed with exit code $LASTEXITCODE."
    }
    $AuditOutput = & $Dotnet list $Project package `
        --vulnerable `
        --include-transitive `
        --format json
    if ($LASTEXITCODE -ne 0) {
        throw "NuGet advisory audit failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$Audit = ($AuditOutput -join [Environment]::NewLine) | ConvertFrom-Json
if ([int]$Audit.version -ne 1) {
    throw 'The NuGet advisory audit returned an unsupported schema.'
}
$Vulnerable = @(@(
    foreach ($ProjectResult in @($Audit.projects)) {
        $Frameworks = $ProjectResult.PSObject.Properties['frameworks']
        if ($null -eq $Frameworks) {
            continue
        }
        foreach ($Framework in @($Frameworks.Value)) {
            $TopLevel = $Framework.PSObject.Properties['topLevelPackages']
            $Transitive = $Framework.PSObject.Properties['transitivePackages']
            $Packages = @()
            if ($null -ne $TopLevel) {
                $Packages += @($TopLevel.Value)
            }
            if ($null -ne $Transitive) {
                $Packages += @($Transitive.Value)
            }
            foreach ($Package in $Packages) {
                $Vulnerabilities = $Package.PSObject.Properties['vulnerabilities']
                if (
                    $null -ne $Vulnerabilities -and
                    @($Vulnerabilities.Value).Count -gt 0
                ) {
                    [string]$Package.id
                }
            }
        }
    }
) | Sort-Object -Unique)
if ($Vulnerable.Count -gt 0) {
    throw "NuGet advisory audit found vulnerable packages: $($Vulnerable -join ', ')."
}

Write-Output "NuGet advisory audit passed with .NET SDK $ExpectedVersion."
