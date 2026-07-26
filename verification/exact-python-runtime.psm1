#requires -Version 7.4
#requires -PSEdition Core

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-ExactPython312 {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $Version = (& $Path -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null)
    return $LASTEXITCODE -eq 0 -and $Version.Trim() -ceq '3.12'
}

function Resolve-ExactPython312 {
    $Candidates = [Collections.Generic.List[string]]::new()
    $Uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Uv) {
        $PreviousDownloads = $env:UV_PYTHON_DOWNLOADS
        try {
            $env:UV_PYTHON_DOWNLOADS = 'never'
            $Candidate = (& $Uv.Source python find 3.12 2>$null)
            if ($LASTEXITCODE -eq 0 -and $Candidate) {
                $Candidates.Add($Candidate.Trim())
            }
        }
        finally {
            $env:UV_PYTHON_DOWNLOADS = $PreviousDownloads
        }
    }

    $Launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Launcher) {
        $Candidate = (& $Launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $Candidate) {
            $Candidates.Add($Candidate.Trim())
        }
    }

    $Ambient = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Ambient) {
        $Candidates.Add($Ambient.Source)
    }

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if (Test-ExactPython312 -Path $Candidate) {
            return [IO.Path]::GetFullPath($Candidate)
        }
    }
    throw 'No installed, network-free Python 3.12 runtime was found.'
}

function Resolve-UvExecutable {
    $Uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $Uv) {
        throw 'The locked server gate requires the uv executable.'
    }
    return $Uv.Source
}

function Sync-LockedServerEnvironment {
    param(
        [Parameter(Mandatory)][string]$ServerRoot,
        [switch]$WithEvaluation,
        [switch]$WithTests
    )

    $ServerDirectory = Get-Item -LiteralPath $ServerRoot -Force
    if (-not $ServerDirectory.PSIsContainer -or $ServerDirectory.LinkType) {
        throw 'The server root must be a real directory.'
    }
    $LockPath = Join-Path $ServerDirectory.FullName 'uv.lock'
    $ProjectPath = Join-Path $ServerDirectory.FullName 'pyproject.toml'
    foreach ($Required in @($LockPath, $ProjectPath)) {
        $Item = Get-Item -LiteralPath $Required -Force
        if ($Item.PSIsContainer -or $Item.LinkType) {
            throw 'The locked server environment requires regular project and lock files.'
        }
    }

    $Uv = Resolve-UvExecutable
    $BasePython = Resolve-ExactPython312
    $Arguments = @(
        'sync'
        '--offline'
        '--locked'
        '--exact'
        '--python'
        $BasePython
        '--no-python-downloads'
    )
    if ($WithEvaluation) {
        $Arguments += @('--extra', 'evaluation')
    }
    if ($WithTests) {
        $Arguments += @('--extra', 'test')
    }
    Push-Location -LiteralPath $ServerDirectory.FullName
    try {
        & $Uv @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "The offline locked uv sync failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    $VirtualEnvironmentRoot = Join-Path $ServerDirectory.FullName '.venv'
    $Python = if ([OperatingSystem]::IsWindows()) {
        Join-Path (Join-Path $VirtualEnvironmentRoot 'Scripts') 'python.exe'
    }
    else {
        Join-Path (Join-Path $VirtualEnvironmentRoot 'bin') 'python'
    }
    if (-not (Test-ExactPython312 -Path $Python)) {
        throw 'The locked uv environment did not produce an exact Python 3.12 interpreter.'
    }
    return [pscustomobject]@{
        LockSha256 = (
            Get-FileHash -LiteralPath $LockPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        Python = [IO.Path]::GetFullPath($Python)
        Uv = $Uv
    }
}

Export-ModuleMember `
    -Function Resolve-ExactPython312, Resolve-UvExecutable, Sync-LockedServerEnvironment
