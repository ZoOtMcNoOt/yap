#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'exact-python-runtime.psm1') -Force
$ServerRoot = Join-Path $Repository 'server'
$Runtime = Sync-LockedServerEnvironment -ServerRoot $ServerRoot
$BasePythonPath = (& $Runtime.Python -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $BasePythonPath -PathType Leaf)) {
    throw 'The locked Python environment did not expose its base interpreter.'
}
$BasePythonPath = [IO.Path]::GetFullPath($BasePythonPath)

function Test-LoopbackListener {
    $Client = [Net.Sockets.TcpClient]::new()
    try {
        $Connection = $Client.ConnectAsync('127.0.0.1', 18765)
        return $Connection.Wait(500) -and $Client.Connected
    }
    catch {
        return $false
    }
    finally {
        $Client.Dispose()
    }
}

if (Test-LoopbackListener) {
    throw 'The server-connector gate requires port 18765 to be unowned before launch.'
}

$env:PYTHONPATH = Join-Path $Repository 'server\src'
$env:YAP_SERVER_HOST = '127.0.0.1'
$env:YAP_SERVER_PORT = '18765'
# This gate owns the unauthenticated development-loopback integration. The
# ordinary server default intentionally fails closed when no identity provider
# is configured, so relying on that default would test the sign-in-required
# contract instead of this connector path.
$env:YAP_SERVER_CONFIGURATION = 'development'
$env:YAP_AUTH_MODE = 'development_loopback'
$Server = Start-Process `
    -FilePath $Runtime.Python `
    -ArgumentList '-m', 'yap_server' `
    -PassThru `
    -WindowStyle Hidden

try {
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
        try {
            Invoke-RestMethod 'http://127.0.0.1:18765/v1/health' | Out-Null
            $Ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $Ready) {
        throw 'The local Yap server did not become ready for the connector contract.'
    }
    $Server.Refresh()
    if ($Server.HasExited) {
        throw 'The launched Python 3.12 server exited before connector verification.'
    }
    $Netstat = @(& netstat.exe -ano -p tcp)
    if ($LASTEXITCODE -ne 0) {
        throw 'Windows could not inspect the loopback listener ownership table.'
    }
    $OwnedListenerPids = @(
        foreach ($Line in $Netstat) {
            if (
                $Line -match (
                    '^\s*TCP\s+127\.0\.0\.1:18765\s+\S+\s+LISTENING\s+(\d+)\s*$'
                )
            ) {
                [int]$Matches[1]
            }
        }
    )
    if ($OwnedListenerPids.Count -ne 1) {
        $Observed = $OwnedListenerPids -join ','
        throw (
            "The healthy loopback listener does not have one owner. " +
            "Observed listener PIDs: $Observed."
        )
    }
    $ListenerProcess = Get-Process -Id $OwnedListenerPids[0] -ErrorAction Stop
    $DirectOwner = $ListenerProcess.Id -eq $Server.Id
    $LockedBaseOwner = (
        [string]::Equals(
            [IO.Path]::GetFullPath($ListenerProcess.Path),
            $BasePythonPath,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        $ListenerProcess.StartTime.ToUniversalTime() -ge
            $Server.StartTime.ToUniversalTime().AddSeconds(-1)
    )
    if (-not $DirectOwner -and -not $LockedBaseOwner) {
        throw 'The healthy listener is not owned by the launched locked Python runtime.'
    }
    $env:YAP_TEST_SERVER_URL = 'http://127.0.0.1:18765'
    Push-Location -LiteralPath $Repository
    try {
        & cargo test `
            --locked `
            --manifest-path '.\desktop\src-tauri\Cargo.toml' `
            --test server_connector
        if ($LASTEXITCODE -ne 0) {
            throw "The server-connector integration failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Stop-Process -Id $Server.Id -Force -ErrorAction SilentlyContinue
    $Server.WaitForExit(5000) | Out-Null
    $Server.Refresh()
    if (-not $Server.HasExited) {
        throw 'The owned Python server did not exit during connector teardown.'
    }
    $Deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (Test-LoopbackListener) {
        if ([DateTime]::UtcNow -ge $Deadline) {
            throw 'Port 18765 remained owned after connector teardown.'
        }
        Start-Sleep -Milliseconds 100
    }
}
