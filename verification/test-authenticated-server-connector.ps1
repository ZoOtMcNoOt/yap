#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repository = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'exact-python-runtime.psm1') -Force
$ServerRoot = Join-Path $Repository 'server'
$Runtime = Sync-LockedServerEnvironment -ServerRoot $ServerRoot
$Port = 18766

function Test-LoopbackListener {
    $Client = [Net.Sockets.TcpClient]::new()
    try {
        $Connection = $Client.ConnectAsync('127.0.0.1', $Port)
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
    throw "The authenticated connector gate requires port $Port to be unowned."
}

$CanonicalTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$StateRoot = [IO.Path]::GetFullPath(
    (Join-Path $CanonicalTemp "yap-authenticated-connector-$([guid]::NewGuid().ToString('N'))")
)
if ([IO.Path]::GetDirectoryName($StateRoot) -cne $CanonicalTemp) {
    throw 'The authenticated connector state root escaped the temporary directory.'
}
New-Item -ItemType Directory -Path $StateRoot | Out-Null
$TokenFile = Join-Path $StateRoot 'access-token.txt'

$PreviousPythonPath = [Environment]::GetEnvironmentVariable(
    'PYTHONPATH',
    [EnvironmentVariableTarget]::Process
)
$env:PYTHONPATH = Join-Path $Repository 'server\src'
$Server = Start-Process `
    -FilePath $Runtime.Python `
    -ArgumentList @(
        (Join-Path $PSScriptRoot 'authenticated-connector-server.py')
        '--port'
        [string]$Port
        '--state-root'
        $StateRoot
        '--token-file'
        $TokenFile
    ) `
    -PassThru `
    -WindowStyle Hidden

try {
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        if (
            (Test-Path -LiteralPath $TokenFile -PathType Leaf) -and
            (Test-LoopbackListener)
        ) {
            $Ready = $true
            break
        }
        $Server.Refresh()
        if ($Server.HasExited) {
            throw 'The authenticated Python server exited before connector verification.'
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $Ready) {
        throw 'The authenticated Python server did not become ready.'
    }

    $env:YAP_TEST_AUTH_SERVER_URL = "http://127.0.0.1:$Port"
    $env:YAP_TEST_AUTH_SERVER_TOKEN = (
        Get-Content -LiteralPath $TokenFile -Raw
    ).Trim()
    if (-not $env:YAP_TEST_AUTH_SERVER_TOKEN) {
        throw 'The synthetic access token was unavailable.'
    }
    Push-Location -LiteralPath $Repository
    try {
        & cargo test `
            --locked `
            --manifest-path '.\desktop\src-tauri\Cargo.toml' `
            'server_connector::client::tests::python_authenticated_server_accepts_signed_bearer_when_provided' `
            --lib
        if ($LASTEXITCODE -ne 0) {
            throw "The authenticated server connector failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    [Environment]::SetEnvironmentVariable(
        'PYTHONPATH',
        $PreviousPythonPath,
        [EnvironmentVariableTarget]::Process
    )
    Remove-Item Env:YAP_TEST_AUTH_SERVER_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:YAP_TEST_AUTH_SERVER_URL -ErrorAction SilentlyContinue
    Stop-Process -Id $Server.Id -Force -ErrorAction SilentlyContinue
    $Server.WaitForExit(5000) | Out-Null
    $Deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (Test-LoopbackListener) {
        if ([DateTime]::UtcNow -ge $Deadline) {
            throw "Port $Port remained owned after authenticated connector teardown."
        }
        Start-Sleep -Milliseconds 100
    }
    $ResolvedStateRoot = [IO.Path]::GetFullPath($StateRoot)
    if (
        [IO.Path]::GetDirectoryName($ResolvedStateRoot) -cne $CanonicalTemp -or
        -not $ResolvedStateRoot.StartsWith(
            "$CanonicalTemp\yap-authenticated-connector-",
            [StringComparison]::Ordinal
        )
    ) {
        throw 'Refusing to remove an unexpected authenticated connector state root.'
    }
    Remove-Item -LiteralPath $ResolvedStateRoot -Recurse -Force
}
