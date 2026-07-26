#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath (Join-Path $Repository 'desktop\src-tauri')
try {
    $WindowsPackages = @(
        cargo tree `
            --locked `
            --offline `
            --target x86_64-pc-windows-msvc `
            --prefix none `
            --format '{p}'
    )
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to inspect the locked Windows dependency graph.'
    }
    $WindowsGlibPackages = @(
        $WindowsPackages | Where-Object { $_ -match '^glib v' }
    )
    if ($WindowsGlibPackages.Count -ne 0) {
        throw "glib became reachable on Windows: $($WindowsGlibPackages -join ', ')"
    }
}
finally {
    Pop-Location
}
