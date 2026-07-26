#requires -Version 7.4
#requires -PSEdition Core

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\..\..")
)
$project = Join-Path $repositoryRoot "desktop\native\Yap.Identity.Broker\Yap.Identity.Broker.csproj"
$publishDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot ".tools\identity-broker-publish")
)
$binaryDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $repositoryRoot "desktop\src-tauri\binaries")
)
$destination = Join-Path $binaryDirectory "yap-identity-broker-x86_64-pc-windows-msvc.exe"
$temporaryDestination = "$destination.part"

foreach ($path in @($publishDirectory, $binaryDirectory)) {
    if (-not $path.StartsWith("$repositoryRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Identity broker output escaped the repository workspace."
    }
}

$repositoryDotnet = Join-Path $repositoryRoot ".tools\dotnet\dotnet.exe"
$dotnetCandidates = @()
if (Test-Path -LiteralPath $repositoryDotnet -PathType Leaf) {
    $dotnetCandidates += $repositoryDotnet
}
$pathDotnet = Get-Command dotnet.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty Source
if ($pathDotnet) {
    $dotnetCandidates += $pathDotnet
}
$dotnet = $dotnetCandidates |
    Select-Object -Unique |
    Where-Object {
        Push-Location -LiteralPath (Join-Path $repositoryRoot 'desktop\native')
        try {
            $candidateVersion = (& $_ --version 2>$null | Out-String).Trim()
        }
        finally {
            Pop-Location
        }
        $LASTEXITCODE -eq 0 -and $candidateVersion -ceq "8.0.423"
    } |
    Select-Object -First 1
if (-not $dotnet) {
    throw "Yap identity broker requires the pinned .NET SDK 8.0.423."
}

if (Test-Path -LiteralPath $publishDirectory) {
    Remove-Item -LiteralPath $publishDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path $publishDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null

& $dotnet publish $project `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    -p:RestoreLockedMode=true `
    --nologo `
    --output $publishDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Identity broker publish failed."
}

$published = Join-Path $publishDirectory "yap-identity-broker.exe"
if (-not (Test-Path -LiteralPath $published -PathType Leaf)) {
    throw "Identity broker publish did not produce the expected executable."
}
$publishedFiles = @(Get-ChildItem -LiteralPath $publishDirectory -File)
if ($publishedFiles.Count -ne 1 -or $publishedFiles[0].Name -cne "yap-identity-broker.exe") {
    throw "Identity broker publish must embed its native WAM runtime in one executable."
}

$smokeRequest = [ordered]@{
    schemaVersion = 1
    requestId = "packaging-smoke"
    operation = "getStatus"
    tenantId = "invalid"
    clientId = "invalid"
    apiScope = "invalid"
    parentWindowHandle = $null
} | ConvertTo-Json -Compress
$smokeResponse = ($smokeRequest | & $published | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Identity broker protocol smoke failed."
}
$smoke = $smokeResponse | ConvertFrom-Json
if (
    [int]$smoke.schemaVersion -ne 1 -or
    $smoke.requestId -cne "packaging-smoke" -or
    $smoke.outcome -cne "invalidRequest" -or
    $smoke.errorCode -cne "INVALID_REQUEST" -or
    $null -ne $smoke.accessToken -or
    $null -ne $smoke.accountId
) {
    throw "Identity broker returned an incompatible protocol response."
}

Remove-Item -LiteralPath $temporaryDestination -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $published -Destination $temporaryDestination
Move-Item -LiteralPath $temporaryDestination -Destination $destination -Force
