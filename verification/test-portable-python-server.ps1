#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'exact-python-runtime.psm1') -Force
$ServerRoot = Join-Path $Repository 'server'
$Runtime = Sync-LockedServerEnvironment `
    -ServerRoot $ServerRoot `
    -WithEvaluation `
    -WithTests

$env:PYTHONPATH = Join-Path $Repository 'server\src'
Push-Location -LiteralPath $ServerRoot
try {
    & $Runtime.Python (Join-Path $PSScriptRoot 'run-portable-server-suite.py')
    if ($LASTEXITCODE -ne 0) {
        throw "The portable Python 3.12 server suite failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
