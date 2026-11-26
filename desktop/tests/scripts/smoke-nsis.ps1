#requires -Version 7.4
#requires -PSEdition Core

param(
  [string]$BundleDirectory = "",
  [switch]$CheckOfflineHistory,
  [string]$ExpectedInstallerSha256 = "",
  [ValidateRange(1, 900)]
  [int]$ProcessTimeoutSeconds = 180,
  [ValidateRange(1, 120)]
  [int]$LaunchTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $IsWindows) {
  throw "The NSIS lifecycle smoke requires Windows."
}

$isHostedDisposable =
  $env:GITHUB_ACTIONS -ceq "true" -and
  $env:RUNNER_ENVIRONMENT -ceq "github-hosted"
$isExplicitDisposable = $env:YAP_DISPOSABLE_WINDOWS -ceq "1"
if (-not ($isHostedDisposable -or $isExplicitDisposable)) {
  throw "The stock NSIS lifecycle smoke may run only on a GitHub-hosted runner or an explicitly disposable Windows environment (YAP_DISPOSABLE_WINDOWS=1)."
}

$desktopRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($BundleDirectory)) {
  $BundleDirectory = Join-Path $desktopRoot "src-tauri\target\release\bundle\nsis"
}
$BundleDirectory = [System.IO.Path]::GetFullPath($BundleDirectory)

$installers = @(Get-ChildItem -LiteralPath $BundleDirectory -Filter "*-setup.exe" -File)
if ($installers.Count -ne 1) {
  throw "Expected exactly one NSIS installer in $BundleDirectory; found $($installers.Count)."
}
$installer = $installers[0]
$beforeSha256 = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
$normalizedExpectedSha256 = $ExpectedInstallerSha256.Trim().ToUpperInvariant()
if ($normalizedExpectedSha256) {
  if ($normalizedExpectedSha256 -notmatch "^[0-9A-F]{64}$") {
    throw "ExpectedInstallerSha256 must be a 64-character hexadecimal SHA-256 value."
  }
  if ($beforeSha256 -cne $normalizedExpectedSha256) {
    throw "The installer SHA-256 does not match the expected artifact."
  }
}

$appDataRoot = Join-Path `
  ([Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)) `
  "com.mcnatg1.yap"
$expectedInstallLocation = Join-Path `
  ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) `
  "Yap"
$productRegistryPath = "HKCU:\Software\mcnatg1\Yap"
$uninstallRegistryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Yap"
foreach ($path in @(
    $appDataRoot,
    $expectedInstallLocation,
    $productRegistryPath,
    $uninstallRegistryPath
  )) {
  if (Test-Path -LiteralPath $path) {
    throw "The disposable Windows environment is not clean: $path already exists."
  }
}

$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $python -c "import sqlite3, sys; sys.exit(sys.version_info.major != 3)"
if ($LASTEXITCODE -ne 0) { throw "The recording preservation check requires Python 3 with SQLite." }

function Invoke-BoundedProcess {
  param(
    [Parameter(Mandatory)]
    [string]$FilePath,
    [string[]]$ArgumentList = @(),
    [Parameter(Mandatory)]
    [string]$Label,
    [int]$TimeoutSeconds = $ProcessTimeoutSeconds
  )

  $arguments = @{}
  if ($ArgumentList.Count -gt 0) { $arguments.ArgumentList = $ArgumentList }
  $process = Start-Process -FilePath $FilePath @arguments -NoNewWindow -PassThru
  try {
    $timeoutMilliseconds = [int][TimeSpan]::FromSeconds($TimeoutSeconds).TotalMilliseconds
    if (-not $process.WaitForExit($timeoutMilliseconds)) {
      $process.Kill($true)
      if (-not $process.WaitForExit(10000)) {
        throw "$Label timed out and its process tree could not be reaped."
      }
      throw "$Label exceeded the $TimeoutSeconds second deadline."
    }
    if ($process.ExitCode -ne 0) {
      throw "$Label failed with exit code $($process.ExitCode)."
    }
  } finally {
    if (-not $process.HasExited) {
      $process.Kill($true)
      $null = $process.WaitForExit(10000)
    }
    $process.Dispose()
  }
}

function Wait-ForPathAbsence {
  param(
    [Parameter(Mandatory)]
    [string[]]$LiteralPaths,
    [Parameter(Mandatory)]
    [string]$Label,
    [int]$TimeoutSeconds = $ProcessTimeoutSeconds
  )

  $timer = [Diagnostics.Stopwatch]::StartNew()
  while ($true) {
    $remainingPaths = @($LiteralPaths | Where-Object { Test-Path -LiteralPath $_ })
    if ($remainingPaths.Count -eq 0) {
      return
    }
    if ($timer.Elapsed.TotalSeconds -ge $ProcessTimeoutSeconds) {
      throw "$Label did not converge within $ProcessTimeoutSeconds seconds. Remaining paths: $($remainingPaths -join ', ')"
    }
    Start-Sleep -Milliseconds 100
  }
}

Invoke-BoundedProcess -FilePath $installer.FullName -ArgumentList @("/S") -Label "Stock NSIS install"

if (-not (Test-Path -LiteralPath $uninstallRegistryPath)) {
  throw "Stock NSIS install did not publish its uninstall registry entry."
}
$installed = Get-ItemProperty -LiteralPath $uninstallRegistryPath
$installLocation = ([string]$installed.InstallLocation).Trim('"')
$mainBinaryName = [string]$installed.MainBinaryName
if ([string]::IsNullOrWhiteSpace($installLocation) -or [string]::IsNullOrWhiteSpace($mainBinaryName)) {
  throw "The stock NSIS registry entry is missing InstallLocation or MainBinaryName."
}
$installLocation = [System.IO.Path]::GetFullPath($installLocation)
if ($installLocation -ine [System.IO.Path]::GetFullPath($expectedInstallLocation)) {
  throw "Stock NSIS installed to an unexpected location: $installLocation"
}
$appExecutable = Join-Path $installLocation $mainBinaryName
$uninstaller = Join-Path $installLocation "uninstall.exe"
foreach ($path in @($appExecutable, $uninstaller)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Stock NSIS install did not create $path."
  }
}


Add-Type -Path (Join-Path $PSScriptRoot "InstalledWorkspace.cs")
function Get-AppStartCount([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
  return @(Select-String -LiteralPath $Path -Pattern '^\d+ app start$').Count
}

function Test-InstalledWorkspace {
  param([switch]$ReadHistory)
  $registeredVersion = Get-ItemPropertyValue -LiteralPath $uninstallRegistryPath -Name DisplayVersion
  $evidence = & (Join-Path $PSScriptRoot "get-installed-package-evidence.ps1") -InstallLocation $installLocation -RegisteredVersion $registeredVersion
  $logPath = Join-Path $appDataRoot "logs\yap.log"
  $previousStarts = Get-AppStartCount $logPath
  $appProcess = Start-Process -FilePath $appExecutable -PassThru
  try {
    $launchTimer = [Diagnostics.Stopwatch]::StartNew()
    while ((Get-AppStartCount $logPath) -le $previousStarts) {
      if ($appProcess.HasExited) {
        throw "The installed Yap process exited before creating its canonical Tauri app-data log."
      }
      if ($launchTimer.Elapsed.TotalSeconds -ge $LaunchTimeoutSeconds) {
        throw "Installed Yap did not record a new startup in $logPath within $LaunchTimeoutSeconds seconds."
      }
      Start-Sleep -Milliseconds 100
    }
    $window = [InstalledWorkspace]::Find($appProcess.Id, $LaunchTimeoutSeconds)
    if ($CheckOfflineHistory) {
      $browserTimer = [Diagnostics.Stopwatch]::StartNew()
      do {
        $children = @(Get-CimInstance Win32_Process -Filter "Name = 'msedgewebview2.exe'" | Where-Object ParentProcessId -eq $appProcess.Id)
        $browserPaths = @($children | ForEach-Object ExecutablePath | Where-Object { $_ } | Sort-Object -Unique)
        if ($browserPaths.Count) { break }
        Start-Sleep -Milliseconds 150
      } while ($browserTimer.Elapsed.TotalSeconds -lt $LaunchTimeoutSeconds)
      if ($browserPaths.Count -eq 0) { throw "The installed app did not own an identifiable WebView2 browser." }
      $evidence.browserExecutables = $browserPaths
    }
    if ($ReadHistory) {
      foreach ($browserPath in $browserPaths) {
        if ($browserPath -notin $firstInstall.browserExecutables) { throw "The reinstalled app used a different WebView2 executable." }
      }
      $reader = Join-Path $PSScriptRoot "read-installed-history.ps1"
      $reference = Join-Path $desktopRoot "../verification/fixtures/package-profile/local-dictation/live-s-package-dictation.txt"
      Invoke-BoundedProcess -FilePath "$env:SystemRoot/System32/WindowsPowerShell/v1.0/powershell.exe" -ArgumentList @(
        "-NoProfile", "-NonInteractive", "-STA", "-File", "`"$reader`"", "-WindowHandle", $window.ToInt64(), "-ReferenceFile", "`"$reference`""
      ) -Label "Read the reinstalled transcript through Windows UI Automation"
    }
    [InstalledWorkspace]::Minimize($window, $LaunchTimeoutSeconds)
    Invoke-BoundedProcess -FilePath $appExecutable -TimeoutSeconds $LaunchTimeoutSeconds -Label "Second launch with minimized workspace"
    [InstalledWorkspace]::WaitForRestore($window, $appProcess.Id, $LaunchTimeoutSeconds)
    [InstalledWorkspace]::CloseToTray($window, $LaunchTimeoutSeconds)
    Invoke-BoundedProcess -FilePath $appExecutable -TimeoutSeconds $LaunchTimeoutSeconds -Label "Second launch after close to tray"
    [InstalledWorkspace]::WaitForRestore($window, $appProcess.Id, $LaunchTimeoutSeconds)
  } catch {
    if (Test-Path -LiteralPath $logPath) {
      Get-Content -LiteralPath $logPath -Tail 70 | Where-Object { $_ -match 'single instance:| app start$|panic:|startup failed' } | ForEach-Object { Write-Host $_ }
    }
    throw
  } finally {
    if (-not $appProcess.HasExited) {
      $appProcess.Kill($true)
      if (-not $appProcess.WaitForExit(10000)) {
        throw "The installed Yap process tree could not be reaped."
      }
    }
    $appProcess.Dispose()
  }
  return $evidence
}

$profileCheck = Join-Path $desktopRoot "../verification/package-profile.py"
function Test-PackageProfile([string]$Action) {
  & $python $profileCheck $Action $appDataRoot | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "Installed profile check failed during $Action." }
}
$firstInstall = Test-InstalledWorkspace
Test-PackageProfile seed

Invoke-BoundedProcess -FilePath $uninstaller -ArgumentList @("/S") -Label "Stock NSIS uninstall"
Wait-ForPathAbsence `
  -LiteralPaths @($uninstallRegistryPath, $installLocation) `
  -Label "Stock NSIS uninstall cleanup"
if (-not (Test-Path -LiteralPath $appDataRoot -PathType Container)) {
  throw "Stock silent uninstall unexpectedly removed the canonical app-data directory."
}
if (-not (Test-Path -LiteralPath $productRegistryPath)) {
  throw "Stock silent uninstall unexpectedly removed its preserved product registry key."
}
$preservedInstallLocation = [string](Get-Item -LiteralPath $productRegistryPath).GetValue("")
if (
  [string]::IsNullOrWhiteSpace($preservedInstallLocation) -or
  [System.IO.Path]::GetFullPath($preservedInstallLocation) -ine $installLocation
) {
  throw "Stock silent uninstall did not preserve the expected product install-location record."
}

Test-PackageProfile verify
Invoke-BoundedProcess -FilePath $installer.FullName -ArgumentList @("/S") -Label "Stock NSIS reinstall"
$reinstalled = if ($CheckOfflineHistory) {
  & (Join-Path $PSScriptRoot "test-installed-history-offline.ps1") -AppExecutable $appExecutable `
    -BrowserExecutables $firstInstall.browserExecutables -CheckWorkspace { Test-InstalledWorkspace -ReadHistory }
} else {
  Test-InstalledWorkspace
}
Test-PackageProfile verify
Invoke-BoundedProcess -FilePath $uninstaller -ArgumentList @("/S") -Label "Final stock NSIS uninstall"
Wait-ForPathAbsence -LiteralPaths @($uninstallRegistryPath, $installLocation) -Label "Final uninstall cleanup"
Test-PackageProfile verify

$afterSha256 = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
if ($afterSha256 -cne $beforeSha256) {
  throw "The NSIS installer changed during lifecycle verification."
}

$result = [ordered]@{
  schemaVersion = 1
  installer = $installer.FullName
  installerSha256 = $afterSha256
  appDataRoot = $appDataRoot
  installedVersion = $reinstalled.installedVersion
  installedResourceSha256 = $reinstalled.installedResourceSha256
  restoredOriginalMinimizedAndHiddenWindow = $true
  reinstallPreservedRecordingAndTwoRevisions = $true
  reinstallPreservedLocalDictation = $true
  offlineHistoryDisplayedCompleteDictation = [bool]$CheckOfflineHistory
  reinstallPreservedOrganizationRegistrationAndSignOut = $true
  stockSilentUninstallPreservedAppData = $true
  stockSilentUninstallPreservedProductRegistry = $true
  lifecycleBoundary = if ($isHostedDisposable) { "github-hosted" } else { "explicit-disposable-windows" }
}
$resultJson = $result | ConvertTo-Json -Depth 4
$resultRoot = Join-Path $desktopRoot "tests\results\nsis-smoke\$([Guid]::NewGuid().ToString('N'))"
$null = New-Item -ItemType Directory -Path $resultRoot
$resultJson | Set-Content -LiteralPath (Join-Path $resultRoot "evidence.json") -Encoding utf8
$resultJson
