#requires -Version 7.4
#requires -PSEdition Core

param(
  [Parameter(Mandatory)][string]$InstallLocation,
  [Parameter(Mandatory)][string]$RegisteredVersion
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$tauriRoot = Join-Path $PSScriptRoot "../../src-tauri"
$config = Get-Content -Raw -LiteralPath (Join-Path $tauriRoot "tauri.conf.json") | ConvertFrom-Json -AsHashtable
if ($RegisteredVersion -cne $config.version) {
  throw "Installed Yap version '$RegisteredVersion' differs from the expected '$($config.version)'."
}
$hashes = [ordered]@{}
foreach ($resource in $config.bundle.resources.GetEnumerator()) {
  $source = Join-Path $tauriRoot $resource.Key
  $installed = Join-Path $InstallLocation $resource.Value
  $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  $installedHash = (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash
  if ($sourceHash -cne $installedHash) {
    throw "Installed $($resource.Value) does not match the reviewed repository input."
  }
  $hashes[$resource.Value] = $installedHash
}
return [ordered]@{ installedVersion = $RegisteredVersion; installedResourceSha256 = $hashes }
