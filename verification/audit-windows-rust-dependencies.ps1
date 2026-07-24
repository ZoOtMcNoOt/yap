#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
$Version = '0.22.2'
$ExpectedSha256 = '0a7316540862c13d954f648917ceacca593747baed6eec180fafa590be2710ab'
$ArchiveName = "cargo-audit-x86_64-pc-windows-msvc-v$Version.zip"
$Url = "https://github.com/RustSec/rustsec/releases/download/cargo-audit/v$Version/$ArchiveName"
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$WorkRoot = [IO.Path]::GetFullPath(
    (Join-Path $TempRoot "yap-cargo-audit-$([Guid]::NewGuid().ToString('N'))")
)
$RelativeWorkRoot = [IO.Path]::GetRelativePath($TempRoot, $WorkRoot)
if (
    [IO.Path]::IsPathRooted($RelativeWorkRoot) -or
    $RelativeWorkRoot -eq '..' -or
    $RelativeWorkRoot.StartsWith("..$([IO.Path]::DirectorySeparatorChar)")
) {
    throw 'The cargo-audit work directory escaped the operating-system temp root.'
}

New-Item -ItemType Directory -Path $WorkRoot | Out-Null
try {
    $Archive = Join-Path $WorkRoot $ArchiveName
    $ExtractRoot = Join-Path $WorkRoot 'extracted'
    Invoke-WebRequest -Uri $Url -OutFile $Archive
    $ActualSha256 = (
        Get-FileHash -LiteralPath $Archive -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($ActualSha256 -cne $ExpectedSha256) {
        throw 'The pinned cargo-audit archive hash does not match.'
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractRoot
    $CargoAudit = Join-Path `
        $ExtractRoot `
        "cargo-audit-x86_64-pc-windows-msvc-v$Version\cargo-audit.exe"
    $ActualVersion = (& $CargoAudit --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $ActualVersion -cne "cargo-audit $Version") {
        throw "The pinned cargo-audit executable has an unexpected version: '$ActualVersion'."
    }

    Push-Location -LiteralPath (Join-Path $Repository 'desktop\src-tauri')
    try {
        & $CargoAudit audit --target-os windows --target-arch x86_64
        if ($LASTEXITCODE -ne 0) {
            throw "cargo-audit failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
}
